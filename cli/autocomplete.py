"""Slash-command autocomplete for the chat prompt."""

from __future__ import annotations

from cli.commands import COMMANDS, SlashCommand


def slash_query(text: str) -> str | None:
    """If *text* is a slash draft (no spaces yet, or trailing space for args), return the cmd prefix.

    Returns None when autocomplete should stay hidden.
    """
    if not text.startswith("/"):
        return None
    # Don't suggest once the user is typing arguments after a full command + space
    body = text[1:]
    if "\n" in body:
        return None
    if " " in body:
        return None  # already past the command token
    return body.lower()


def suggest_commands(prefix: str, *, limit: int = 8) -> list[SlashCommand]:
    """Rank slash commands matching *prefix* (may be empty → show popular)."""
    prefix = (prefix or "").lower().strip()
    scored: list[tuple[int, SlashCommand]] = []
    for cmd in COMMANDS:
        names = (cmd.name, *cmd.aliases)
        best = None
        for name in names:
            n = name.lower()
            if not prefix:
                best = 10
                break
            if n.startswith(prefix):
                best = 0 if n == prefix else 1
                break
            if prefix in n:
                best = 2
                break
            # fuzzy: all chars of prefix appear in order
            if _subseq(prefix, n):
                best = 3
                break
        if best is not None:
            scored.append((best, cmd))
    scored.sort(key=lambda t: (t[0], t[1].name))
    # Deduplicate by canonical name
    seen: set[str] = set()
    out: list[SlashCommand] = []
    for _, cmd in scored:
        if cmd.name in seen:
            continue
        seen.add(cmd.name)
        out.append(cmd)
        if len(out) >= limit:
            break
    return out


def _subseq(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)
