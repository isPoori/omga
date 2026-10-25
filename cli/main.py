"""OMGA CLI — entry point, doctor, config, interactive session."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from config import store as cfg
from core.version import __version__
from core.errors import OmgaError, WizardInterrupted
from core.paths import config_file, log_file, secrets_file
from ui.console import OmgaConsole
from ui.theme import get_theme


def _console() -> OmgaConsole:
    return OmgaConsole(get_theme(cfg.get("theme", "ink")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omga",
        description="OMGA — self-improving AI coding agent for the terminal.",
        add_help=False,
    )
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("sub", nargs="?", default=None)
    parser.add_argument("args", nargs="*")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--safe", action="store_true",
                        help="Safe mode: extra approvals, no deletes.")
    parser.add_argument("--fix", action="store_true",
                        help="With `doctor`: auto-repair what we can.")
    return parser


_TABLE = {
    "omga": "Launch the interactive coding agent.",
    "omga init": "First-run / setup wizard.",
    "omga settings": "Open settings.",
    "omga config": "Show current configuration.",
    "omga config provider": "Change the AI provider.",
    "omga config model": "Change the default model.",
    "omga config key": "Update the API key.",
    "omga config theme": "Change the theme.",
    "omga config reset": "Reset configuration to defaults.",
    "omga config example": "Print an example config.yaml.",
    "omga doctor": "Run diagnostics.",
    "omga doctor --fix": "Diagnose and auto-repair (deps, dirs, PATH…).",
    "omga version": "Show version.",
    "omga help": "Show this help.",
}


def print_help() -> None:
    console = _console()
    console.plain()
    console.show_logo()
    console.info(
        f"OMGA v{__version__} — self-improving AI coding agent.\n"
        "Config: ~/.config/omga/config.yaml · Keys: secrets.json · State: state.sqlite",
        title="Help",
    )
    console.plain()
    for cmd, desc in _TABLE.items():
        console.console.print(f"  [bold]{cmd:<24}[/] {desc}")
    console.plain()
    console.console.print("  [dim]Providers:[/] openrouter · openai · anthropic · groq · deepseek ·")
    console.console.print("             ollama · together · mistral · fireworks · gemini · lmstudio · …")
    console.plain()


def _cmd_init(console: OmgaConsole) -> int:
    from core.wizard import Wizard
    ok = Wizard(console).run()
    return 0 if ok else 1


def _cmd_interactive(console: OmgaConsole, *, safe: bool = False) -> int:
    from providers import create_provider
    from core.project import detect_project
    from ui.session import run_session
    from ui.kernel import is_interactive

    if not cfg.has_config():
        from core.wizard import Wizard
        if not Wizard(console).run():
            return 1
    provider = create_provider()
    if not provider.validate_credentials():
        console.warning(
            f"No API key configured for {provider.name}. Run `omga init`.",
            title="Missing key",
        )
        return 1
    project = detect_project()
    theme = get_theme(cfg.get("theme", "ink"))
    if not is_interactive():
        console.error("OMGA needs an interactive terminal.", title="Terminal")
        return 1
    try:
        return run_session(provider, project, theme=theme, safe=safe)
    except WizardInterrupted:
        return 1
    except KeyboardInterrupt:
        return 130


def _cmd_config(console: OmgaConsole, sub: str | None, args: Sequence[str]) -> int:
    from core.wizard import Wizard

    if sub is None:
        show_config(console)
        return 0

    action = sub.lower()
    if action == "provider":
        return 0 if Wizard(console).run() else 1
    if action == "model":
        return 0 if Wizard(console).run(model_only=True) else 1
    if action == "key":
        return _cmd_config_key(console)
    if action == "theme":
        return 0 if Wizard(console).run(theme_only=True) else 1
    if action == "reset":
        cfg.reset_config()
        console.success("Configuration reset. Run `omga init` to reconfigure.")
        return 0
    if action in ("example", "sample", "template"):
        console.plain()
        console.console.print(cfg.export_example())
        return 0
    console.error(f"Unknown config subcommand: '{action}'.", title="Config")
    return 1


def _cmd_settings(console: OmgaConsole) -> int:
    from ui.kernel import App, is_interactive
    from ui.screens import SettingsScreen

    if not is_interactive():
        show_config(console)
        return 0
    theme = get_theme(cfg.get("theme", "ink"))
    category = App(theme=theme).run(SettingsScreen())
    if not category:
        return 0
    if category == "theme":
        from core.wizard import Wizard
        Wizard(console, theme).run(theme_only=True)
    elif category == "model":
        from core.wizard import Wizard
        Wizard(console, theme).run(model_only=True)
    elif category == "provider":
        from core.wizard import Wizard
        Wizard(console, theme).run()
    else:
        console.info(f"Use `/settings` inside `omga` to edit {category}.",
                     title="Settings")
    return 0


def _cmd_config_key(console: OmgaConsole) -> int:
    from ui.menus import ask_string
    from core.errors import WizardInterrupted as WI

    provider = cfg.get("provider", "openrouter")
    existing = cfg.get_api_key(provider)
    masked = (
        (existing[:4] + "…" + existing[-4:])
        if existing and len(existing) > 8
        else "(not set)"
    )
    console.info(
        f"Provider: {provider}\n"
        f"Current : {masked}\n"
        "Paste the raw key only (no Bearer, no quotes). Input is hidden.",
        title="Update API key",
    )
    try:
        key = ask_string(console.theme, "API key:", secret=True).strip()
    except WI:
        console.warning("Cancelled.")
        return 1
    if not key:
        console.error("No key entered.", title="Update API key")
        return 1
    try:
        cfg.set_api_key(provider, key)
    except ValueError as exc:
        console.error(str(exc), title="Update API key")
        return 1
    console.success(f"API key updated for {provider}.")
    return 0


def show_config(console: OmgaConsole) -> None:
    from providers import available_providers

    provider = cfg.get("provider", "openrouter")
    model = cfg.get("model", None) or "(auto)"
    theme = cfg.get("theme", "ink")
    key = cfg.get_api_key(provider)
    masked = _mask(key) if key else "(not set)"
    console.plain()
    console.info(
        f"Provider : {provider}\n"
        f"Model    : {model}\n"
        f"Theme    : {theme}\n"
        f"Mode     : {cfg.get('mode', 'agent')}\n"
        f"API key  : {masked}\n"
        f"Memory   : {cfg.get('agent.enable_memory', True)}\n"
        f"Skills   : {cfg.get('agent.enable_skills', True)}\n"
        "\nProviders: " + ", ".join(available_providers()) +
        "\n\nUse `omga config <provider|model|key|theme|example|reset>` to change values.",
        title="Configuration",
    )
    console.plain()
    yml = config_file().with_suffix(".yaml")
    console.console.print(f"  Config file : {yml if yml.exists() else config_file()}")
    console.console.print(f"  Secrets file: {secrets_file()}")
    console.console.print(f"  Log file    : {log_file()}")


def _mask(key: str) -> str:
    if len(key) <= 8:
        return "(set)"
    return key[:4] + "…" + key[-2:]


def _cmd_doctor(console: OmgaConsole, *, fix: bool = False) -> int:
    from core.doctor import run_doctor
    return run_doctor(console, fix=fix)


def _cmd_version(console: OmgaConsole) -> int:
    console.plain(f"OMGA  v{__version__}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from core import log
    log.debug(os.environ.get("OMGA_DEBUG") == "1")

    if args.version:
        print(f"OMGA  v{__version__}")
        return 0
    if args.help:
        print_help()
        return 0

    console = _console()
    command = (args.command or "").lower()
    safe = bool(getattr(args, "safe", False)) or os.environ.get("OMGA_SAFE") == "1"
    fix = bool(getattr(args, "fix", False))

    # Support: omga doctor --fix  and  omga doctor fix
    if command == "doctor" and (args.sub or "").lower() in ("fix", "--fix"):
        fix = True

    try:
        if command in ("", "chat", "repl"):
            return _cmd_interactive(console, safe=safe)
        if command in ("init", "setup"):
            return _cmd_init(console)
        if command in ("settings",):
            return _cmd_settings(console)
        if command == "config":
            return _cmd_config(console, args.sub, args.args)
        if command == "doctor":
            return _cmd_doctor(console, fix=fix)
        if command == "version":
            return _cmd_version(console)
        if command in ("help", "--help"):
            print_help()
            return 0
        console.error(
            f"Unknown command: '{command}'. Use `omga help`.",
            title="Command",
        )
        return 2
    except OmgaError as exc:
        console.error(exc.message, title="Error")
        if exc.hint:
            console.console.print(f"  [yellow]→ {exc.hint}[/]")
        return 1
    except KeyboardInterrupt:
        console.plain()
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
