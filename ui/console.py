"""Non-interactive console facade (doctor, config, help).

Interactive sessions do not use this class. It must never be used to
redraw menus — that belongs to ui.kernel.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.live import Live
from rich.text import Text

from core.branding import heading
from ui.render import (
    code_block,
    diff_panel,
    error_panel,
    info_panel,
    make_console,
    markdown,
    rule,
    success_panel,
    unified_diff,
    warning_panel,
)
from ui.theme import Theme, get_theme
from ui.terminal import terminal_size


class OmgaConsole:
    def __init__(self, theme: Theme | None = None) -> None:
        self.theme = theme or get_theme("ink")
        self.console = make_console(self.theme)

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.console = make_console(theme)

    def show_logo(self) -> None:
        self.console.print(f"  {heading()}")
        self.console.print()

    def print_logo(self) -> None:
        self.show_logo()

    def info(self, message: str, title: str = "Info") -> None:
        self.console.print(info_panel(message, self.theme, title))

    def success(self, message: str, title: str = "Success") -> None:
        self.console.print(success_panel(message, self.theme, title))

    def error(self, message: str, title: str = "Error") -> None:
        self.console.print(error_panel(message, self.theme, title))

    def warning(self, message: str, title: str = "Warning") -> None:
        self.console.print(warning_panel(message, self.theme, title))

    def plain(self, text: str = "") -> None:
        self.console.print(text)

    def separator(self, text: str = "") -> None:
        self.console.print(rule(text, self.theme))

    def code(self, code: str, language: str = "python", title: str = "") -> None:
        self.console.print(code_block(code, self.theme, language, title))

    def md(self, text: str) -> None:
        self.console.print(markdown(text, self.theme))

    def diff(self, old: str, new: str, *, title: str = "Proposed Changes",
             n: int = 3, label: str = "") -> None:
        lines = unified_diff(old, new, n=n)
        self.console.print(
            diff_panel(lines, self.theme, title=title, width=terminal_size()[0])
        )

    def live(self, renderable: Any = None) -> Live:
        return Live(
            renderable or Text(),
            console=self.console,
            refresh_per_second=16,
            vertical_overflow="visible",
            transient=True,
        )
