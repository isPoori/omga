"""OMGA branding — ASCII wordmark + Unicode marks for the TUI."""

from __future__ import annotations

WORDMARK = "OMGA"
MARK = "◈"
TAGLINE = "the agent that grows with you"

# Compact monospaced wordmark (fits ~28 cols)
ASCII_LOGO = [
    "   ___  __  __  ____    _  ",
    "  / _ \\|  \\/  |/ ___|  / \\ ",
    " | | | | |\\/| | |  _  / _ \\",
    " | |_| | |  | | |_| |/ ___ \\",
    "  \\___/|_|  |_|\\____/_/   \\_\\",
]

# Narrower mark for tight terminals
ASCII_MARK = [
    "  ┌─┐ ┌┬┐ ┌─┐ ┌─┐",
    "  │ │ │││ │─┤ ├─┤",
    "  └─┘ ┴ ┴ └─┘ ┴ ┴",
]

SESSION_MARK = "◈"
USER_MARK = "›"
ASSISTANT_MARK = "◆"
TOOL_MARK = "⚙"
SYSTEM_MARK = "·"
MEMORY_MARK = "◉"
SKILL_MARK = "✦"


def badge() -> str:
    return "OMGA"


def heading() -> str:
    return f"{SESSION_MARK} OMGA"


def logo_plain() -> str:
    return "\n".join(ASCII_LOGO)


def logo_for_width(width: int) -> list[str]:
    """Pick a wordmark that fits the terminal width."""
    if width >= 34:
        return list(ASCII_LOGO)
    if width >= 22:
        return list(ASCII_MARK)
    return [f"  {SESSION_MARK} OMGA"]


def header_title(version: str = "") -> str:
    if version:
        return f"{SESSION_MARK} OMGA  ·  v{version}"
    return f"{SESSION_MARK} OMGA"
