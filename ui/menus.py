"""Public menu helpers — thin wrappers over the TUI selector/editor.

Interactive calls run inside the kernel (one frame, exclusive keys).
Non-interactive callers get the default option without rendering.
"""

from __future__ import annotations

from typing import Any, Sequence

from core.errors import WizardInterrupted
from ui.kernel import App, HeadlessBackend, is_interactive
from ui.keys import Key
from ui.screens import ConfirmScreen, InputScreen, SelectorScreen
from ui.theme import Theme
from ui.widgets import Option, Selector

# Re-export for callers / tests.
__all__ = ["Option", "Select", "Prompt", "Confirm", "ask_string", "ask_confirm", "ask_choice"]


class Select:
    def __init__(
        self,
        theme: Theme,
        prompt: str,
        options: Sequence[Option],
        *,
        multi: bool = False,
        allow_search: bool = True,
        interactive: bool | None = None,
        console=None,
    ) -> None:
        self.theme = theme
        self.prompt = prompt
        self.options = list(options)
        self.multi = multi
        self.allow_search = allow_search
        self.interactive = is_interactive() if interactive is None else interactive
        self.selector = Selector(self.options, allow_search=allow_search)

    def run(self, default_index: int = 0) -> Any:
        if not self.options:
            raise WizardInterrupted("No options to choose from.", hint="")
        if not self.interactive:
            return self.options[default_index].value
        screen = SelectorScreen(
            self.prompt, self.options,
            allow_search=self.allow_search,
            default_index=default_index,
        )
        app = App(theme=self.theme)
        value = app.run(screen)
        if value is None:
            raise WizardInterrupted("Cancelled.", hint="")
        return value


class Prompt:
    def __init__(self, theme: Theme, message: str, *, secret: bool = False,
                 console=None, interactive: bool | None = None) -> None:
        self.theme = theme
        self.message = message
        self.secret = secret
        self.interactive = is_interactive() if interactive is None else interactive

    def run(self, default: str = "") -> str:
        if not self.interactive:
            try:
                raw = input(f"  {self.message}: ")
            except (KeyboardInterrupt, EOFError):
                raise WizardInterrupted("Input cancelled.", hint="") from None
            return raw or default
        screen = InputScreen("OMGA", self.message, secret=self.secret, allow_empty=True)
        value = App(theme=self.theme).run(screen)
        if value is None:
            raise WizardInterrupted("Input cancelled.", hint="")
        return value or default


class Confirm:
    def __init__(self, theme: Theme, message: str, *, default: bool = False,
                 console=None, interactive: bool | None = None) -> None:
        self.theme = theme
        self.message = message
        self.default = default
        self.interactive = is_interactive() if interactive is None else interactive

    def run(self) -> bool:
        if not self.interactive:
            try:
                raw = input(f"  {self.message} [{'Y/n' if self.default else 'y/N'}] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                raise WizardInterrupted("Input cancelled.", hint="") from None
            if not raw:
                return self.default
            return raw in ("y", "yes")
        value = App(theme=self.theme).run(ConfirmScreen("OMGA", self.message, default=self.default))
        return bool(value)


def ask_string(theme: Theme, message: str, *, default: str = "",
               secret: bool = False) -> str:
    return Prompt(theme, message, secret=secret).run(default=default)


def ask_confirm(theme: Theme, message: str, *, default: bool = False) -> bool:
    return Confirm(theme, message, default=default).run()


def ask_choice(
    theme: Theme,
    prompt: str,
    labels: Sequence[str],
    *,
    default_index: int = 0,
    interactive: bool | None = None,
) -> str:
    opts = [Option(label, label, searchable=label) for label in labels]
    return Select(
        theme, prompt, opts, allow_search=False, interactive=interactive
    ).run(default_index)


def drive_selector(selector: Selector, keys: Sequence[Key]) -> Any:
    """Test helper: apply keys to a selector and return the selected value."""
    for key in keys:
        result = selector.handle(key)
        if result == "select":
            opt = selector.selected()
            return None if opt is None else opt.value
        if result == "cancel":
            raise WizardInterrupted("Cancelled.", hint="")
    opt = selector.selected()
    return None if opt is None else opt.value
