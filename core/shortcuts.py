"""Central keyboard shortcut registry.

Screens look up actions here instead of hard-coding chords. Ctrl+M cannot
be distinguished from Enter in a classic TTY (both send CR), so model
switching is bound to Ctrl+O and `/model`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ui.keys import Key


@dataclass(frozen=True)
class Shortcut:
    keys: tuple[str, ...]
    action: str
    label: str
    when: str = "session"


SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut(("ctrl-o",), "model", "Model"),
    Shortcut(("ctrl-p",), "provider", "Provider"),
    Shortcut(("ctrl-t",), "theme", "Theme"),
    Shortcut(("ctrl-k",), "palette", "Command palette"),
    Shortcut(("ctrl-l",), "clear", "Clear session"),
    Shortcut(("ctrl-y",), "copy", "Copy last reply"),
    Shortcut(("ctrl-c",), "cancel", "Cancel"),
    Shortcut(("ctrl-d",), "exit", "Exit"),
    Shortcut(("esc",), "back", "Back"),
    Shortcut(("?",), "help", "Help"),
)


def action_for(key: Key, *, when: str = "session") -> str | None:
    if key.name == "char" and key.char == "?" and when == "session":
        return "help"
    for item in SHORTCUTS:
        if when not in ("any", item.when) and item.when != "any":
            if item.when != when:
                continue
        if key.name in item.keys:
            return item.action
    return None


def help_rows(when: str = "session") -> list[tuple[str, str]]:
    rows = [
        ("↑ ↓", "Scroll chat (empty input)"),
        ("PgUp PgDn", "Scroll chat"),
        ("Mouse drag", "Select & copy chat text"),
        ("Ctrl+Y", "Copy last assistant reply"),
        ("Enter", "Send message"),
        ("Ctrl+N", "New line in prompt"),
        ("Esc", "Stop agent / back"),
        ("Ctrl+C", "Stop agent / clear / cancel"),
        ("Ctrl+D", "Exit"),
        ("Ctrl+O", "Model"),
        ("Ctrl+P", "Provider"),
        ("Ctrl+T", "Theme"),
        ("Ctrl+K", "Command palette"),
        ("Ctrl+L", "Clear"),
        ("?", "Help"),
        ("/", "Slash commands — see /help"),
    ]
    return rows
