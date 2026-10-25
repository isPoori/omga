"""ANSI colour helpers driven by theme tokens.

Supports truecolor, 256-color, 16-color and NO_COLOR. Interactive
rendering never counts escape sequences as visible width — callers
always measure the plain text separately.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.theme import Theme


def color_mode() -> str:
    if os.environ.get("NO_COLOR") or os.environ.get("OMGA_NO_COLOR"):
        return "none"
    forced = os.environ.get("OMGA_COLOR", "").strip().lower()
    if forced in ("0", "none", "off", "no"):
        return "none"
    if forced in ("16", "ansi"):
        return "16"
    if forced in ("256",):
        return "256"
    if forced in ("true", "truecolor", "24bit", "1", "on"):
        return "truecolor"
    colorterm = os.environ.get("COLORTERM", "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return "truecolor"
    term = os.environ.get("TERM", "")
    if "256color" in term:
        return "256"
    if term in ("dumb", ""):
        return "none"
    if not sys.stdout.isatty():
        return "none"
    return "256"


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        return None
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return None


def _to_256(r: int, g: int, b: int) -> int:
    return 16 + 36 * (r * 5 // 255) + 6 * (g * 5 // 255) + (b * 5 // 255)


def style_open(theme: "Theme", token: str, *, bold: bool = False, dim: bool = False,
               inverse: bool = False) -> str:
    mode = color_mode()
    if mode == "none":
        return ""
    parts: list[str] = []
    if bold:
        parts.append("1")
    if dim:
        parts.append("2")
    if inverse:
        parts.append("7")
    colour = theme.get(token, "")
    rgb = _hex_to_rgb(colour) if colour.startswith("#") else None
    if rgb:
        r, g, b = rgb
        if mode == "truecolor":
            parts.append(f"38;2;{r};{g};{b}")
        elif mode == "256":
            parts.append(f"38;5;{_to_256(r, g, b)}")
        else:
            parts.append(_approx_16(r, g, b))
    if not parts:
        return ""
    return "\x1b[" + ";".join(parts) + "m"


def style_close() -> str:
    if color_mode() == "none":
        return ""
    return "\x1b[0m"


def paint(text: str, theme: "Theme", token: str, *, bold: bool = False,
          dim: bool = False, inverse: bool = False) -> str:
    open_ = style_open(theme, token, bold=bold, dim=dim, inverse=inverse)
    if not open_:
        return text
    return f"{open_}{text}{style_close()}"


def _approx_16(r: int, g: int, b: int) -> str:
    # Map to the closest basic ANSI foreground.
    bright = max(r, g, b) > 180
    idx = (r >= 128) * 1 + (g >= 128) * 2 + (b >= 128) * 4
    code = 30 + idx
    if bright and idx:
        code += 60
    return str(code)
