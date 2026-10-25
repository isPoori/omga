"""Unicode-aware visible-width measurement and wrapping.

Never use ``len(text)`` as a terminal column count: combining marks,
East-Asian wide glyphs, and ANSI escapes all break that assumption.
"""

from __future__ import annotations

import re
import unicodedata

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b.")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _char_width(ch: str) -> int:
    if not ch or ch in ("\n", "\r"):
        return 0
    code = ord(ch)
    if code == 0 or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    if code < 32 or (0x7F <= code < 0xA0):
        return 0
    east = unicodedata.east_asian_width(ch)
    if east in ("F", "W"):
        return 2
    return 1


def display_width(text: str) -> int:
    """Return the number of terminal columns *text* occupies."""
    total = 0
    for ch in strip_ansi(text):
        total += _char_width(ch)
    return total


def slice_display(text: str, start_col: int, width: int) -> str:
    """Return the substring occupying display columns [start_col, start_col+width)."""
    if width <= 0:
        return ""
    out: list[str] = []
    col = 0
    for ch in text:
        w = _char_width(ch)
        next_col = col + w
        if next_col <= start_col:
            col = next_col
            continue
        if col >= start_col + width:
            break
        if col < start_col:
            col = next_col
            continue
        if next_col - start_col > width:
            break
        out.append(ch)
        col = next_col
    return "".join(out)


def truncate(text: str, width: int, marker: str = "…") -> str:
    """Truncate *text* to *width* columns, preserving ANSI if present."""
    if width <= 0:
        return ""
    plain = strip_ansi(text)
    if display_width(plain) <= width:
        return text
    marker_w = display_width(marker)
    if marker_w >= width:
        return _take(plain, width)
    budget = width - marker_w
    return _take(plain, budget) + marker


def _take(text: str, width: int) -> str:
    out: list[str] = []
    used = 0
    for ch in text:
        w = _char_width(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


def wrap(text: str, width: int) -> list[str]:
    """Wrap *text* to *width* columns. Empty width yields a single empty line."""
    if width <= 0:
        return [""]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        remaining = paragraph
        while remaining:
            if display_width(remaining) <= width:
                lines.append(remaining)
                break
            chunk = _take(remaining, width)
            if not chunk:
                chunk = remaining[0]
            lines.append(chunk)
            remaining = remaining[len(chunk):]
    return lines or [""]


def pad(text: str, width: int, align: str = "left") -> str:
    visible = display_width(text)
    if visible >= width:
        return truncate(text, width)
    gap = width - visible
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def format_count(n: int | float | None) -> str:
    """Human-friendly token/count formatting: 1.2K, 24.8K, 1.2M."""
    if n is None:
        return "—"
    value = float(n)
    abs_n = abs(value)
    if abs_n < 1000:
        return str(int(value)) if value == int(value) else f"{value:.1f}"
    if abs_n < 1_000_000:
        scaled = value / 1000
        return f"{scaled:.1f}K".replace(".0K", "K")
    scaled = value / 1_000_000
    return f"{scaled:.1f}M".replace(".0M", "M")


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
