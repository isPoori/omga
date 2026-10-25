"""Central slash-command registry for the interactive session."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    summary: str
    group: str = "session"
    aliases: tuple[str, ...] = ()


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("help", "Show keyboard shortcuts and commands", "general"),
    SlashCommand("exit", "Quit OMGA", "general", ("quit",)),
    SlashCommand("clear", "Clear transcript and start a fresh session", "session"),
    SlashCommand("stop", "Cancel the running agent turn", "session", ("cancel",)),
    SlashCommand("compress", "Compress conversation context", "session"),
    SlashCommand("status", "Show provider, model, tools, session id", "session"),
    SlashCommand("usage", "Token and tool usage for this session", "session"),
    SlashCommand("model", "Pick, search, or paste a model id", "config"),
    SlashCommand("provider", "Switch AI provider", "config"),
    SlashCommand("theme", "Preview and set theme", "config"),
    SlashCommand("mode", "Switch operating mode", "config"),
    SlashCommand("settings", "Open settings", "config"),
    SlashCommand("key", "Set / update API key for current provider", "config", ("apikey", "api-key")),
    SlashCommand(
        "proxy",
        "Proxy: /proxy 7890 · /proxy off · /proxy test",
        "config",
        ("https-proxy",),
    ),
    SlashCommand("copy", "Copy last assistant reply to clipboard", "session", ("yank",)),
    SlashCommand("ask", "Read-only Ask mode", "modes"),
    SlashCommand("plan", "Plan mode — no edits yet", "modes"),
    SlashCommand("agent", "Full agent mode", "modes", ("code",)),
    SlashCommand("think", "Careful reasoning mode", "modes", ("thinking",)),
    SlashCommand("edit", "Focused edit mode", "modes"),
    SlashCommand("debug", "Debug / root-cause mode", "modes"),
    SlashCommand("review", "Review git changes", "modes"),
    SlashCommand("auto", "Auto mode", "modes"),
    SlashCommand("execute", "Execute the last plan", "modes"),
    SlashCommand("memory", "Browse long-term memory", "memory"),
    SlashCommand("skills", "Browse procedural skills", "memory"),
    SlashCommand("sessions", "List past sessions", "memory", ("history",)),
)


def resolve(name: str) -> SlashCommand | None:
    key = name.lower().strip()
    for cmd in COMMANDS:
        if cmd.name == key or key in cmd.aliases:
            return cmd
    return None


def palette_options() -> list[tuple[str, str]]:
    return [(c.name, c.summary) for c in COMMANDS]


def help_lines() -> list[str]:
    lines: list[str] = []
    group = ""
    for c in COMMANDS:
        if c.group != group:
            group = c.group
            lines.append("")
            lines.append(group.upper())
        alias = f" ({', '.join('/' + a for a in c.aliases)})" if c.aliases else ""
        lines.append(f"  /{c.name:<12} {c.summary}{alias}")
    return lines
