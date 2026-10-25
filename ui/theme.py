"""
Centralised theme tokens — professional ink/teal palette by default.

UI code only references semantic tokens, never raw hex.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

TOKENS = (
    "primary", "secondary",
    "success", "error", "warning", "info",
    "muted", "border",
    "added", "removed",
    "user", "assistant", "tool", "tool_output",
    "code", "accent",
    "bg", "fg", "selection", "highlight",
)


@dataclass(frozen=True)
class Theme:
    name: str
    colors: Mapping[str, str] = field(default_factory=dict)

    def __getitem__(self, token: str) -> str:
        try:
            return self.colors[token]
        except KeyError:
            raise KeyError(f"Unknown colour token '{token}'") from None

    def get(self, token: str, default: str = "") -> str:
        return self.colors.get(token, default)

    def style(self, token: str, bold: bool = False, dim: bool = False) -> str:
        colour = self.colors.get(token)
        if colour is None:
            return ""
        parts = []
        if bold:
            parts.append("bold")
        if dim:
            parts.append("dim")
        parts.append(colour)
        return " ".join(parts)


def _ink() -> Mapping[str, str]:
    """Default — charcoal + deep teal (matches the docs site)."""
    return {
        "bg": "#0b1214",
        "fg": "#e8eef0",
        "primary": "#2a9d8f",
        "secondary": "#7eb8b0",
        "accent": "#3dccc7",
        "success": "#3dd68c",
        "error": "#f07178",
        "warning": "#e6b450",
        "info": "#5eb1ff",
        "muted": "#7a8a90",
        "border": "#243033",
        "added": "#3dd68c",
        "removed": "#f07178",
        "user": "#3dccc7",
        "assistant": "#e8eef0",
        "tool": "#e6b450",
        "tool_output": "#9aa8ae",
        "code": "#5eb1ff",
        "selection": "#1a3030",
        "highlight": "#132022",
    }


def _light() -> Mapping[str, str]:
    return {
        "bg": "#f7faf9",
        "fg": "#142024",
        "primary": "#0d5c63",
        "secondary": "#1a7a74",
        "accent": "#0d5c63",
        "success": "#0f7a4a",
        "error": "#b42318",
        "warning": "#9a6700",
        "info": "#175cd3",
        "muted": "#5c6b70",
        "border": "#d0dcda",
        "added": "#0f7a4a",
        "removed": "#b42318",
        "user": "#0d5c63",
        "assistant": "#142024",
        "tool": "#9a6700",
        "tool_output": "#4b5c60",
        "code": "#175cd3",
        "selection": "#d7ece9",
        "highlight": "#eaf4f2",
    }


def _nord() -> Mapping[str, str]:
    return {
        "bg": "#2e3440",
        "fg": "#d8dee9",
        "primary": "#88c0d0",
        "secondary": "#81a1c1",
        "accent": "#8fbcbb",
        "success": "#a3be8c",
        "error": "#bf616a",
        "warning": "#ebcb8b",
        "info": "#88c0d0",
        "muted": "#616e88",
        "border": "#4c566a",
        "added": "#a3be8c",
        "removed": "#bf616a",
        "user": "#88c0d0",
        "assistant": "#d8dee9",
        "tool": "#ebcb8b",
        "tool_output": "#c8c8ce",
        "code": "#81a1c1",
        "selection": "#434c5e",
        "highlight": "#3b4252",
    }


def _minimal() -> Mapping[str, str]:
    return {
        "bg": "#0a0a0a",
        "fg": "#eaeaea",
        "primary": "#eaeaea",
        "secondary": "#a0a0a0",
        "accent": "#ffffff",
        "success": "#6fdd8b",
        "error": "#ff7b72",
        "warning": "#e3b341",
        "info": "#79c0ff",
        "muted": "#6e7681",
        "border": "#30363d",
        "added": "#6fdd8b",
        "removed": "#ff7b72",
        "user": "#ffffff",
        "assistant": "#eaeaea",
        "tool": "#e3b341",
        "tool_output": "#a0a0a0",
        "code": "#79c0ff",
        "selection": "#21262d",
        "highlight": "#161b22",
    }


def _dracula() -> Mapping[str, str]:
    return {
        "bg": "#282a36",
        "fg": "#f8f8f2",
        "primary": "#8be9fd",
        "secondary": "#50fa7b",
        "accent": "#ff79c6",
        "success": "#50fa7b",
        "error": "#ff5555",
        "warning": "#f1fa8c",
        "info": "#8be9fd",
        "muted": "#6272a4",
        "border": "#44475a",
        "added": "#50fa7b",
        "removed": "#ff5555",
        "user": "#ff79c6",
        "assistant": "#f8f8f2",
        "tool": "#f1fa8c",
        "tool_output": "#c8c8ce",
        "code": "#8be9fd",
        "selection": "#44475a",
        "highlight": "#3d3f52",
    }


def _dark() -> Mapping[str, str]:
    """Legacy alias → ink."""
    return _ink()


_REGISTRY: dict[str, Mapping[str, str]] = {
    "ink": _ink(),
    "dark": _dark(),
    "light": _light(),
    "nord": _nord(),
    "minimal": _minimal(),
    "dracula": _dracula(),
}

KNOWN_THEMES = tuple(_REGISTRY.keys())


def all_themes() -> list[Theme]:
    return [Theme(name, colors) for name, colors in _REGISTRY.items()]


def get_theme(name: str) -> Theme:
    key = (name or "ink").lower()
    colors = _REGISTRY.get(key)
    if colors is None:
        colors = _REGISTRY["ink"]
        key = "ink"
    return Theme(key, colors)


def token_names() -> tuple[str, ...]:
    return TOKENS
