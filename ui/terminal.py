"""Terminal capability helpers (compat surface for older imports)."""

from __future__ import annotations

from ui.glyphs import unicode_enabled
from ui.kernel import is_interactive, terminal_size
from ui.measure import truncate

__all__ = [
    "is_interactive",
    "supports_color",
    "terminal_size",
    "truncate",
    "RawInput",
    "unicode_enabled",
]


def supports_color() -> bool:
    from ui.ansi import color_mode
    return color_mode() != "none"


class RawInput:
    """Deprecated raw-input helper kept for tests that import sentinels."""

    CtrlC = "\x03"
    Enter = "\r"
    Esc = "\x1b"
    Backspace = "\x7f"
    Tab = "\t"

    def __enter__(self) -> "RawInput":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def getch(self) -> str:
        from ui.keys import read_utf8_char
        import sys
        if not sys.stdin.isatty():
            return ""
        return read_utf8_char(sys.stdin.fileno())

    def read_escape(self, first: str) -> str | None:
        return None
