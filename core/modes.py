"""Agent operating modes.

Modes change the system prompt and the default tool policy. They never
silently switch the user's provider.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    id: str
    name: str
    description: str
    read_only: bool = False
    plan_first: bool = False
    prompt: str = ""


MODES: dict[str, Mode] = {
    "auto": Mode(
        "auto", "Auto",
        "Choose the approach that fits the task.",
        prompt="Work autonomously. Inspect first, then change what is needed.",
    ),
    "ask": Mode(
        "ask", "Ask",
        "Read-only answers. No file writes or destructive commands.",
        read_only=True,
        prompt=(
            "Ask mode is read-only. Explain and analyse only. "
            "Do not modify files or run mutating commands. "
            "If the user asks you to create or edit a file, reply with exactly "
            "one short line: Ask mode is read-only. Switch to /agent to edit. "
            "Do not use markdown, numbered questions, or long refusals."
        ),
    ),
    "plan": Mode(
        "plan", "Plan",
        "Analyse and produce a numbered plan. Do not edit files yet.",
        read_only=True,
        plan_first=True,
        prompt=(
            "Plan mode: inspect the codebase and produce a numbered plan. "
            "Do not modify files or run mutating commands until the user "
            "explicitly asks to execute the plan."
        ),
    ),
    "edit": Mode(
        "edit", "Edit",
        "Focused file edits with diffs and approval.",
        prompt="Prefer precise file edits. Show intent before writing.",
    ),
    "agent": Mode(
        "agent", "Agent",
        "Full coding agent: read, edit, run, and verify.",
        prompt=(
            "Agent mode: you can read, write, search, and run commands. "
            "When the user asks to create or change a file, call edit_file "
            "or write_file immediately. Prefer edit_file for existing files. "
            "Infer a sensible path; "
            "help.txt, README, and similar names belong at the project root "
            "unless they say otherwise. Do not ask where the file should live. "
            "Do not refuse because of ask/plan from an earlier turn. "
            "Keep prose short. Use tools first, then a brief result."
        ),
    ),
    "review": Mode(
        "review", "Review",
        "Review git changes and report issues by severity.",
        read_only=True,
        prompt=(
            "Review mode: inspect git diff / status. Report issues as "
            "High / Medium / Low. Do not modify files unless asked."
        ),
    ),
    "think": Mode(
        "think", "Think",
        "Reason carefully. Inspect first. Prefer a short plan, then act.",
        prompt=(
            "Think mode: reason step by step before acting. Inspect the "
            "codebase, state assumptions, then make the smallest correct change. "
            "If the task is large, outline a short plan first."
        ),
    ),
    "debug": Mode(
        "debug", "Debug",
        "Focus on logs, stack traces, failing tests and root cause.",
        prompt=(
            "Debug mode: reproduce, isolate root cause, then propose a minimal fix. "
            "Prefer tests and logs over speculation."
        ),
    ),
}

DEFAULT_MODE = "agent"
_ALIASES = {
    "code": "agent",
    "coding": "agent",
    "execute": "agent",
}


def get_mode(mode_id: str | None) -> Mode:
    key = (mode_id or DEFAULT_MODE).lower().strip()
    key = _ALIASES.get(key, key)
    return MODES.get(key, MODES[DEFAULT_MODE])


def mode_ids() -> list[str]:
    return list(MODES)
