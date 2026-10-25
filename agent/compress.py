"""
Context compression — keep recent turns intact, summarize the middle.

When history grows past a soft token/char budget, older tool-heavy turns
are collapsed into a single system summary so the agent stays scalable.
"""

from __future__ import annotations

from core.models import Message

# Soft budgets (characters ≈ tokens for budgeting).
_SOFT_CHARS = 90_000
_HARD_CHARS = 140_000
_KEEP_RECENT = 16  # non-system messages to keep verbatim
_KEEP_SYSTEM = 6


def estimate_chars(messages: list[Message]) -> int:
    total = 0
    for m in messages:
        total += len(m.content or "")
        if m.tool_calls:
            for tc in m.tool_calls:
                total += len(tc.name) + len(str(tc.arguments))
    return total


def needs_compression(messages: list[Message], *, soft: int = _SOFT_CHARS) -> bool:
    return estimate_chars(messages) >= soft


def compress_history(
    messages: list[Message],
    *,
    soft: int = _SOFT_CHARS,
    hard: int = _HARD_CHARS,
    keep_recent: int = _KEEP_RECENT,
) -> list[Message]:
    """Return a compressed copy of *messages* when over budget."""
    if estimate_chars(messages) < soft:
        return list(messages)

    system = [m for m in messages if m.role == "system"][:_KEEP_SYSTEM]
    rest = [m for m in messages if m.role != "system"]

    if len(rest) <= keep_recent + 4:
        # Still too large: truncate oversized tool payloads.
        return system + [_truncate_message(m) for m in rest]

    head = rest[: max(2, len(rest) - keep_recent)]
    tail = rest[-keep_recent:]
    summary = _summarize_locally(head)
    summary_msg = Message(
        role="system",
        content=(
            "[Compressed earlier conversation]\n"
            f"{summary}\n"
            "Continue from the recent turns below. Do not redo finished work."
        ),
    )
    out = system + [summary_msg] + [_truncate_message(m) for m in tail]
    if estimate_chars(out) > hard:
        # Emergency: keep only system + last few user/assistant turns.
        slim_tail = [m for m in tail if m.role in ("user", "assistant")][-8:]
        out = system[:3] + [summary_msg] + slim_tail
    return out


def _truncate_message(m: Message, limit: int = 8_000) -> Message:
    content = m.content or ""
    if len(content) > limit:
        content = content[: limit - 20] + "\n… [truncated]"
    return Message(
        role=m.role,
        content=content,
        name=m.name,
        tool_call_id=m.tool_call_id,
        tool_calls=m.tool_calls,
    )


def _summarize_locally(messages: list[Message], *, max_chars: int = 4_000) -> str:
    """Extractive summary without an extra LLM call (always available)."""
    bullets: list[str] = []
    files: set[str] = set()
    tools_used: set[str] = set()
    user_asks: list[str] = []
    for m in messages:
        if m.role == "user" and m.content.strip():
            ask = m.content.strip().replace("\n", " ")
            if len(ask) > 160:
                ask = ask[:157] + "…"
            user_asks.append(ask)
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                tools_used.add(tc.name)
                args = tc.arguments or {}
                path = args.get("path") or args.get("file")
                if isinstance(path, str) and path:
                    files.add(path)
        if m.role == "tool" and m.name:
            tools_used.add(m.name)
    if user_asks:
        bullets.append("User goals: " + " | ".join(user_asks[-5:]))
    if files:
        shown = sorted(files)[:20]
        bullets.append("Files touched: " + ", ".join(shown))
    if tools_used:
        bullets.append("Tools used: " + ", ".join(sorted(tools_used)))
    # Keep a few short assistant conclusions.
    for m in messages:
        if m.role == "assistant" and (m.content or "").strip() and not m.tool_calls:
            text = m.content.strip().replace("\n", " ")
            if len(text) > 200:
                text = text[:197] + "…"
            bullets.append("Outcome: " + text)
            if len(bullets) >= 10:
                break
    text = "\n".join(f"- {b}" for b in bullets) or "- Earlier turns compressed."
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text
