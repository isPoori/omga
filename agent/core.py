"""
The OMGA coding agent — modular loop over a provider and a tool set.

Architecture (Hermes-inspired):
    Agent
      ├── provider          → streaming chat + tools
      ├── tools             → filesystem, edit, shell, git, memory, skills
      ├── prompt builder    → stable / context / volatile tiers
      ├── memory store      → SQLite sessions + FTS + profile
      ├── context compress  → scalable long conversations
      └── hooks             → UI rendering + approval callbacks
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.compress import compress_history, needs_compression
from agent.hooks import Hooks
from agent.prompt import build_system_prompt, project_context_summary
from core.errors import OmgaError, ToolDeniedError
from core.models import ChunkEvent, DoneEvent, Message, ToolCall, ToolCallEvent
from tools.registry import ToolRegistry
from tools.safety import assess as assess_safety

# Tools that mutate the workspace and may need approval.
_MUTATING = frozenset({"write_file", "edit_file", "delete_file", "run_command"})


class AgentCancelled(OmgaError):
    def __init__(self, message: str = "Stopped by the user.") -> None:
        super().__init__(message, hint="You can restart with a new request.")


class Agent:
    def __init__(
        self,
        provider,
        registry: ToolRegistry,
        *,
        hooks: Hooks | None = None,
        max_iterations: int = 60,
        temperature: float | None = None,
        max_tokens: int | None = None,
        mode: str = "agent",
        safe: bool = False,
        store: Any | None = None,
        session_id: str | None = None,
        skills: Any | None = None,
        project: Any | None = None,
        is_subagent: bool = False,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.hooks = hooks or Hooks()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.history: list[Message] = []
        self.mode = mode
        self.safe = safe
        self.store = store
        self.session_id = session_id
        self.skills = skills
        self.project = project
        self.is_subagent = is_subagent
        self.last_usage: dict[str, Any] = {}
        self._system_ready = False
        self._turns = 0
        self._complex_turn = False

    def _ensure_system(self) -> None:
        if self._system_ready:
            return
        root = self.registry.root
        project_summary = ""
        if self.project is not None:
            project_summary = project_context_summary(self.project)
        memories_block = ""
        if self.store is not None:
            try:
                hits = self.store.list_memories(cwd=str(root), limit=8)
                if hits:
                    memories_block = "\n".join(
                        f"- [{h.get('kind', 'note')}] {h.get('content', '')}"
                        for h in hits
                    )
            except Exception:
                pass
        text = build_system_prompt(
            root=root,
            mode=self.mode,
            safe=self.safe,
            project_summary=project_summary,
            memories_block=memories_block,
            skills=self.skills,
        )
        # Replace any prior OMGA system identity message.
        self.history = [
            m for m in self.history
            if not (m.role == "system" and (m.content or "").startswith("You are OMGA"))
        ]
        self.history.insert(0, Message(role="system", content=text))
        self._system_ready = True

    def add_context(self, context: str) -> None:
        if not context.strip():
            return
        if any(m.role == "system" and "Working directory:" in (m.content or "") for m in self.history):
            return
        self.history.append(Message(role="system", content=context))

    def run(self, request: str) -> str:
        """Execute *request* as a fresh agent turn. Returns the final text."""
        from tools import procs

        procs.set_cancel(self.hooks.cancelled)
        try:
            return self._run(request)
        finally:
            if self.hooks.cancelled():
                procs.kill_all()
            procs.set_cancel(None)

    def _run(self, request: str) -> str:
        self._ensure_system()
        self._turns += 1
        self._complex_turn = False
        user_msg = Message(role="user", content=request)
        self.history.append(user_msg)
        self._persist(user_msg)

        if needs_compression(self.history):
            self.hooks.progress("Compressing context…")
            self.history = compress_history(self.history)
            self._system_ready = True  # identity kept inside compressed history

        final_text = ""
        for iteration in range(self.max_iterations):
            if self.hooks.cancelled():
                raise AgentCancelled()

            tool_calls: list[ToolCallEvent] = []
            round_text: list[str] = []
            tools = self._tools_for_mode()

            try:
                for evt in self.provider.chat(
                    self.history,
                    tools=tools or None,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                ):
                    if self.hooks.cancelled():
                        raise AgentCancelled()
                    if isinstance(evt, ChunkEvent):
                        round_text.append(evt.text)
                        self.hooks.stream(evt.text)
                    elif isinstance(evt, ToolCallEvent):
                        tool_calls.append(evt)
                    elif isinstance(evt, DoneEvent):
                        if evt.usage:
                            self.last_usage = evt.usage
                            self.hooks.usage(evt.usage)
                        break
            except AgentCancelled:
                raise
            except OmgaError:
                raise

            from core.security import scrub_output

            assistant_text = scrub_output("".join(round_text))
            tc_models = [
                ToolCall(id=c.id, name=c.name, arguments=c.arguments)
                for c in tool_calls
            ] or None
            if assistant_text or tool_calls:
                asst = Message(
                    role="assistant",
                    content=assistant_text,
                    tool_calls=tc_models,
                )
                self.history.append(asst)
                self._persist(asst)

            if not tool_calls:
                final_text = assistant_text
                self._maybe_learn_nudge(final_text, iteration)
                self.hooks.final(final_text)
                return final_text

            if len(tool_calls) >= 3 or iteration >= 5:
                self._complex_turn = True

            for call in tool_calls:
                if self.hooks.cancelled():
                    raise AgentCancelled()
                tool = self.registry.get(call.name)
                if tool is None:
                    result: Any = {"error": f"Unknown tool: {call.name}"}
                else:
                    self.hooks.tool_start(call.name, call.arguments)
                    try:
                        result = self._dispatch(tool, call.arguments)
                    except ToolDeniedError as exc:
                        result = {
                            "error": str(exc),
                            "note": "The user did not approve this action. "
                                    "Do not retry it; propose an alternative.",
                        }
                    except OmgaError as exc:
                        result = {"error": str(exc)}
                    self.hooks.tool_result(call.name, result)
                payload = _stringify(result)
                if len(payload) > 24_000:
                    payload = payload[:24_000] + "\n… truncated"
                tool_msg = Message(
                    role="tool",
                    content=payload,
                    name=call.name,
                    tool_call_id=call.id,
                )
                self.history.append(tool_msg)
                self._persist(tool_msg)

            if needs_compression(self.history):
                self.history = compress_history(self.history)

        raise OmgaError(
            "The agent reached its iteration limit.",
            hint="The task may need to be broken into smaller steps.",
        )

    def _maybe_learn_nudge(self, final_text: str, iterations: int) -> None:
        """Closed learning loop: nudge persistence after complex work."""
        if self.is_subagent or not self._complex_turn:
            return
        if iterations < 4:
            return
        # Soft nudge via a system note for the *next* turn only if skills exist.
        if self.skills is None:
            return
        nudge = (
            "[Learning nudge] This turn was complex. If the procedure will recur, "
            "consider create_skill or remember(also_profile=true) before ending."
        )
        # Attach only when the model didn't already create a skill this turn.
        recent_tools = [
            m.name for m in self.history[-20:]
            if m.role == "tool" and m.name
        ]
        if "create_skill" in recent_tools or "remember" in recent_tools:
            return
        # Do not inject into history mid-flight after final — store as session note.
        if self.store and self.session_id:
            try:
                self.store.touch_session(self.session_id, summary=(final_text or "")[:500])
            except Exception:
                pass
        _ = nudge  # reserved for future explicit nudge injection

    def _persist(self, message: Message) -> None:
        if not self.store or not self.session_id:
            return
        try:
            tool_calls = None
            if message.tool_calls:
                tool_calls = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in message.tool_calls
                ]
            self.store.append_message(
                self.session_id,
                role=message.role,
                content=message.content or "",
                name=message.name,
                tool_call_id=message.tool_call_id,
                tool_calls=tool_calls,
            )
        except Exception:
            pass

    def _dispatch(self, tool, args: dict[str, Any]) -> Any:
        from core.modes import get_mode

        mode = get_mode(self.mode)
        if mode.read_only and tool.name in ("write_file", "edit_file", "delete_file"):
            raise ToolDeniedError(
                f"{tool.name} is disabled in {mode.name} mode (read-only)."
            )
        if mode.read_only and tool.name == "run_command":
            if assess_safety(str(args.get("command", ""))).requires_confirmation:
                raise ToolDeniedError(
                    f"Destructive commands are disabled in {mode.name} mode."
                )
        if self.safe and tool.name == "delete_file":
            raise ToolDeniedError("delete_file is disabled in safe mode.")

        from config.store import get

        auto = bool(get("agent.auto_approve", False))
        if tool.name in _MUTATING and not auto:
            destructive = _looks_destructive(tool.name, args, self.registry.root)
            if destructive or self.safe:
                if tool.name in ("write_file", "edit_file"):
                    path = str(args.get("path", ""))
                    old = _existing_content(self.registry.root, path)
                    if tool.name == "write_file":
                        new = str(args.get("content", ""))
                    else:
                        old_s = str(args.get("old_string", ""))
                        new_s = str(args.get("new_string", ""))
                        if args.get("replace_all"):
                            new = old.replace(old_s, new_s)
                        else:
                            new = old.replace(old_s, new_s, 1)
                    files = [{
                        "tool": tool.name,
                        "path": path,
                        "old_content": old,
                        "new_content": new,
                    }]
                else:
                    files = [{"tool": tool.name, **args}]
                approved = self.hooks.approve(
                    f"OMGA wants to {_verb(tool.name)}.",
                    files,
                )
                if not approved:
                    raise ToolDeniedError(f"{tool.name} was not approved.")
        return tool.run(**args)

    def _tools_for_mode(self) -> list[dict[str, Any]]:
        from core.modes import get_mode

        mode = get_mode(self.mode)
        schemas = self.registry.schemas()
        if not mode.read_only:
            return schemas
        blocked = {"write_file", "edit_file", "delete_file", "run_command", "create_skill"}
        return [
            s for s in schemas
            if (s.get("function") or {}).get("name") not in blocked
        ]


def _stringify(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)
    return str(result)


def _verb(tool: str) -> str:
    return {
        "write_file": "write to a file",
        "edit_file": "edit a file",
        "delete_file": "delete a file",
        "run_command": "run a shell command",
    }.get(tool, "run a command")


def _looks_destructive(tool: str, args: dict, root: Path) -> bool:
    from config.store import get

    if tool == "delete_file":
        return True
    if tool in ("write_file", "edit_file"):
        path = str(args.get("path", ""))
        exists = (root / path).exists()
        always = bool(get("system.confirm_destructive", True))
        return exists or always
    if tool == "run_command":
        return assess_safety(str(args.get("command", ""))).requires_confirmation
    return False


def _existing_content(root: Path, path: str) -> str:
    try:
        return (root / path).read_text(encoding="utf-8")
    except OSError:
        return ""
