"""Stateful TUI screens. Only the top screen receives keyboard events."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from core.branding import ASCII_LOGO, TAGLINE, heading
from core.errors import WizardInterrupted
from core.shortcuts import help_rows
from ui.glyphs import Glyphs
from ui.kernel import Action, BaseScreen, Frame, Line, Span, blank, hline
from ui.keys import Key
from ui.measure import format_count, truncate, wrap
from ui.theme import Theme, all_themes, get_theme
from ui.widgets import Editor, Option, Selector, chrome_frame, chrome_overhead


class SelectorScreen(BaseScreen):
    name = "selector"

    def __init__(
        self,
        title: str,
        options: Sequence[Option],
        *,
        subtitle: str = "",
        allow_search: bool = True,
        default_index: int = 0,
        hints: str | None = None,
        details: Callable[[Option], list[Line]] | None = None,
        preview: Callable[[Option, int, Glyphs], list[Line]] | None = None,
        on_highlight: Callable[[Option], None] | None = None,
    ) -> None:
        self.title = title
        self.subtitle = subtitle
        self.selector = Selector(options, allow_search=allow_search,
                                 default_index=default_index)
        self.hints = hints or "↑↓ Navigate   Enter Select   Esc Back"
        self.details = details
        self.preview = preview
        self.on_highlight = on_highlight
        self._last_value: Any = None

    def on_key(self, key: Key) -> Action:
        result = self.selector.handle(key)
        current = self.selector.selected()
        if current and self.on_highlight and current.value != self._last_value:
            self.on_highlight(current)
            self._last_value = current.value
        if result == "select" and current is not None:
            return Action.pop(current.value)
        if result == "cancel":
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        current = self.selector.selected()
        if current and self.on_highlight and current.value != self._last_value:
            self.on_highlight(current)
            self._last_value = current.value
        extra: list[Line] = []
        if self.preview and current:
            extra = self.preview(current, width, glyphs)[:10]
        elif self.details and current:
            extra = self.details(current)[:6]

        hints = self.hints
        overhead = chrome_overhead(subtitle=self.subtitle, hints=hints)
        details_h = (len(extra) + 1) if extra else 0
        avail = max(6, height - overhead - details_h)
        # Option viewport — shrink until rendered list fits avail (groups/counter)
        viewport = max(3, avail - 4)
        body = self.selector.lines(width, viewport, glyphs)
        while len(body) > avail and viewport > 3:
            viewport -= 1
            body = self.selector.lines(width, viewport, glyphs)
        if extra:
            body.append(blank())
            body.extend(extra)
        return chrome_frame(
            body, width, height, glyphs,
            title=self.title, subtitle=self.subtitle, hints=hints,
        )


class InputScreen(BaseScreen):
    name = "input"

    def __init__(
        self,
        title: str,
        prompt: str,
        *,
        secret: bool = False,
        subtitle: str = "",
        allow_empty: bool = False,
        single_line: bool | None = None,
    ) -> None:
        self.title = title
        self.prompt = prompt
        self.secret = secret
        self.subtitle = subtitle
        self.allow_empty = allow_empty
        # Secrets / keys default to single-line so paste never injects Enter/Esc.
        self.single_line = secret if single_line is None else single_line
        self.editor = Editor(single_line=self.single_line)

    def on_key(self, key: Key) -> Action:
        # Only a bare Esc cancels — never paste-end / unknown CSI
        if key.name == "esc":
            return Action.pop(None)
        if key.name in ("unknown", "paste-end", "mouse", "resize"):
            return Action.redraw()
        result = self.editor.handle(key)
        if result == "submit":
            text = self.editor.text.strip()
            if self.secret:
                from config.store import clean_api_key
                text = clean_api_key(text)
            if not text and not self.allow_empty:
                return Action.redraw()
            return Action.pop(text)
        if result == "cancel":
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        field_cols = max(8, width - 4)
        visible, cursor_in = self.editor.visible_segment(field_cols)
        if self.secret:
            from ui.measure import display_width as _dw
            shown = glyphs.bullet * _dw(visible)
        else:
            shown = visible
        body = [
            Line.plain(self.prompt, "fg"),
            blank(),
            Line.mixed(
                (glyphs.prompt + " ", "accent"),
                Span(shown, "fg"),
            ),
        ]
        n = len(self.editor.text.replace("\n", ""))
        if self.secret:
            body.append(Line.plain(
                f"Hidden · {n} chars  ·  paste key  ·  Enter saves  ·  Esc cancel",
                "muted",
            ))
        # cursor row: header(~4) + blank + prompt + blank + input ≈ 6 in chrome_frame
        cursor_col = 2 + cursor_in
        return chrome_frame(
            body, width, height, glyphs,
            title=self.title, subtitle=self.subtitle,
            hints="Enter save   Esc back   Ctrl+U clear line",
            cursor=(6, min(width - 1, cursor_col)),
        )


class ConfirmScreen(BaseScreen):
    name = "confirm"

    def __init__(self, title: str, message: str, *, default: bool = False,
                 yes: str = "Y", no: str = "N") -> None:
        self.title = title
        self.message = message
        self.default = default

    def on_key(self, key: Key) -> Action:
        if key.name == "enter":
            return Action.pop(self.default)
        if key.name in ("esc", "ctrl-c"):
            return Action.pop(False)
        if key.is_char:
            ch = key.char.lower()
            if ch in ("y",):
                return Action.pop(True)
            if ch in ("n",):
                return Action.pop(False)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body = [Line.plain(line, "fg") for line in wrap(self.message, width - 2)]
        body.append(blank())
        body.append(Line.plain("[Enter] default   [Y] Yes   [N] No   Esc cancel", "muted"))
        return chrome_frame(body, width, height, glyphs, title=self.title,
                            hints="Y / N / Enter / Esc")


class HelpScreen(BaseScreen):
    """Keyboard + slash help — full-height scrollable overlay."""

    name = "help"

    def __init__(self, when: str = "session") -> None:
        from cli.commands import help_lines

        lines: list[str] = [
            "KEYBOARD",
            "",
        ]
        for combo, desc in help_rows(when):
            lines.append(f"  {combo:<14} {desc}")
        lines.append("")
        lines.append("SLASH COMMANDS")
        lines.extend(help_lines())
        lines.append("")
        lines.append("TIPS")
        lines.append("  /model          Search, pick, or paste any model id")
        lines.append("  /proxy off      Force direct (ignore HTTPS_PROXY)")
        lines.append("  /memory         Facts OMGA remembers about you")
        lines.append("  ↑↓ / j k        Scroll this help · mouse wheel if OMGA_MOUSE=1")
        self._inner = MessageScreen(
            f"{heading()} · Help",
            lines,
            subtitle="↑↓ scroll  ·  PgUp/PgDn  ·  Enter closes",
        )

    def on_key(self, key: Key) -> Action:
        if key.is_char and key.char == "?":
            return Action.pop(None)
        return self._inner.on_key(key)

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        return self._inner.render(width, height, theme, glyphs)


class PaletteScreen(BaseScreen):
    name = "palette"

    def __init__(self) -> None:
        from cli.commands import palette_options

        opts = [
            Option(summary, cmd, searchable=f"{cmd} {summary}")
            for cmd, summary in palette_options()
        ]
        self.selector = Selector(opts, allow_search=True)

    def on_key(self, key: Key) -> Action:
        result = self.selector.handle(key)
        if result == "select":
            opt = self.selector.selected()
            return Action.pop(opt.value if opt else None)
        if result == "cancel":
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body = self.selector.lines(width, max(6, height - 8), glyphs)
        return chrome_frame(body, width, height, glyphs,
                            title=f"{heading()} · Commands",
                            hints="Type to search   Enter Run   Esc Back")


class ThemePreviewScreen(BaseScreen):
    name = "theme"

    def __init__(self, current: str = "ink") -> None:
        themes = all_themes()
        names = [t.name for t in themes]
        idx = names.index(current) if current in names else 0
        self.selector = Selector(
            [Option(t.name.capitalize(), t.name, searchable=t.name) for t in themes],
            allow_search=False,
            default_index=idx,
        )
        self.preview_name = current

    def on_key(self, key: Key) -> Action:
        result = self.selector.handle(key)
        opt = self.selector.selected()
        if opt:
            self.preview_name = opt.value
        if result == "select" and opt:
            return Action.pop(opt.value)
        if result == "cancel":
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        preview_theme = get_theme(self.preview_name)
        # The kernel paints with App.theme; session/wizard should swap App.theme
        # on highlight. The preview body still uses token names.
        viewport = max(4, min(6, height // 4))
        body = self.selector.lines(width, viewport, glyphs, show_search=False)
        body.append(blank())
        body.append(Line.plain("Preview", "muted"))
        body.append(hline(min(width, 40), glyphs))
        body.append(Line.plain("  OMGA", "primary", bold=True))
        body.append(blank())
        body.append(Line.plain("  You", "user", bold=True))
        body.append(Line.plain("  Fix the authentication bug.", "fg"))
        body.append(blank())
        body.append(Line.plain("  OMGA", "assistant", bold=True))
        body.append(Line.plain("  I'll inspect the project first.", "fg"))
        body.append(Line.mixed(
            (f"  {glyphs.success} ", "success"),
            ("Reading src/auth.ts", "tool"),
        ))
        body.append(Line.plain("  + Added line", "added"))
        body.append(Line.plain("  - Removed line", "removed"))
        body.append(hline(min(width, 40), glyphs))
        # Carry preview theme name in a span so App can pick it up.
        self._live_theme = preview_theme
        return chrome_frame(
            body, width, height, glyphs,
            title=f"{heading()} · Theme",
            subtitle="Preview updates as you move",
            hints="↑↓ Preview   Enter Select   Esc Back",
        )


class MessageScreen(BaseScreen):
    """Scrollable text overlay (help, status, command lists, …)."""

    name = "message"

    def __init__(
        self,
        title: str,
        lines: Sequence[str],
        *,
        kind: str = "info",
        subtitle: str = "",
    ) -> None:
        self.title = title
        self.subtitle = subtitle
        self.body_lines = list(lines)
        self.kind = kind
        self.offset = 0
        self._viewport = 10
        self._max_off = 0

    def on_key(self, key: Key) -> Action:
        if key.name in ("enter", "esc", "ctrl-c"):
            return Action.pop(True)
        if key.name in ("up", "wheel-up") or (key.is_char and key.char in ("k", "K")):
            self.offset = max(0, self.offset - 1)
            return Action.redraw()
        if key.name in ("down", "wheel-down") or (key.is_char and key.char in ("j", "J")):
            self.offset = min(self._max_off, self.offset + 1)
            return Action.redraw()
        if key.name == "page-up" or (key.is_char and key.char == "b"):
            self.offset = max(0, self.offset - self._viewport)
            return Action.redraw()
        if key.name == "page-down" or (key.is_char and key.char in (" ", "f")):
            self.offset = min(self._max_off, self.offset + self._viewport)
            return Action.redraw()
        if key.name == "home" or (key.is_char and key.char == "g"):
            self.offset = 0
            return Action.redraw()
        if key.name == "end" or (key.is_char and key.char == "G"):
            self.offset = self._max_off
            return Action.redraw()
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        token = {"error": "error", "success": "success", "warning": "warning"}.get(
            self.kind, "fg"
        )
        body: list[Line] = []
        for raw in self.body_lines:
            raw_s = str(raw)
            style = token
            stripped = raw_s.strip()
            # Section headers: ALL CAPS words (may include spaces)
            if (
                stripped
                and stripped == stripped.upper()
                and any(c.isalpha() for c in stripped)
                and not stripped.startswith("/")
                and len(stripped) < 40
            ):
                style = "accent"
            elif raw_s.startswith("  /"):
                style = "fg"
            for line in wrap(raw_s, max(8, width - 2)):
                body.append(Line.plain(line, style))

        hints_probe = "↑↓ scroll"
        overhead = chrome_overhead(subtitle=self.subtitle, hints=hints_probe)
        viewport = max(4, height - overhead)
        self._viewport = viewport
        self._max_off = max(0, len(body) - viewport)
        self.offset = max(0, min(self.offset, self._max_off))
        window = body[self.offset : self.offset + viewport]

        if self._max_off > 0:
            end = min(len(body), self.offset + viewport)
            hints = (
                f"↑↓/jk  ·  {self.offset + 1}–{end}/{len(body)}  ·  "
                f"PgUp/PgDn  ·  Enter close"
            )
        else:
            hints = "Enter / Esc close"
        return chrome_frame(
            window, width, height, glyphs,
            title=self.title, subtitle=self.subtitle, hints=hints,
        )


class LoadingScreen(BaseScreen):
    name = "loading"
    tick_interval = 0.08

    def __init__(self, title: str, message: str) -> None:
        self.title = title
        self.message = message
        self.frame_i = 0
        self.done_value: Any = Ellipsis  # sentinel: still loading

    def finish(self, value: Any) -> None:
        self.done_value = value

    def tick(self) -> None:
        self.frame_i += 1

    def poll(self) -> Action | None:
        if self.done_value is not Ellipsis:
            return Action.pop(self.done_value)
        return None

    def on_key(self, key: Key) -> Action:
        if self.done_value is not Ellipsis:
            return Action.pop(self.done_value)
        if key.name in ("esc", "ctrl-c"):
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        if self.done_value is not Ellipsis:
            # Next key or tick will pop; still show loading until then.
            pass
        spin = glyphs.spinner[self.frame_i % len(glyphs.spinner)]
        body = [Line.mixed((f"{spin} ", "accent"), (self.message, "fg"))]
        return chrome_frame(body, width, height, glyphs, title=self.title,
                            hints="Esc Cancel")


class DiffScreen(BaseScreen):
    name = "diff"

    def __init__(self, files: list[dict], title: str = "Diff") -> None:
        self.files = files
        self.title = title
        self.file_index = 0
        self.offset = 0
        self.expanded = False

    def _current_lines(self, width: int) -> list[Line]:
        from ui.render import unified_diff

        if not self.files:
            return [Line.plain("No changes.", "muted")]
        item = self.files[self.file_index]
        path = str(item.get("path") or item.get("tool") or "")
        old = str(item.get("old_content", ""))
        new = str(item.get("new_content", item.get("content", "")))
        out: list[Line] = [
            Line.plain(truncate(path, width - 2), "primary", bold=True),
            Line.plain(""),
        ]
        if old or new:
            for d in unified_diff(old, new):
                if d.kind == "@":
                    out.append(Line.plain(truncate(d.text, width - 2), "info"))
                elif d.kind == "+":
                    no = f"{d.new_no:>4} " if d.new_no else "     "
                    out.append(Line.mixed(
                        Span(no, "muted"),
                        Span("+ ", "added", bold=True),
                        Span(truncate(d.text, max(8, width - 8)), "added"),
                    ))
                elif d.kind == "-":
                    no = f"{d.old_no:>4} " if d.old_no else "     "
                    out.append(Line.mixed(
                        Span(no, "muted"),
                        Span("- ", "removed", bold=True),
                        Span(truncate(d.text, max(8, width - 8)), "removed"),
                    ))
                else:
                    no = f"{(d.new_no or d.old_no or 0):>4} "
                    out.append(Line.mixed(
                        Span(no, "muted"),
                        Span("  ", "fg"),
                        Span(truncate(d.text, max(8, width - 8)), "fg"),
                    ))
        else:
            out.append(Line.plain(str(item.get("command") or item.get("tool") or ""), "fg"))
        return out

    def on_key(self, key: Key) -> Action:
        if key.name in ("esc", "ctrl-c"):
            return Action.pop("close")
        if key.name == "enter":
            self.expanded = not self.expanded
            return Action.redraw()
        if key.name in ("down", "wheel-down"):
            self.offset += 1 if key.name == "down" else 3
            return Action.redraw()
        if key.name in ("up", "wheel-up"):
            step = 1 if key.name == "up" else 3
            self.offset = max(0, self.offset - step)
            return Action.redraw()
        if key.name == "page-down":
            self.offset += 10
            return Action.redraw()
        if key.name == "page-up":
            self.offset = max(0, self.offset - 10)
            return Action.redraw()
        if key.name in ("tab", "right"):
            if self.files:
                self.file_index = (self.file_index + 1) % len(self.files)
                self.offset = 0
            return Action.redraw()
        if key.name == "left":
            if self.files:
                self.file_index = (self.file_index - 1) % len(self.files)
                self.offset = 0
            return Action.redraw()
        if key.is_char and key.char.lower() == "y":
            return Action.pop("apply")
        if key.is_char and key.char.lower() == "n":
            return Action.pop("reject")
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        rows = self._current_lines(width)
        self.offset = min(self.offset, max(0, len(rows) - 1))
        view = rows[self.offset:]
        body: list[Line] = []
        if len(self.files) > 1:
            body.append(Line.plain(
                f"File {self.file_index + 1} / {len(self.files)}", "muted"
            ))
        body.extend(view)
        return chrome_frame(
            body, width, height, glyphs,
            title=self.title,
            hints="Wheel/↑↓ Scroll   Tab Files   Y Apply   N Reject   Esc Close",
        )


class ApprovalScreen(BaseScreen):
    name = "approval"

    def __init__(self, description: str, files: list[dict]) -> None:
        self.description = description
        self.files = files

    def on_key(self, key: Key) -> Action:
        if key.name == "enter":
            return Action.pop("review")
        if key.is_char and key.char.lower() == "y":
            return Action.pop("apply")
        if key.name in ("esc",) or (key.is_char and key.char.lower() == "n"):
            return Action.pop("reject")
        if key.name == "ctrl-c":
            return Action.pop("reject")
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body = [
            Line.plain(self.description, "warning", bold=True),
            blank(),
        ]
        for item in self.files:
            kind = "M"
            if item.get("tool") == "write_file" and not item.get("old_content"):
                kind = "A"
            if item.get("tool") == "delete_file":
                kind = "D"
            path = item.get("path") or item.get("command") or ""
            body.append(Line.mixed(
                (f"  {kind} ", "accent"),
                (str(path), "fg"),
            ))
        body.append(blank())
        body.append(Line.plain("Review changes?", "fg"))
        body.append(Line.plain("  [Enter] Review   [Y] Apply   [N] Reject", "muted"))
        return chrome_frame(body, width, height, glyphs,
                            title=f"{heading()} · Approval",
                            hints="Enter Review   Y Apply   N Reject")


class FirstLaunchScreen(BaseScreen):
    name = "first_launch"

    def on_key(self, key: Key) -> Action:
        if key.name in ("enter",):
            return Action.pop("continue")
        if key.name in ("esc", "ctrl-c", "ctrl-d"):
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body: list[Line] = []
        if height >= 22:
            for i, row in enumerate(ASCII_LOGO):
                token = "primary" if i < 2 else "accent"
                body.append(Line.plain(row, token, bold=(i == 0)))
            body.append(Line.plain("  " + TAGLINE, "muted"))
            body.append(blank())
        body.extend([
            Line.plain("No configuration found.", "fg"),
            blank(),
            Line.plain("Let's configure your coding environment.", "muted"),
            blank(),
            Line.plain("  Provider", "fg"),
            Line.plain("  Endpoint (if required)", "muted"),
            Line.plain("  API key", "fg"),
            Line.plain("  Model", "fg"),
            Line.plain("  Theme", "fg"),
            blank(),
            Line.plain("[Enter] Continue", "accent"),
        ])
        return chrome_frame(body, width, height, glyphs,
                            title=f"{heading()} · First launch")


class TrustScreen(BaseScreen):
    name = "trust"

    def __init__(self, path: str) -> None:
        self.path = path

    def on_key(self, key: Key) -> Action:
        if key.name == "enter" or (key.is_char and key.char.lower() == "y"):
            return Action.pop(True)
        if key.name in ("esc", "ctrl-c") or (key.is_char and key.char.lower() == "n"):
            return Action.pop(False)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body = [
            Line.plain("Do you trust this folder?", "primary", bold=True),
            blank(),
            Line.plain(truncate(self.path, width - 2), "fg"),
            blank(),
            Line.plain(
                "OMGA can read, edit, and run commands inside this directory.",
                "muted",
            ),
            Line.plain("Only continue if this is a project you control.", "muted"),
            blank(),
            Line.plain("[Y] Yes, trust this folder", "success"),
            Line.plain("[N] No, go back", "error"),
        ]
        return chrome_frame(
            body, width, height, glyphs,
            title=f"{heading()} · Workspace",
            hints="Y Trust   N Cancel",
        )


class SetupProgressScreen(BaseScreen):
    """Non-interactive progress chrome used as a header helper."""


def setup_progress(step: int, glyphs: Glyphs) -> list[Line]:
    labels = ["Provider", "API key", "Model", "Theme"]
    lines: list[Line] = []
    for i, label in enumerate(labels, start=1):
        if i < step:
            mark, token = glyphs.success, "success"
        elif i == step:
            mark, token = glyphs.active, "accent"
        else:
            mark, token = glyphs.empty, "muted"
        lines.append(Line.mixed((f"  {mark} ", token), (label, "fg")))
    return lines


class SettingsScreen(BaseScreen):
    name = "settings"

    CATEGORIES = (
        ("credentials", "API key"),
        ("provider", "Provider"),
        ("model", "Model"),
        ("theme", "Theme"),
        ("general", "General"),
        ("interface", "Interface"),
        ("agent", "Agent"),
        ("tools", "Tools"),
        ("security", "Security"),
        ("terminal", "Terminal"),
        ("git", "Git"),
        ("performance", "Performance"),
        ("advanced", "Advanced"),
    )

    def __init__(self) -> None:
        opts = [Option(label, key, searchable=f"{key} {label}")
                for key, label in self.CATEGORIES]
        self.selector = Selector(opts, allow_search=False)

    def on_key(self, key: Key) -> Action:
        result = self.selector.handle(key)
        if result == "select":
            opt = self.selector.selected()
            return Action.pop(opt.value if opt else None)
        if result == "cancel":
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body = self.selector.lines(width, max(6, height - 8), glyphs, show_search=False)
        return chrome_frame(body, width, height, glyphs,
                            title=f"{heading()} · Settings",
                            hints="↑↓ Navigate   Enter Open   Esc Back")


def run_screen(screen, *, theme: Theme | None = None, backend=None):
    """Run a single screen to completion. Returns the popped value."""
    from ui.kernel import App, is_interactive

    if backend is None and not is_interactive():
        raise WizardInterrupted("Not an interactive terminal.", hint="")
    app = App(backend=backend, theme=theme)
    return app.run(screen)


def cancelled(value: Any) -> bool:
    return value is None
