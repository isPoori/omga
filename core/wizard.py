"""First-run / redo configuration wizard — state-driven TUI screens."""

from __future__ import annotations

import threading

from core.branding import ASCII_LOGO, heading
from config import store as cfg
from core.errors import NetworkError, OmgaError, ProviderError, WizardInterrupted
from core.models import Model
from providers import create_provider, provider_info_registry
from ui.glyphs import Glyphs
from ui.kernel import Action, App, BaseScreen, Frame, Line, Span, blank, is_interactive
from ui.keys import Key
from ui.screens import (
    ConfirmScreen,
    FirstLaunchScreen,
    InputScreen,
    MessageScreen,
    SelectorScreen,
    ThemePreviewScreen,
    setup_progress,
)
from ui.theme import Theme, get_theme
from ui.widgets import Option, chrome_frame
from ui.measure import format_count


class WizardApp(BaseScreen):
    """A single root screen that hosts setup steps as exclusive overlays."""

    name = "wizard"
    tick_interval = 0.08

    def __init__(self, *, model_only: bool = False, theme_only: bool = False,
                 theme: Theme | None = None, show_intro: bool = True) -> None:
        self.theme = theme or get_theme(cfg.get("theme", "ink"))
        self.model_only = model_only
        self.theme_only = theme_only
        self.show_intro = show_intro and not model_only and not theme_only
        self.overlay: BaseScreen | None = None
        self.step = 0
        self.provider_id: str | None = None
        self.model: str | None = None
        self.theme_name: str | None = None
        self.done = False
        self.ok = False
        self._load = None
        self._spin = 0
        self._app_ref: App | None = None
        self._boot()

    def _boot(self) -> None:
        if self.theme_only:
            self._open(ThemePreviewScreen(cfg.get("theme", "ink")), "theme")
            return
        if self.model_only:
            self._fetch_models(cfg.get("provider", "openrouter"))
            return
        if self.show_intro:
            self._open(FirstLaunchScreen(), "intro")
            return
        self._open_provider()

    def _open(self, screen: BaseScreen, kind: str) -> None:
        self.overlay = screen
        self._kind = kind

    def _open_provider(self) -> None:
        self.step = 1
        registry = provider_info_registry()
        opts = []
        for info in registry.values():
            hint = "requires base URL" if info.requires_base_url else "hosted"
            opts.append(Option(
                info.name, info.id,
                hint=hint,
                searchable=f"{info.name} {info.id} {hint}",
                meta=hint,
            ))
        self._open(
            SelectorScreen(
                f"{heading()} · Setup · Provider",
                opts,
                subtitle="Choose your AI router",
                allow_search=False,
            ),
            "provider",
        )

    def _open_endpoint(self) -> None:
        pid = self.provider_id or "provider"
        current = cfg.get(f"endpoints.{pid}", "") or ""
        info = provider_info_registry().get(pid)
        default = (info.default_base_url if info else "") or ""
        self._open(
            InputScreen(
                f"{heading()} · Setup · Endpoint",
                f"Base URL for {pid}",
                subtitle=f"Example: {default or 'https://host/api/v1'}",
                allow_empty=False,
            ),
            "endpoint",
        )
        if current:
            self.overlay.editor.set_text(str(current))  # type: ignore[union-attr]

    def _open_key(self) -> None:
        self.step = 2
        name = self.provider_id or "provider"
        self._open(
            InputScreen(
                f"{heading()} · Setup · 2/4",
                f"Enter your {name} API key",
                secret=True,
                subtitle="Stored securely. Never logged.",
            ),
            "key",
        )

    def _fetch_models(self, provider_id: str) -> None:
        self.step = 3
        self._open(
            _BusyScreen(f"{heading()} · Setup · 3/4",
                        f"Fetching models from {provider_id}…"),
            "fetch",
        )
        result: dict = {}

        def work() -> None:
            try:
                from core import cache
                cached = cache.get_cached_models(provider_id)
                if cached:
                    result["models"] = cached
                    return
                prov = create_provider(provider_id)
                models = prov.list_models()
                cache.store_models(provider_id, models)
                result["models"] = models
            except (NetworkError, ProviderError, OmgaError) as exc:
                result["error"] = exc
            except Exception as exc:  # pragma: no cover
                result["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self._load = (thread, result)

    def _open_model(self, models: list[Model]) -> None:
        self.step = 3
        if not models:
            self._open(
                InputScreen(
                    f"{heading()} · Setup · 3/4",
                    "Model ID",
                    subtitle="Could not fetch a live list — enter an ID",
                ),
                "model-manual",
            )
            return
        recents = list(cfg.get("recent_models") or [])
        opts: list[Option] = []
        seen: set[str] = set()
        for m in models:
            group = "Recent" if m.id in recents else "All models"
            if m.id in seen:
                continue
            seen.add(m.id)
            meta = []
            if m.context_window:
                meta.append(f"{format_count(m.context_window)} context")
            if m.capabilities:
                meta.append(" · ".join(m.capabilities[:3]))
            opts.append(Option(
                m.display, m.id,
                searchable=f"{m.id} {m.display}",
                meta=" · ".join(meta),
                group=group,
            ))
        # Recents first
        opts.sort(key=lambda o: (0 if o.group == "Recent" else 1, o.label.lower()))
        self._open(
            SelectorScreen(
                f"{heading()} · Setup · 3/4",
                opts,
                subtitle="Choose your model",
                allow_search=True,
            ),
            "model",
        )

    def _open_theme(self) -> None:
        self.step = 4
        screen = ThemePreviewScreen(cfg.get("theme", "ink"))
        self._open(screen, "theme")

    def _open_done(self) -> None:
        self._open(_DoneScreen(self.provider_id or "", self.model or "",
                               self.theme_name or "ink"), "done")

    def poll(self) -> Action | None:
        if self.overlay is not None and hasattr(self.overlay, "poll"):
            child = self.overlay.poll()
            if child is not None and child.kind == "pop":
                self._handle(self._kind, child.value)
                return Action.redraw()
        if self._kind == "fetch" and self._load:
            thread, result = self._load
            if not thread.is_alive():
                self._load = None
                if "error" in result:
                    self._open(
                        _FetchFailedScreen(str(result["error"])),
                        "fetch-fail",
                    )
                else:
                    self._open_model(result.get("models") or [])
        if self.done:
            return Action.quit(self.ok)
        return None

    def tick(self) -> None:
        self._spin += 1
        if self.overlay is not None and hasattr(self.overlay, "tick"):
            self.overlay.tick()
        if self._kind == "theme" and self.overlay is not None:
            name = getattr(self.overlay, "preview_name", None)
            if name and self._app_ref:
                self._app_ref.set_theme(get_theme(name))

    def on_key(self, key: Key) -> Action:
        if self.overlay is None:
            if key.name in ("ctrl-c", "esc"):
                return Action.quit(False)
            return Action.redraw()
        action = self.overlay.on_key(key)
        if action.kind == "pop":
            self._handle(self._kind, action.value)
            return Action.redraw()
        if action.kind == "quit":
            return Action.quit(False)
        if self._kind == "theme":
            name = getattr(self.overlay, "preview_name", None)
            if name and self._app_ref:
                self._app_ref.set_theme(get_theme(name))
        return Action.redraw()

    def _handle(self, kind: str, value) -> None:
        if value is None and kind != "done":
            if kind == "intro":
                self.done = True
                self.ok = False
                return
            # Back
            if kind == "provider":
                self.done = True
                self.ok = False
                return
            if kind == "endpoint":
                self._open_provider()
                return
            if kind == "key":
                if self._needs_url():
                    self._open_endpoint()
                else:
                    self._open_provider()
                return
            if kind in ("model", "model-manual", "fetch", "fetch-fail"):
                if self.model_only:
                    self.done = True
                    self.ok = False
                    return
                self._open_key()
                return
            if kind == "theme":
                if self.theme_only:
                    self.done = True
                    self.ok = False
                    return
                self._fetch_models(self.provider_id or cfg.get("provider", "openrouter"))
                return
            return
        if kind == "intro":
            self._open_provider()
            return
        if kind == "provider":
            self.provider_id = value
            if self._needs_url():
                self._open_endpoint()
            else:
                self._open_key()
            return
        if kind == "endpoint":
            url = str(value).strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                self._open_endpoint()
                return
            cfg.set_value(f"endpoints.{self.provider_id}", url)
            self._open_key()
            return
        if kind == "key":
            raw = "" if value is None else str(value)
            cleaned = cfg.clean_api_key(raw)
            if not cleaned:
                self._open_key()
                return
            try:
                cfg.set_api_key(
                    self.provider_id or cfg.get("provider", "openrouter"),
                    cleaned,
                )
            except ValueError:
                self._open_key()
                return
            self._fetch_models(self.provider_id or cfg.get("provider"))
            return
        if kind == "fetch-fail":
            if value == "retry":
                self._fetch_models(self.provider_id or cfg.get("provider"))
                return
            if value == "manual":
                self._open_model([])
                return
            self._open_key()
            return
        if kind in ("model", "model-manual"):
            self.model = str(value).strip()
            if self.model_only:
                cfg.set_value("model", self.model)
                self.ok = True
                self.done = True
                return
            self._open_theme()
            return
        if kind == "theme":
            self.theme_name = str(value)
            if self.theme_only:
                cfg.set_value("theme", self.theme_name)
                self.ok = True
                self.done = True
                return
            cfg.set_value("provider", self.provider_id)
            cfg.set_value("model", self.model)
            cfg.set_value("theme", self.theme_name)
            recents = [self.model] if self.model else []
            cfg.set_value("recent_models", recents)
            self._open_done()
            return
        if kind == "done":
            self.ok = True
            self.done = True

    def _needs_url(self) -> bool:
        pid = self.provider_id or ""
        info = provider_info_registry().get(pid)
        return bool(info and info.requires_base_url)

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        if self.overlay is not None:
            return self.overlay.render(width, height, theme, glyphs)
        return chrome_frame(
            [Line.plain("OMGA", "primary", bold=True)],
            width, height, glyphs, title=heading(),
        )


class _BusyScreen(BaseScreen):
    tick_interval = 0.08

    def __init__(self, title: str, message: str) -> None:
        self.title = title
        self.message = message
        self.i = 0

    def tick(self) -> None:
        self.i += 1

    def on_key(self, key: Key) -> Action:
        if key.name in ("esc", "ctrl-c"):
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        spin = glyphs.spinner[self.i % len(glyphs.spinner)]
        body = [Line.mixed((f"{spin} ", "accent"), (self.message, "fg"))]
        return chrome_frame(body, width, height, glyphs, title=self.title,
                            hints="Esc Cancel")


class _FetchFailedScreen(BaseScreen):
    def __init__(self, error: str) -> None:
        self.error = error

    def on_key(self, key: Key) -> Action:
        if key.is_char and key.char.lower() == "r":
            return Action.pop("retry")
        if key.is_char and key.char.lower() == "m":
            return Action.pop("manual")
        if key.name in ("esc", "ctrl-c"):
            return Action.pop(None)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body = [
            Line.mixed((f"{glyphs.error} ", "error"), ("Unable to fetch models", "error")),
            blank(),
            Line.plain(self.error[: width - 2], "muted"),
            blank(),
            Line.plain("[R] Retry   [M] Enter model manually   Esc Back", "muted"),
        ]
        return chrome_frame(body, width, height, glyphs,
                            title=f"{heading()} · Models")


class _DoneScreen(BaseScreen):
    def __init__(self, provider: str, model: str, theme_name: str) -> None:
        self.provider = provider
        self.model = model
        self.theme_name = theme_name

    def on_key(self, key: Key) -> Action:
        if key.name in ("enter", "esc"):
            return Action.pop(True)
        return Action.redraw()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        body: list[Line] = []
        if height >= 20:
            for i, row in enumerate(ASCII_LOGO):
                token = "primary" if i < 2 else "accent"
                body.append(Line.plain(row, token, bold=(i == 0)))
            body.append(blank())
        body.extend([
            Line.mixed((f"{glyphs.success} ", "success"), ("Provider configured", "fg")),
            Line.mixed((f"{glyphs.success} ", "success"), ("API key stored", "fg")),
            Line.mixed((f"{glyphs.success} ", "success"), (f"Model  {self.model}", "fg")),
            Line.mixed((f"{glyphs.success} ", "success"), (f"Theme  {self.theme_name}", "fg")),
            blank(),
            Line.plain("You're ready to code.", "fg"),
            blank(),
            Line.plain("Press Enter to start.", "accent"),
        ])
        return chrome_frame(body, width, height, glyphs,
                            title=f"{heading()} · Setup complete")


class Wizard:
    def __init__(self, console=None, theme: Theme | None = None) -> None:
        self.theme = theme or get_theme("ink")
        self.console = console

    def run(self, *, model_only: bool = False, theme_only: bool = False) -> bool:
        if not is_interactive():
            raise WizardInterrupted(
                "Setup requires an interactive terminal.",
                hint="Run `omga init` from a TTY.",
            )
        root = WizardApp(
            model_only=model_only,
            theme_only=theme_only,
            theme=self.theme,
            show_intro=not (model_only or theme_only),
        )
        app = App(theme=self.theme)
        root._app_ref = app
        result = app.run(root)
        return bool(result)
