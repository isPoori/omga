"""Main coding session — a single stateful screen with exclusive overlays.

The transcript, prompt, status bar and overlays share one renderer.
Keyboard events go to the overlay if present, otherwise to the editor.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from agent.core import Agent, AgentCancelled
from agent.hooks import Hooks
from core.branding import (
    ASSISTANT_MARK,
    MEMORY_MARK,
    SESSION_MARK,
    SKILL_MARK,
    SYSTEM_MARK,
    TAGLINE,
    USER_MARK,
    heading,
    header_title,
    logo_for_width,
)
from config import store as cfg
from config.store import is_workspace_trusted, trust_workspace
from core.errors import (
    ModelNotFoundError,
    OmgaError,
    ProviderAuthError,
    ProviderBlockedError,
    WizardInterrupted,
)
from providers.errors import is_plausible_model_id
from providers.http import invalidate_http_cache, resolve_proxy
from core.modes import MODES, get_mode
from core.models import Message
from core.paths import history_file
from core.shortcuts import action_for
from ui.glyphs import Glyphs
from ui.kernel import Action, App, BaseScreen, Frame, Line, Span, blank
from ui.keys import Key
from ui.markdown import render_markdown
from ui.measure import display_width, format_count, format_duration, truncate, wrap
from ui.screens import (
    ApprovalScreen,
    ConfirmScreen,
    DiffScreen,
    HelpScreen,
    InputScreen,
    MessageScreen,
    PaletteScreen,
    SelectorScreen,
    SettingsScreen,
    ThemePreviewScreen,
    TrustScreen,
)
from ui.theme import Theme, get_theme
from ui.widgets import Editor, Option, status_line_text
from core.usage import Metrics, Usage, parse_usage
from core.version import __version__ as OMGA_VERSION
from cli.autocomplete import slash_query, suggest_commands
from cli.commands import SlashCommand

_MAX_TRANSCRIPT = 200
_MAX_ITEM_CHARS = 8000
_CUSTOM_MODEL = "__custom_model__"
_REFRESH_MODELS = "__refresh_models__"


@dataclass
class Item:
    kind: str  # user | assistant | tool | system | error | diff | notify
    text: str
    extra: dict = field(default_factory=dict)
    collapsed: bool = False


class SessionScreen(BaseScreen):
    name = "main_session"

    def __init__(self, provider, project, *, theme: Theme, safe: bool = False) -> None:
        from memory.store import MemoryStore
        from skills.loader import load_skills
        from tools.registry import ToolRegistry

        self.provider = provider
        self.project = project
        self.theme = theme
        self.safe = safe or bool(cfg.get("safe_mode", False))
        self.store = MemoryStore() if cfg.get("agent.enable_memory", True) else None
        self.skills = load_skills(project.root) if cfg.get("agent.enable_skills", True) else None
        self.session_id: str | None = None
        if self.store is not None and cfg.get("agent.persist_sessions", True):
            model = ""
            try:
                model = provider.resolve_model() if hasattr(provider, "resolve_model") else ""
            except Exception:
                model = str(cfg.get("model") or "")
            rec = self.store.create_session(
                cwd=str(project.root),
                model=model,
                provider=getattr(provider, "id", "") or "",
                title="session",
            )
            self.session_id = rec.id
        self.registry = ToolRegistry(
            project.root,
            store=self.store,
            skills=self.skills,
            make_child=self._spawn_subagent if cfg.get("agent.enable_delegate", True) else None,
            enable_delegate=bool(cfg.get("agent.enable_delegate", True)),
        )
        self.history: list[Message] = []
        self.transcript: list[Item] = []
        self.editor = Editor(history=_load_prompt_history())
        self.metrics = Metrics(started=time.time())
        self.mode = get_mode(cfg.get("mode", "agent"))
        self.op = "Idle"
        self.op_started = time.time()
        self.work_seconds = 0.0
        self._slice_start: float | None = None
        self.last_plan: str = ""
        self.spin_i = 0
        self.overlay: BaseScreen | None = None
        self._overlay_kind = ""
        self._events: queue.Queue = queue.Queue()
        self._agent_thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._approval_event = threading.Event()
        self._approval_result = False
        self._busy = False
        self._notify: str | None = None
        self._notify_until = 0.0
        self._app_ref: App | None = None
        self.quit = False
        self._pending_overlay_result: Any = None
        self._chat_offset = 0
        self._agent: Agent | None = None
        self._body_len = 0
        self._slash_hits: list[SlashCommand] = []
        self._slash_index = 0
        if not is_workspace_trusted(str(project.root)):
            self._open(TrustScreen(str(project.root)), "trust")
        # Repair accidental junk model ids (e.g. a single keystroke saved as model)
        self._sanitize_model_config()

    @property
    def tick_interval(self) -> float:
        if self._busy:
            return 0.05
        if self.overlay is not None:
            return 0.1
        return 0.4

    # ── Overlay plumbing ──────────────────────────────────────────────────────

    def _open(self, screen: BaseScreen, kind: str) -> None:
        self.overlay = screen
        self._overlay_kind = kind
        self._pending_overlay_result = Ellipsis

    def on_child_result(self, value: Any) -> None:
        self._pending_overlay_result = value
        kind = self._overlay_kind
        self.overlay = None
        self._overlay_kind = ""
        self._handle_overlay_result(kind, value)

    def poll(self) -> Action | None:
        self._drain_events()
        if self.quit:
            return Action.quit(0)
        if self.overlay is not None and hasattr(self.overlay, "poll"):
            child = self.overlay.poll()
            if child is not None and child.kind == "pop":
                self.on_child_result(child.value)
                return Action.redraw()
        return None

    def tick(self) -> None:
        self.spin_i += 1
        if self.overlay is not None and hasattr(self.overlay, "tick"):
            self.overlay.tick()
        if self.overlay is not None and self._overlay_kind == "theme":
            name = getattr(self.overlay, "preview_name", None)
            if name and self._app_ref:
                self._app_ref.set_theme(get_theme(name))
        if self._notify and time.time() > self._notify_until:
            self._notify = None

    def notify(self, text: str, seconds: float = 2.5) -> None:
        self._notify = text
        self._notify_until = time.time() + seconds

    def _end_work(self) -> None:
        if self._slice_start is not None:
            self.work_seconds += max(0.0, time.time() - self._slice_start)
            self._slice_start = None

    def _work_now(self) -> float:
        extra = (time.time() - self._slice_start) if self._slice_start else 0.0
        return self.work_seconds + extra

    # ── Keys ──────────────────────────────────────────────────────────────────

    def on_key(self, key: Key) -> Action:
        if self.overlay is not None:
            action = self.overlay.on_key(key)
            if action.kind == "pop":
                self.on_child_result(action.value)
                return Action.redraw()
            if action.kind == "quit":
                return action
            if self._overlay_kind == "theme":
                name = getattr(self.overlay, "preview_name", None)
                if name and self._app_ref:
                    self._app_ref.set_theme(get_theme(name))
            return Action.redraw()

        if key.name == "mouse":
            return Action.redraw()

        if self._busy:
            if key.name in ("ctrl-c", "esc"):
                self._stop_agent()
                return Action.redraw()
            if self._handle_scroll(key):
                return Action.redraw()
            return Action.redraw()

        # Slash autocomplete navigation (before chat scroll / editor)
        if self._slash_hits and key.name in ("tab", "up", "down"):
            if key.name == "tab":
                self._accept_slash_suggestion()
                return Action.redraw()
            if key.name == "up":
                self._slash_index = (self._slash_index - 1) % len(self._slash_hits)
                return Action.redraw()
            if key.name == "down":
                self._slash_index = (self._slash_index + 1) % len(self._slash_hits)
                return Action.redraw()

        if self._handle_scroll(key):
            return Action.redraw()

        chord = action_for(key, when="session")
        if key.name == "ctrl-d" and not self.editor.text:
            return Action.quit(0)
        if key.name == "ctrl-c" and not self.editor.text:
            self._open(
                ConfirmScreen("Exit", "Exit OMGA?", default=False),
                "exit-confirm",
            )
            return Action.redraw()
        if chord == "help" and not self.editor.text:
            self._open(HelpScreen("session"), "help")
            return Action.redraw()
        if chord == "palette":
            self._open(PaletteScreen(), "palette")
            return Action.redraw()
        if chord == "model":
            return self._start_model_picker()
        if chord == "provider":
            return self._start_provider_picker()
        if chord == "theme":
            self._open(ThemePreviewScreen(cfg.get("theme", "ink")), "theme")
            return Action.redraw()
        if chord == "clear":
            self.transcript.clear()
            self.history.clear()
            self._agent = None
            self._chat_offset = 0
            self.notify("Session cleared")
            return Action.redraw()
        if chord == "copy":
            self._copy_last_reply()
            return Action.redraw()

        result = self.editor.handle(key)
        self._refresh_slash_suggestions()
        if result == "submit":
            text = self.editor.text.strip()
            if not text:
                return Action.redraw()
            # If slash suggestions are open and query is incomplete, accept first
            if self._slash_hits and text.startswith("/") and " " not in text[1:]:
                exact = any(text[1:].lower() == h.name for h in self._slash_hits)
                if not exact:
                    self._accept_slash_suggestion()
                    text = self.editor.text.strip()
            if text.startswith("/"):
                self.editor.commit_history()
                _save_prompt_history(self.editor.history)
                self.editor.clear()
                self._slash_hits = []
                return self._slash(text)
            self.editor.commit_history()
            _save_prompt_history(self.editor.history)
            prompt = text
            self.editor.clear()
            self._slash_hits = []
            self._submit(prompt)
            return Action.redraw()
        if result == "cancel":
            self._open(
                ConfirmScreen("Exit", "Exit OMGA?", default=False),
                "exit-confirm",
            )
            return Action.redraw()
        return Action.redraw()

    def _refresh_slash_suggestions(self) -> None:
        q = slash_query(self.editor.text)
        if q is None:
            self._slash_hits = []
            self._slash_index = 0
            return
        hits = suggest_commands(q)
        self._slash_hits = hits
        if hits:
            self._slash_index = min(self._slash_index, len(hits) - 1)
        else:
            self._slash_index = 0

    def _accept_slash_suggestion(self) -> None:
        if not self._slash_hits:
            return
        cmd = self._slash_hits[self._slash_index]
        self.editor.set_text("/" + cmd.name + " ")
        self._slash_hits = []
        self._slash_index = 0

    def _handle_overlay_result(self, kind: str, value: Any) -> None:
        if kind == "trust":
            if value:
                trust_workspace(str(self.project.root))
                self.notify("Workspace trusted")
            else:
                self.quit = True
            return
        if kind == "exit-confirm":
            if value:
                self.quit = True
            return
        if kind == "palette" and value:
            self._slash("/" + str(value))
            return
        if kind == "theme":
            if value:
                cfg.set_value("theme", value)
                self.theme = get_theme(value)
                if self._app_ref:
                    self._app_ref.set_theme(self.theme)
                self.notify(f"Theme · {value}")
            else:
                if self._app_ref:
                    self._app_ref.set_theme(self.theme)
            return
        if kind == "model":
            if value is None:
                return
            mid = str(value).strip()
            if mid == _CUSTOM_MODEL:
                self._start_custom_model_editor()
                return
            if mid == _REFRESH_MODELS:
                self._refresh_model_cache(notify=True)
                self._start_model_picker()
                return
            self._apply_model(mid)
            return
        if kind == "model-custom":
            if value is None:
                return
            self._apply_model(str(value).strip())
            return
        if kind == "provider" and value:
            cfg.set_value("provider", value)
            info = None
            try:
                from providers import provider_info_registry
                info = provider_info_registry().get(value)
            except Exception:
                info = None
            if info and info.requires_base_url and not cfg.get(f"endpoints.{value}"):
                self._pending_provider = value
                self._open(
                    InputScreen(
                        f"{heading()} · Endpoint",
                        f"Base URL for {info.name}",
                        subtitle=info.default_base_url,
                    ),
                    "endpoint",
                )
                return
            try:
                from providers import create_provider
                self.provider = create_provider(value)
                self._agent = None
                # Drop model ids that belong to another gateway (e.g. openrouter/auto on Groq)
                self._ensure_model_for_provider()
                self.notify(
                    f"Provider · {self.provider.name}  ·  model {cfg.get('model')}"
                )
            except OmgaError as exc:
                self.transcript.append(Item("error", exc.message))
            return
        if kind == "endpoint" and value:
            pid = getattr(self, "_pending_provider", None) or cfg.get("provider")
            url = str(value).strip().rstrip("/")
            if url.startswith("http"):
                cfg.set_value(f"endpoints.{pid}", url)
                cfg.set_value("provider", pid)
                from providers import create_provider
                try:
                    self.provider = create_provider(pid)
                    self.notify(f"Provider · {self.provider.name}")
                except OmgaError as exc:
                    self.transcript.append(Item("error", exc.message))
            return
        if kind == "mode" and value:
            cfg.set_value("mode", value)
            self.mode = get_mode(value)
            if self._agent is not None:
                self._agent.mode = value
            self.notify(f"Mode · {self.mode.name}")
            return
        if kind == "settings" and value:
            self._open_settings_category(value)
            return
        if kind == "api-key":
            if value is None:
                return
            pid = getattr(self, "_key_provider", None) or cfg.get("provider", "openrouter")
            try:
                cfg.set_api_key(str(pid), str(value))
                masked = cfg.clean_api_key(str(value))
                tip = (masked[:4] + "…" + masked[-4:]) if len(masked) > 8 else "(saved)"
                self.notify(f"API key saved · {pid} · {tip}")
                try:
                    from providers import create_provider
                    self.provider = create_provider(str(pid))
                    self._agent = None
                except OmgaError as exc:
                    self.transcript.append(Item("error", exc.message))
            except ValueError as exc:
                self.notify(str(exc))
                self._start_key_editor(str(pid))
            return
        if kind == "auth-retry":
            if value:
                self._start_key_editor()
            return
        if kind == "model-retry":
            if value:
                self._start_model_picker()
            return
        if kind == "model-fix":
            if value in (None, "dismiss"):
                return
            if value == "picker":
                self._start_model_picker()
                return
            if value == _CUSTOM_MODEL:
                self._start_custom_model_editor()
                return
            self._apply_model(str(value))
            return
        if kind == "blocked-fix":
            if value == "proxy":
                self._start_proxy_editor()
            elif value == "proxy-test":
                self._proxy_test()
            elif value == "provider":
                self._start_provider_picker()
            return
        if kind == "proxy":
            if value is not None:
                self._apply_proxy(str(value))
            return
        if kind == "approval":
            if value == "review":
                self._open(DiffScreen(self._pending_files, "Review changes"), "diff")
                return
            self._approval_result = value == "apply"
            self._approval_event.set()
            return
        if kind == "diff":
            if value == "apply":
                self._approval_result = True
            elif value == "reject":
                self._approval_result = False
            else:
                # closed — go back to approval
                self._open(
                    ApprovalScreen("Review changes?", self._pending_files),
                    "approval",
                )
                return
            self._approval_event.set()
            return
        if kind == "help":
            return
        if kind == "status" or kind == "usage" or kind == "message":
            return

    def _open_settings_category(self, category: str) -> None:
        if category == "theme":
            self._open(ThemePreviewScreen(cfg.get("theme", "ink")), "theme")
            return
        if category == "model":
            self._start_model_picker()
            return
        if category == "provider":
            self._start_provider_picker()
            return
        if category in ("credentials", "api-key", "key"):
            self._start_key_editor()
            return
        lines = _settings_info(category)
        self._open(MessageScreen(f"Settings · {category}", lines), "message")

    def _sanitize_model_config(self) -> None:
        mid = str(cfg.get("model") or "").strip()
        if mid and is_plausible_model_id(mid) and self._model_ok_for_provider(mid):
            return
        self._ensure_model_for_provider()

    def _model_fits_provider(self, mid: str) -> bool:
        """Heuristic filter (used when the live catalog is unavailable)."""
        pid = (getattr(self.provider, "id", "") or cfg.get("provider", "") or "").lower()
        mid_l = mid.lower()
        if mid_l.startswith("openrouter/") and pid not in ("openrouter", "omnirouter", "9router"):
            return False
        # Groq (and others) now ship org/model ids like openai/gpt-oss-120b
        if pid == "groq":
            return True
        if pid in ("openrouter", "omnirouter", "9router", "openai", "together", "fireworks"):
            return True
        return True

    def _listed_model_ids(self, *, refresh: bool = False) -> list[str]:
        from core import cache
        from core.models import Model

        models: list[Model] = []
        if not refresh:
            cached = cache.get_cached_models(getattr(self.provider, "id", "") or "")
            if cached:
                models = cached
        if not models:
            try:
                models = self.provider.list_models()
                cache.store_models(getattr(self.provider, "id", "") or "", models)
            except Exception:
                return []
        return [m.id for m in models if getattr(m, "id", None)]

    def _model_ok_for_provider(self, mid: str) -> bool:
        if not is_plausible_model_id(mid) or not self._model_fits_provider(mid):
            return False
        ids = self._listed_model_ids()
        if not ids:
            return True  # can't verify — allow configured id
        return mid in ids

    def _ensure_model_for_provider(self) -> None:
        from providers.catalog import preferred_default, resolve_retired

        mid = str(cfg.get("model") or "").strip()
        pid = getattr(self.provider, "id", "") or ""
        retired = resolve_retired(mid, pid)
        if retired:
            mid = retired
            cfg.set_value("model", mid)
            self.notify(f"Model retired · switched to {mid}")

        if mid and self._model_ok_for_provider(mid):
            return

        ids = self._listed_model_ids(refresh=True)
        fallback = preferred_default(pid, ids)
        if fallback and ids and fallback not in ids:
            fallback = ids[0]
        elif not fallback:
            fallback = ids[0] if ids else preferred_default(pid)

        if mid and mid != fallback:
            self.notify(f"Model {mid!r} unavailable · switched to {fallback}")
        cfg.set_value("model", fallback)
        _remember_model(fallback)

    def _apply_model(self, mid: str) -> None:
        mid = (mid or "").strip()
        if not is_plausible_model_id(mid):
            self.notify(f"Invalid model id · {mid!r} — try /model")
            return
        if not self._model_fits_provider(mid):
            self.notify(f"Model {mid!r} does not fit {getattr(self.provider, 'name', 'provider')}")
            return
        ids = self._listed_model_ids()
        if ids and mid not in ids:
            # Allow paste of unlisted ids (new models / aliases) but warn
            tips = ", ".join(ids[:3])
            self.notify(f"Not in catalog — saved anyway. Live examples: {tips}")
        cfg.set_value("model", mid)
        _remember_model(mid)
        self._agent = None
        self.notify(f"Model · {mid}")

    def _refresh_model_cache(self, *, notify: bool = False) -> list[str]:
        from core import cache

        pid = getattr(self.provider, "id", "") or ""
        try:
            cache.invalidate(pid)
        except Exception:
            pass
        ids = self._listed_model_ids(refresh=True)
        if notify:
            self.notify(
                f"Models refreshed · {len(ids)} available"
                if ids
                else "Model list empty / unreachable"
            )
        return ids

    def _start_custom_model_editor(self) -> None:
        current = str(cfg.get("model") or "")
        self._open(
            InputScreen(
                f"{heading()} · Custom model",
                "Type or paste a model id",
                subtitle=f"Current: {current or '(none)'}  ·  e.g. openai/gpt-oss-120b",
                allow_empty=False,
                single_line=True,
            ),
            "model-custom",
        )

    def _copy_last_reply(self) -> None:
        from ui.clipboard import copy_text

        text = ""
        for item in reversed(self.transcript):
            if item.kind == "assistant" and (item.text or "").strip():
                text = item.text
                break
        if not text.strip():
            self.notify("Nothing to copy")
            return
        ok, method = copy_text(text)
        if ok:
            self.notify(f"Copied · {method} ({len(text)} chars)")
        else:
            self.notify("Copy failed — select text with the mouse instead")

    def _apply_proxy(self, raw: str) -> None:
        from providers.http import DIRECT, normalize_proxy_url, proxy_status_label
        from providers.transport import probe_openrouter

        text = (raw or "").strip()
        try:
            norm = normalize_proxy_url(text if text else None)
        except ValueError as exc:
            self.notify(str(exc))
            return
        # None → clear config (use env); DIRECT → force direct; else URL
        if norm is None:
            cfg.set_value("network.https_proxy", None)
        elif norm == DIRECT:
            cfg.set_value("network.https_proxy", DIRECT)
        else:
            cfg.set_value("network.https_proxy", norm)
        invalidate_http_cache()
        self.notify(f"Proxy · {proxy_status_label()}")

    def _proxy_test(self) -> None:
        from providers.http import proxy_status_label, probe_openrouter

        self.notify("Testing OpenRouter reachability…")
        result = probe_openrouter()
        lines = [
            f"Proxy: {proxy_status_label()}",
            f"curl available: {result.get('curl_available')}",
        ]
        if "curl_status" in result:
            lines.append(f"curl → HTTP {result['curl_status']}  {(result.get('curl_body') or '')[:80]}")
        if result.get("curl_error"):
            lines.append(f"curl error: {result['curl_error']}")
        if "requests_status" in result:
            lines.append(
                f"python → HTTP {result['requests_status']}  "
                f"{(result.get('requests_body') or '')[:80]}"
            )
        if result.get("requests_error"):
            lines.append(f"python error: {result['requests_error']}")
        curl_ok = result.get("curl_status") in (200, 401)  # 401 = reached API
        py_ok = result.get("requests_status") in (200, 401)
        if curl_ok:
            lines.append("OK — curl path can reach OpenRouter (OMGA uses this for OpenRouter).")
        elif py_ok:
            lines.append("Python path works; curl path failed — check curl / proxy.")
        else:
            lines.append(
                "Both paths blocked. Fix VPN exit IP, try socks5://127.0.0.1:PORT, "
                "or switch /provider."
            )
        self._open(MessageScreen("Proxy / OpenRouter test", lines), "message")

    def _start_proxy_editor(self) -> None:
        from providers.http import proxy_status_label

        self._open(
            InputScreen(
                f"{heading()} · HTTPS proxy",
                "Proxy (7890 · host:port · http://… · socks5://…)",
                subtitle=(
                    f"Now: {proxy_status_label()}  ·  "
                    "off=disable  ·  clear=env  ·  7890=port"
                ),
                allow_empty=True,
                single_line=True,
            ),
            "proxy",
        )

    def _start_key_editor(self, provider: str | None = None) -> None:
        pid = (provider or cfg.get("provider", "openrouter") or "openrouter").lower()
        existing = cfg.get_api_key(pid)
        masked = (
            (existing[:4] + "…" + existing[-4:]) if existing and len(existing) > 8 else "(not set)"
        )
        self._key_provider = pid
        self._open(
            InputScreen(
                f"{heading()} · API key",
                f"Paste API key for {pid}",
                secret=True,
                subtitle=f"Current: {masked}  ·  raw key only, no Bearer/quotes",
            ),
            "api-key",
        )

    def _start_model_picker(self) -> Action:
        opts = _model_options(self.provider)
        # Always offer type/paste + refresh, even when the catalog is empty
        extras = [
            Option(
                "⌨  Type or paste a model id…",
                _CUSTOM_MODEL,
                group="Custom",
                searchable="custom type paste enter model id",
                meta="Enter any provider model id",
            ),
            Option(
                "↻  Refresh live model list",
                _REFRESH_MODELS,
                group="Custom",
                searchable="refresh reload fetch models",
                meta="Re-query the provider /models API",
            ),
        ]
        opts = extras + opts
        current = str(cfg.get("model") or "")
        self._open(
            SelectorScreen(
                f"{heading()} · Model",
                opts,
                subtitle=f"Current · {current or 'none'}  ·  type to search  ·  paste via Custom",
                allow_search=True,
                details=_model_details,
                hints="↑↓ Select   / search   Enter   Esc",
            ),
            "model",
        )
        return Action.redraw()

    def _start_provider_picker(self) -> Action:
        from providers import provider_info_registry

        registry = provider_info_registry()
        opts = [Option(info.name, info.id, searchable=info.name)
                for info in registry.values()]
        self._open(
            SelectorScreen(f"{heading()} · Provider", opts, allow_search=False),
            "provider",
        )
        return Action.redraw()

    def _slash(self, text: str) -> Action:
        from cli.commands import resolve

        raw, _, rest = text[1:].partition(" ")
        raw = raw.lower().strip()
        resolved = resolve(raw)
        cmd = resolved.name if resolved else raw

        if cmd in ("exit", "quit"):
            return Action.quit(0)
        if cmd == "help":
            self._open(HelpScreen("session"), "help")
        elif cmd == "model":
            if rest.strip():
                self._apply_model(rest.strip())
            else:
                return self._start_model_picker()
        elif cmd in ("copy", "yank"):
            self._copy_last_reply()
        elif cmd in ("proxy", "https-proxy"):
            arg = rest.strip()
            if not arg:
                self._start_proxy_editor()
            elif arg.lower() in ("test", "check", "probe", "status"):
                self._proxy_test()
            else:
                self._apply_proxy(arg)
        elif cmd == "provider":
            return self._start_provider_picker()
        elif cmd == "theme":
            name = rest.strip() or cfg.get("theme", "ink")
            self._open(ThemePreviewScreen(name), "theme")
        elif cmd == "settings":
            self._open(SettingsScreen(), "settings")
        elif cmd in ("key", "apikey", "api-key"):
            target = rest.strip() or None
            self._start_key_editor(target)
        elif cmd == "clear":
            self.transcript.clear()
            self.history.clear()
            self._agent = None
            self._chat_offset = 0
            if self.store is not None and cfg.get("agent.persist_sessions", True):
                model = str(cfg.get("model") or "")
                rec = self.store.create_session(
                    cwd=str(self.project.root),
                    model=model,
                    provider=getattr(self.provider, "id", "") or "",
                    title="session",
                )
                self.session_id = rec.id
            self.notify("Session cleared")
        elif cmd in ("stop", "cancel"):
            if self._busy:
                self._stop_agent()
            else:
                self.notify("Nothing is running")
        elif cmd == "usage":
            self._open(
                MessageScreen("Session usage", self.metrics.summary_lines(self._work_now())),
                "usage",
            )
        elif cmd == "status":
            self._open(MessageScreen("OMGA Status", self._status_lines()), "status")
        elif cmd == "memory":
            self._open(MessageScreen("Memory", self._memory_lines(rest.strip())), "message")
        elif cmd == "skills":
            self._open(MessageScreen("Skills", self._skills_lines(rest.strip())), "message")
        elif cmd in ("sessions", "history"):
            self._open(MessageScreen("Sessions", self._sessions_lines()), "message")
        elif cmd == "compress":
            from agent.compress import compress_history, estimate_chars

            before = estimate_chars(self.history)
            self.history = compress_history(self.history)
            if self._agent is not None:
                self._agent.history = list(self.history)
            after = estimate_chars(self.history)
            self.notify(f"Compressed · {before} → {after} chars")
        elif cmd in MODES or cmd in ("thinking", "code"):
            key = "think" if cmd == "thinking" else ("agent" if cmd == "code" else cmd)
            if key in MODES:
                cfg.set_value("mode", key)
                self.mode = get_mode(key)
                if self._agent is not None:
                    self._agent.mode = key
                self.notify(f"Mode · {self.mode.name}")
        elif cmd == "execute":
            if not self.last_plan.strip():
                self.notify("No plan to execute. Use /plan first.")
            else:
                self.mode = get_mode("agent")
                cfg.set_value("mode", "agent")
                self._submit(
                    "Execute this plan. Follow it step by step.\n\n" + self.last_plan
                )
        elif cmd == "mode":
            opts = [
                Option(m.name, m.id, hint=m.description,
                       searchable=f"{m.id} {m.name} {m.description}")
                for m in MODES.values()
            ]
            self._open(SelectorScreen(f"{heading()} · Mode", opts, allow_search=True), "mode")
        elif cmd == "review":
            self._submit("Review the current git changes. Report High/Medium/Low issues.")
        else:
            self.notify(f"Unknown /{raw}  ·  try /help")
        return Action.redraw()

    def _status_lines(self) -> list[str]:
        model = self.provider.resolve_model() if hasattr(self.provider, "resolve_model") else cfg.get("model")
        tools = self.registry.names()
        return [
            f"Provider       {self.provider.name}",
            f"Model          {model}",
            f"Mode           {self.mode.name}",
            f"Directory      {self.project.root}",
            f"Session        {(self.session_id or '—')[:12]}",
            f"Skills         {len(self.skills.skills) if self.skills else 0}",
            "",
            self.metrics.context_label(),
            f"Work time      {format_duration(self._work_now())}",
            "",
            f"Tools ({len(tools)})",
            "  " + ", ".join(tools[:14]) + ("…" if len(tools) > 14 else ""),
        ]

    def _memory_lines(self, query: str = "") -> list[str]:
        if self.store is None:
            return ["Memory is disabled."]
        hits = self.store.search_memories(query, limit=15, cwd=str(self.project.root))
        if not hits:
            return ["No memories yet. The agent can call remember() to save facts."]
        lines = []
        for h in hits:
            lines.append(f"[{h.get('kind', 'note')}] {h.get('content', '')[:120]}")
            lines.append(f"  id {h.get('id', '')}")
        return lines

    def _skills_lines(self, query: str = "") -> list[str]:
        if self.skills is None:
            return ["Skills are disabled."]
        items = self.skills.search(query) if query else self.skills.skills
        if not items:
            return ["No skills found."]
        return [f"{s.name}  ·  {s.description[:80]}  ({s.source})" for s in items]

    def _sessions_lines(self) -> list[str]:
        if self.store is None:
            return ["Session persistence is disabled."]
        rows = self.store.list_sessions(cwd=str(self.project.root), limit=12)
        if not rows:
            return ["No saved sessions for this project."]
        out = []
        for r in rows:
            mark = "●" if r.id == self.session_id else " "
            title = r.title or "session"
            out.append(
                f"{mark} {r.id[:10]}  {title[:40]}  ·  {r.message_count} msgs"
            )
        return out


    # ── Agent ─────────────────────────────────────────────────────────────────

    def _stop_agent(self) -> None:
        from tools import procs

        self._cancel.set()
        self._approval_result = False
        self._approval_event.set()
        procs.kill_all()
        self.op = "Stopping"
        self.notify("Stopping…")

    def _handle_scroll(self, key: Key) -> bool:
        empty = not self.editor.text.strip()
        if key.name == "wheel-up":
            self._nudge_scroll(3)
            return True
        if key.name == "wheel-down":
            self._nudge_scroll(-3)
            return True
        if key.name == "page-up":
            self._nudge_scroll(8)
            return True
        if key.name == "page-down":
            self._nudge_scroll(-8)
            return True
        if key.name == "up" and (self._busy or self._chat_offset > 0 or empty):
            if self._busy or self._chat_offset > 0 or self._body_len > 4:
                self._nudge_scroll(1)
                return True
        if key.name == "down" and (self._busy or self._chat_offset > 0):
            self._nudge_scroll(-1)
            return True
        return False

    def _nudge_scroll(self, delta: int) -> None:
        max_off = max(0, self._body_len)
        self._chat_offset = max(0, min(max_off, self._chat_offset + delta))

    def _submit(self, prompt: str) -> None:
        self.transcript.append(Item("user", prompt))
        self._chat_offset = 0
        self._busy = True
        self._cancel.clear()
        self.op = "Thinking"
        self.op_started = time.time()
        self._slice_start = time.time()
        self.metrics.requests += 1
        thread = threading.Thread(target=self._run_agent, args=(prompt,), daemon=True)
        self._agent_thread = thread
        thread.start()

    def _get_agent(self, hooks: Hooks) -> Agent:
        if self._agent is None:
            self._agent = Agent(
                self.provider,
                self.registry,
                hooks=hooks,
                max_iterations=int(cfg.get("agent.max_iterations", 60) or 60),
                temperature=_float(cfg.get("system.temperature")),
                max_tokens=_int(cfg.get("system.max_tokens")),
                mode=self.mode.id,
                safe=self.safe,
                store=self.store,
                session_id=self.session_id,
                skills=self.skills,
                project=self.project,
            )
            for msg in self.history:
                self._agent.history.append(
                    Message(
                        role=msg.role,
                        content=msg.content,
                        name=msg.name,
                        tool_call_id=msg.tool_call_id,
                        tool_calls=msg.tool_calls,
                    )
                )
        else:
            self._agent.hooks = hooks
            self._agent.mode = self.mode.id
            self._agent.safe = self.safe
            self._agent.provider = self.provider
            self._agent.session_id = self.session_id
        return self._agent

    def _spawn_subagent(self, prompt: str) -> str:
        """Run an isolated child agent (no nested delegation)."""
        from tools.registry import ToolRegistry

        child_registry = ToolRegistry(
            self.project.root,
            store=self.store,
            skills=self.skills,
            make_child=None,
            enable_delegate=False,
        )
        child = Agent(
            self.provider,
            child_registry,
            hooks=Hooks(should_cancel=lambda: self._cancel.is_set()),
            max_iterations=int(cfg.get("agent.subagent_max_iterations", 25) or 25),
            temperature=_float(cfg.get("system.temperature")),
            max_tokens=_int(cfg.get("system.max_tokens")),
            mode=self.mode.id,
            safe=self.safe,
            store=None,
            session_id=None,
            skills=self.skills,
            project=self.project,
            is_subagent=True,
        )
        return child.run(prompt)

    def _run_agent(self, prompt: str) -> None:
        try:
            hooks = Hooks(
                on_stream=lambda t: self._events.put(("stream", t)),
                on_tool_start=lambda n, a: self._events.put(("tool_start", n, a)),
                on_tool_result=lambda n, r: self._events.put(("tool_result", n, r)),
                on_approval=self._on_approval,
                on_final=lambda t: self._events.put(("final", t)),
                on_usage=lambda u: self._events.put(("usage", u)),
                should_cancel=lambda: self._cancel.is_set(),
            )
            agent = self._get_agent(hooks)
            final = agent.run(prompt)
            self.history = _prune_history(list(agent.history))
            agent.history = list(self.history)
            self._events.put(("done", final))
        except AgentCancelled:
            if self._agent is not None:
                self.history = _prune_history(list(self._agent.history))
            self._events.put(("cancelled", None))
        except ProviderAuthError as exc:
            self._events.put(("auth_error", exc.message, exc.hint))
        except ProviderBlockedError as exc:
            self._events.put(("blocked", exc.message, exc.hint))
        except ModelNotFoundError as exc:
            self._events.put(("model_error", exc.message, exc.hint))
        except OmgaError as exc:
            self._events.put(("error", exc.message, exc.hint))
        except Exception as exc:  # pragma: no cover
            self._events.put(("error", str(exc), ""))

    def _on_approval(self, description: str, files: list[dict]) -> bool:
        self._pending_files = files
        self._approval_event.clear()
        self._events.put(("approval", description, files))
        self._approval_event.wait()
        return self._approval_result

    def _drain_events(self) -> None:
        stream_acc = None
        while True:
            try:
                evt = self._events.get_nowait()
            except queue.Empty:
                break
            kind = evt[0]
            if kind == "stream":
                from core.security import looks_like_prompt_leak, scrub_output
                text = evt[1]
                last = self.transcript[-1] if self.transcript else None
                if last and last.kind == "assistant" and last.extra.get("streaming"):
                    last.text += text
                    if len(last.text) > _MAX_ITEM_CHARS:
                        last.text = last.text[-_MAX_ITEM_CHARS:]
                else:
                    self.transcript.append(Item("assistant", text, extra={"streaming": True}))
                last = self.transcript[-1] if self.transcript else None
                if last and last.kind == "assistant" and looks_like_prompt_leak(last.text):
                    last.text = scrub_output(last.text)
                self.op = "Thinking"
            elif kind == "tool_start":
                name, args = evt[1], evt[2]
                self.metrics.tool_calls += 1
                self.op = _op_for_tool(name)
                self.transcript.append(Item(
                    "tool",
                    _tool_label(name, args or {}, running=True),
                    extra={"running": True, "name": name, "args": args or {}},
                ))
            elif kind == "tool_result":
                name, result = evt[1], evt[2]
                last = next((i for i in reversed(self.transcript)
                             if i.kind == "tool" and i.extra.get("running")), None)
                args = {}
                if last:
                    args = last.extra.get("args") or {}
                    last.extra["running"] = False
                    last.extra["result"] = result
                    last.text = _tool_label(name, args, running=False, result=result)
                if name == "read_file":
                    self.metrics.files_read += 1
                if name in ("write_file", "delete_file"):
                    self.metrics.files_modified += 1
                if name == "run_command":
                    self.metrics.commands_executed += 1
            elif kind == "final":
                from core.security import scrub_output
                text = scrub_output(evt[1] or "")
                last = self.transcript[-1] if self.transcript else None
                if last and last.kind == "assistant":
                    last.text = text or last.text
                    last.extra["streaming"] = False
                elif text:
                    self.transcript.append(Item("assistant", text))
                if self.mode.id == "plan" and (text or (last and last.text)):
                    self.last_plan = text or (last.text if last else "")
            elif kind == "done":
                self._busy = False
                self.op = "Completed"
                self._end_work()
            elif kind == "cancelled":
                self._busy = False
                self.op = "Cancelled"
                self._end_work()
                self.transcript.append(Item("system", "Cancelled."))
            elif kind == "error":
                self._busy = False
                self.op = "Failed"
                self._end_work()
                msg, hint = evt[1], evt[2] if len(evt) > 2 else ""
                self.transcript.append(Item("error", msg + (f"\n{hint}" if hint else "")))
            elif kind == "auth_error":
                self._busy = False
                self.op = "Auth"
                self._end_work()
                msg, hint = evt[1], evt[2] if len(evt) > 2 else ""
                self.transcript.append(Item("error", msg + (f"\n{hint}" if hint else "")))
                self._open(
                    ConfirmScreen(
                        "API key rejected",
                        "Credentials look wrong — update the API key now?",
                        default=True,
                    ),
                    "auth-retry",
                )
            elif kind == "model_error":
                self._busy = False
                self.op = "Model"
                self._end_work()
                msg, hint = evt[1], evt[2] if len(evt) > 2 else ""
                # Auto-suggest live replacements
                suggestions = self._listed_model_ids(refresh=True)[:8]
                tip = ""
                if suggestions:
                    tip = "\nSuggested: " + " · ".join(suggestions[:5])
                    # Auto-switch to first live model so the next message works
                    try:
                        if hasattr(self.provider, "_default_model"):
                            preferred = str(self.provider._default_model() or "")
                        else:
                            preferred = ""
                    except Exception:
                        preferred = ""
                    pick = preferred if preferred in suggestions else suggestions[0]
                    cfg.set_value("model", pick)
                    _remember_model(pick)
                    tip += f"\nSwitched to · {pick}  (change with /model)"
                self.transcript.append(
                    Item("error", msg + (f"\n{hint}" if hint else "") + tip)
                )
                opts = [
                    Option("⌨  Type / paste another model…", _CUSTOM_MODEL,
                           searchable="custom paste"),
                    Option("Browse all models", "picker", searchable="list browse"),
                ]
                for mid in suggestions[:6]:
                    opts.append(Option(mid, mid, group="Suggested", searchable=mid, meta=mid))
                opts.append(Option("Dismiss", "dismiss"))
                self._open(
                    SelectorScreen(
                        f"{heading()} · Model unavailable",
                        opts,
                        allow_search=True,
                        hints="↑↓ Select   Enter   Esc",
                    ),
                    "model-fix",
                )
            elif kind == "blocked":
                self._busy = False
                self.op = "Blocked"
                self._end_work()
                msg, hint = evt[1], evt[2] if len(evt) > 2 else ""
                self.transcript.append(Item("error", msg + (f"\n{hint}" if hint else "")))
                self._open(
                    SelectorScreen(
                        f"{heading()} · Network blocked",
                        [
                            Option("Set proxy (/proxy 7890)", "proxy",
                                   searchable="proxy vpn waf clash"),
                            Option("Test reachability (/proxy test)", "proxy-test",
                                   searchable="test probe curl"),
                            Option("Switch provider", "provider",
                                   searchable="provider groq openai ollama"),
                            Option("Dismiss", "dismiss"),
                        ],
                        allow_search=False,
                        hints="↑↓ Select   Enter   Esc",
                    ),
                    "blocked-fix",
                )
            elif kind == "approval":
                self.op = "WaitingForApproval"
                _, description, files = evt
                self._pending_files = files
                self._open(ApprovalScreen(description, files), "approval")
            elif kind == "usage":
                parsed = parse_usage(evt[1])
                self.metrics.usage.add(parsed)
                if parsed.total_tokens:
                    self.metrics.context_used = parsed.total_tokens
        if len(self.transcript) > _MAX_TRANSCRIPT:
            self.transcript = self.transcript[-_MAX_TRANSCRIPT:]

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        if self.overlay is not None:
            # Exclusive overlay — prompt does not receive keys and is not shown.
            return self.overlay.render(width, height, theme, glyphs)

        model = cfg.get("model") or (
            self.provider.resolve_model() if hasattr(self.provider, "resolve_model") else ""
        )
        wd = _short_path(str(self.project.root))
        header_sub = (
            f"{wd}  {glyphs.sep}  {model}  {glyphs.sep}  "
            f"{self.provider.name}  {glyphs.sep}  {self.mode.name}"
        )

        body: list[Line] = []
        if not self.transcript:
            body.extend(_empty_chat_lines(width, glyphs, self.provider, key_ok=bool(
                cfg.get_api_key(getattr(self.provider, "id", "") or None)
            )))
        prev_kind = ""
        for item in self.transcript:
            rows = _render_item(item, width, glyphs, self.spin_i)
            if not rows:
                continue
            if body and not (item.kind == "tool" and prev_kind == "tool"):
                body.append(blank())
            body.extend(rows)
            prev_kind = item.kind
        self._body_len = len(body)

        elapsed = (time.time() - self._slice_start) if self._busy and self._slice_start else 0
        op_line = _op_label(self.op, elapsed, glyphs, self.spin_i, self._busy)
        ctx = self.metrics.context_label()
        tokens = format_count(self.metrics.usage.total_tokens)
        work = format_duration(self._work_now()) if (self._busy or self.work_seconds) else "—"
        git = ""
        if getattr(self.project, "branch", None) and self.project.branch != "?":
            git = self.project.branch

        # ── Input box (cursor tracked precisely) ──────────────────────────────
        # Layout of the active line:  "│ ❯ <text…>"
        # Use ASCII-safe prompt glyph width via display_width.
        left_prefix = f"{glyphs.vline} {glyphs.prompt} "
        prefix_cols = display_width(left_prefix)
        field_cols = max(8, width - prefix_cols - 1)  # leave 1 col margin
        n_editor = max(1, len(self.editor.lines))
        # Cap multiline editor height so chat still has room.
        max_editor_rows = min(n_editor, max(1, height // 4))
        start_row = max(0, n_editor - max_editor_rows)

        prompt_block: list[Line] = [
            Line.plain(
                glyphs.corner_tl + glyphs.hline * max(0, width - 2) + glyphs.corner_tr,
                "border",
            ),
        ]
        cursor_row_in_block = 1  # first content line after top border
        cursor_col = prefix_cols
        for ri in range(start_row, n_editor):
            if ri == self.editor.row:
                visible, cur_in = self.editor.visible_segment(field_cols)
                prompt_block.append(Line.mixed(
                    (glyphs.vline + " ", "border"),
                    (glyphs.prompt + " ", "accent"),
                    Span(visible, "fg"),
                ))
                cursor_row_in_block = len(prompt_block) - 1
                cursor_col = prefix_cols + cur_in
            else:
                # Non-active lines: show start of line, no hscroll tracking.
                other = truncate(self.editor.lines[ri], field_cols)
                # Align continuation under the text (skip prompt glyph width).
                pad_left = " " * display_width(glyphs.prompt + " ")
                prompt_block.append(Line.mixed(
                    (glyphs.vline + " ", "border"),
                    (pad_left, "border"),
                    Span(other, "muted"),
                ))
        prompt_block.append(Line.plain(
            glyphs.corner_bl + glyphs.hline * max(0, width - 2) + glyphs.corner_br,
            "border",
        ))

        # Slash autocomplete panel (above the input box)
        suggest_block: list[Line] = []
        if self._slash_hits and not self._busy:
            suggest_block.append(Line.plain(
                f"  {glyphs.spark} commands  ·  Tab accept  ·  ↑↓",
                "muted",
            ))
            for i, hit in enumerate(self._slash_hits[:6]):
                mark = glyphs.selected if i == self._slash_index else " "
                token = "accent" if i == self._slash_index else "fg"
                label = f"/{hit.name}"
                hint = truncate(hit.summary, max(8, width - len(label) - 8))
                suggest_block.append(Line.mixed(
                    (f"  {mark} ", "accent" if i == self._slash_index else "muted"),
                    Span(f"{label:<14}", token, bold=(i == self._slash_index)),
                    Span(hint, "muted"),
                ))
            suggest_block.append(blank())

        if self._notify:
            prompt_block.append(Line.mixed(
                (f" {glyphs.success} ", "success"),
                (truncate(self._notify, width - 4), "success"),
            ))

        status = status_line_text(
            [op_line, ctx, f"{tokens} tok", work, git],
            width, glyphs,
        )
        if self._busy:
            hints = f"{glyphs.warning} Esc stop   ·   ↑↓ scroll   ·   drag to copy"
        else:
            hints = (
                f"Enter send  {glyphs.sep}  drag to copy  {glyphs.sep}  "
                f"Ctrl+Y yank  {glyphs.sep}  /help"
            )

        # Header (4) + blank + body + suggestions + prompt + hints + status
        header_h = 4
        reserved = (
            header_h + 1 + len(suggest_block) + len(prompt_block) + 1 + 1
        )
        budget = max(3, height - reserved)
        if len(body) > budget:
            max_off = len(body) - budget
            self._chat_offset = min(self._chat_offset, max_off)
            end = len(body) - self._chat_offset
            start = max(0, end - budget)
            clipped = body[start:end]
            if self._chat_offset > 0 and clipped:
                clipped[0] = Line.plain(
                    truncate(f"↑ {self._chat_offset} earlier · PgDn to follow", width),
                    "muted",
                )
            body = clipped
        else:
            self._chat_offset = 0

        top = glyphs.corner_tl + glyphs.hline * max(0, width - 2) + glyphs.corner_tr
        mid = glyphs.corner_bl + glyphs.hline * max(0, width - 2) + glyphs.corner_br
        key_set = bool(cfg.get_api_key(getattr(self.provider, "id", "") or None))
        key_badge = f"{glyphs.success} key" if key_set else f"{glyphs.warning} no key"
        lines: list[Line] = [
            Line.plain(top, "border"),
            Line.mixed(
                (glyphs.vline + " ", "border"),
                Span(header_title(OMGA_VERSION), "primary", bold=True),
                ("  ", "fg"),
                Span(key_badge, "success" if key_set else "warning"),
            ),
            Line.mixed(
                (glyphs.vline + " ", "border"),
                Span(truncate(header_sub, max(8, width - 4)), "muted"),
            ),
            Line.plain(mid, "border"),
            blank(),
        ]
        lines.extend(body)
        footer_h = len(suggest_block) + len(prompt_block) + 2
        while len(lines) + footer_h < height:
            lines.append(blank())
        lines.extend(suggest_block)
        input_start = len(lines)
        lines.extend(prompt_block)
        lines.append(Line.plain(truncate(hints, width), "muted"))
        lines.append(status)

        if len(lines) > height:
            overflow = len(lines) - height
            body_start = header_h + 1
            body_end = input_start - len(suggest_block)
            trim = min(overflow, max(0, body_end - body_start))
            if trim:
                lines = lines[:body_start] + lines[body_start + trim:]
                input_start -= trim
            lines = lines[:height]

        cursor_row = min(height - 1, input_start + cursor_row_in_block)
        cursor_col = max(0, min(width - 1, cursor_col))
        return Frame(lines[:height], cursor=(cursor_row, cursor_col))


def run_session(provider, project, *, theme: Theme, safe: bool = False) -> int:
    from ui.kernel import is_interactive

    screen = SessionScreen(provider, project, theme=theme, safe=safe)
    if not is_interactive():
        raise WizardInterrupted("OMGA needs an interactive terminal.", hint="")
    app = App(theme=theme)
    screen._app_ref = app
    result = app.run(screen)
    return int(result or 0)


def _empty_chat_lines(width: int, glyphs: Glyphs, provider, *, key_ok: bool) -> list[Line]:
    """ASCII-branded empty state — one composed welcome panel."""
    inner = max(28, min(width - 4, 64))
    top = f"  {glyphs.corner_tl}{glyphs.hline * (inner - 2)}{glyphs.corner_tr}"
    bot = f"  {glyphs.corner_bl}{glyphs.hline * (inner - 2)}{glyphs.corner_br}"

    def row(text: str, token: str = "muted") -> Line:
        content = truncate(text, inner - 4)
        pad = max(0, inner - 4 - display_width(content))
        return Line.mixed(
            (f"  {glyphs.vline} ", "border"),
            Span(content + (" " * pad), token),
            (f" {glyphs.vline}", "border"),
        )

    def blank_row() -> Line:
        return Line.mixed(
            (f"  {glyphs.vline}", "border"),
            Span(" " * (inner - 2), "fg"),
            (glyphs.vline, "border"),
        )

    lines: list[Line] = [blank(), Line.plain(top, "border")]
    logo = logo_for_width(inner - 4)
    for logo_row in logo:
        lines.append(row(logo_row.rstrip(), "primary"))
    lines.append(blank_row())
    lines.append(row(f"{SESSION_MARK}  {TAGLINE}", "accent"))
    lines.append(blank_row())

    key_label = "key ready" if key_ok else "set key · /key"
    key_token = "success" if key_ok else "warning"
    provider_name = getattr(provider, "name", "?") or "?"
    model = str(cfg.get("model") or "—")

    for icon, text, token in (
        (glyphs.spark, "Type a message  ·  / for commands", "muted"),
        (glyphs.spark, "/model  ·  pick or paste   /proxy off", "muted"),
        (MEMORY_MARK, "Grows with you  ·  /memory  /skills", "muted"),
        (glyphs.success if key_ok else glyphs.warning,
         f"{provider_name}  ·  {key_label}", key_token),
        (SYSTEM_MARK, f"model  {model}", "muted"),
    ):
        lines.append(row(f"{icon}  {text}", token))

    lines.append(Line.plain(bot, "border"))
    lines.append(blank())
    return lines


def _render_item(item: Item, width: int, glyphs: Glyphs, spin_i: int = 0) -> list[Line]:
    if item.kind == "user":
        lines = [Line.mixed(
            (f"{USER_MARK} ", "user"),
            Span("You", "user", bold=True),
        )]
        for w in wrap(item.text, max(8, width - 2)):
            lines.append(Line.plain("  " + w, "fg"))
        return lines
    if item.kind == "assistant":
        if not (item.text or "").strip():
            return []
        lines = [Line.mixed(
            (f"{ASSISTANT_MARK} ", "assistant"),
            Span("OMGA", "assistant", bold=True),
        )]
        for md_line in render_markdown(item.text, max(8, width - 2)):
            # Indent markdown under the mark
            if md_line.spans:
                lines.append(Line.mixed(("  ", "fg"), *md_line.spans))
            else:
                lines.append(blank())
        return lines
    if item.kind == "tool":
        name = item.extra.get("name") or ""
        running = bool(item.extra.get("running"))
        if running:
            prefix = glyphs.spinner[spin_i % len(glyphs.spinner)]
            status_token = "accent"
        else:
            prefix = glyphs.success
            status_token = "success"
        icon, icon_token = _tool_icon(name, glyphs)
        label = truncate(item.text, max(8, width - 10))
        return [Line.mixed(
            Span(f"{prefix} ", status_token),
            Span(f"{icon} ", icon_token),
            Span(label, "muted" if running else "fg"),
        )]
    if item.kind == "error":
        lines = [Line.mixed(
            (f"{glyphs.error} ", "error"),
            (item.text.split("\n")[0], "error"),
        )]
        for extra in item.text.split("\n")[1:]:
            lines.append(Line.plain("  " + extra, "muted"))
        return lines
    if item.kind == "diff":
        out = []
        for row in item.text.split("\n"):
            if row.startswith("@@"):
                token = "info"
            elif row.startswith("+"):
                token = "added"
            elif row.startswith("-"):
                token = "removed"
            else:
                token = "muted"
            out.append(Line.plain(truncate(row, width), token))
        return out
    if item.kind == "system":
        return [Line.mixed(
            (f"{SYSTEM_MARK} ", "muted"),
            Span(truncate(item.text, width - 4), "muted"),
        )]
    return [Line.plain(item.text, "muted")]


def _op_label(op: str, elapsed: float, glyphs: Glyphs, spin_i: int, busy: bool) -> str:
    if busy:
        spin = glyphs.spinner[spin_i % len(glyphs.spinner)]
        return f"{spin} {op} · {format_duration(elapsed)}"
    if op == "Completed":
        return f"{glyphs.success} Completed"
    if op == "Failed":
        return f"{glyphs.error} Failed"
    if op == "Cancelled":
        return f"{glyphs.warning} Cancelled"
    return "Idle"


def _tool_icon(name: str, glyphs: Glyphs) -> tuple[str, str]:
    if name in ("read_file", "list_files"):
        return glyphs.file, "info"
    if name in ("write_file", "edit_file", "delete_file"):
        return glyphs.edit, "warning"
    if name in ("search", "grep", "recall", "search_sessions", "web_search", "browse_page"):
        return glyphs.search, "accent"
    if name == "run_command":
        return glyphs.shell, "tool"
    if name in ("git_status", "git_diff", "git_log"):
        return glyphs.file, "success"
    if name in ("remember", "load_skill", "create_skill", "delegate_task"):
        return glyphs.bullet, "accent"
    return glyphs.bullet, "tool"


def _op_for_tool(name: str) -> str:
    return {
        "read_file": "Reading",
        "write_file": "Editing",
        "edit_file": "Editing",
        "delete_file": "Editing",
        "search": "Searching",
        "web_search": "Searching",
        "browse_page": "Reading",
        "run_command": "RunningCommand",
        "git_status": "Reading",
        "git_diff": "Reading",
        "remember": "Remembering",
        "recall": "Recalling",
        "load_skill": "LoadingSkill",
        "delegate_task": "Delegating",
        "poll_process": "Polling",
    }.get(name, "Working")


def _tool_label(name: str, args: dict, *, running: bool, result: Any = None) -> str:
    args = args or {}
    data = result if isinstance(result, dict) else {}
    path = str(args.get("path") or data.get("path") or "")
    if name == "run_command":
        cmd = str(args.get("command") or data.get("command") or "").strip()
        cmd = truncate(cmd, 72)
        if running:
            return f"$ {cmd}"
        if data.get("background") or data.get("status") == "running":
            pid = data.get("pid", "")
            return f"$ {cmd}  ·  running pid {pid}"
        if data.get("cancelled"):
            return f"$ {cmd}  ·  stopped"
        code = data.get("exit_code")
        elapsed = data.get("elapsed_seconds")
        extra = f"exit {code}" if code is not None else "done"
        if elapsed is not None:
            extra += f" · {elapsed}s"
        return f"$ {cmd}  ·  {extra}"
    if name == "read_file":
        n = data.get("total_lines")
        suffix = f"  ·  {n} lines" if n and not running else ""
        return f"{'Reading' if running else 'Read'} {path or 'file'}{suffix}"
    if name == "write_file":
        return f"{'Writing' if running else 'Wrote'} {path or 'file'}"
    if name == "edit_file":
        n = data.get("replacements")
        extra = f"  ·  {n} edits" if n and not running else ""
        return f"{'Editing' if running else 'Edited'} {path or 'file'}{extra}"
    if name == "delete_file":
        return f"{'Deleting' if running else 'Deleted'} {path or 'file'}"
    if name == "remember":
        return "Remember" if running else f"Remembered {data.get('id', '')}"
    if name == "recall":
        return "Recall" if running else f"Recall · {data.get('count', 0)} hits"
    if name == "load_skill":
        return f"Skill {args.get('name') or data.get('name') or ''}"
    if name == "delegate_task":
        return "Subagent" if running else "Subagent done"
    if name == "list_files":
        loc = path or "."
        if running:
            return f"List {loc}"
        n = data.get("count")
        if n is None:
            n = len(data.get("entries") or [])
        extra = f"  ·  {n} entries"
        if data.get("truncated"):
            extra += " (truncated)"
        skipped = data.get("skipped") or []
        if skipped:
            extra += f"  ·  skipped {', '.join(skipped[:3])}"
        return f"List {loc}{extra}"
    if name == "web_search":
        q = str(args.get("query") or data.get("query") or "")
        eng = str(data.get("engine") or args.get("engine") or "web")
        n = data.get("count")
        shown = f'"{truncate(q, 48)}"' if q else "web"
        if running:
            return f"Web search {shown}"
        extra = f"  ·  {n} hits" if n is not None else ""
        return f"Web search {shown}  ·  {eng}{extra}"
    if name == "browse_page":
        url = str(args.get("url") or data.get("url") or "")
        title = str(data.get("title") or "")
        shown = truncate(title or url, 56) or "page"
        return f"{'Browsing' if running else 'Browsed'} {shown}"
    if name in ("search", "grep"):
        pat = str(args.get("pattern") or args.get("query") or data.get("pattern") or "")
        scope = str(args.get("path") or "")
        shown = f'"{truncate(pat, 40)}"' if pat else "code"
        if scope and scope not in (".", ""):
            shown += f" in {scope}"
        if running:
            return f"Search {shown}"
        hits = data.get("count")
        if hits is None:
            hits = len(data.get("results") or data.get("matches") or data.get("hits") or [])
        return f"Search {shown}  ·  {hits} hits"
    if name == "git_status":
        return "Git status" if not running else "Checking git status"
    if name == "git_diff":
        return "Git diff" if not running else "Reading git diff"
    pretty = name.replace("_", " ")
    return f"{pretty} {path}".strip()


def _prune_history(messages: list[Message], keep: int = 48) -> list[Message]:
    systems = [m for m in messages if m.role == "system"][:3]
    rest = [m for m in messages if m.role != "system"]
    if len(rest) > keep:
        rest = rest[-keep:]
    return systems + rest


def _model_options(provider) -> list[Option]:
    from core import cache
    from core.models import Model
    from providers.catalog import free_ids_for, is_free_id

    models: list[Model] = []
    cached = cache.get_cached_models(provider.id)
    if cached:
        models = cached
    else:
        try:
            models = provider.list_models()
            cache.store_models(provider.id, models)
        except Exception:
            models = []
    recents = list(cfg.get("recent_models") or [])
    favs = set(cfg.get("favorite_models") or [])
    opts: list[Option] = []
    seen: set[str] = set()
    by_id = {m.id: m for m in models}
    live_ids = set(by_id)
    pid = getattr(provider, "id", "") or ""

    def add(mid: str, group: str, *, label: str | None = None, meta: str = "") -> None:
        if mid in seen:
            return
        seen.add(mid)
        m = by_id.get(mid)
        star = "* " if mid in favs else ""
        if m is not None:
            meta_parts = []
            if m.context_window:
                meta_parts.append(f"{format_count(m.context_window)} ctx")
            if m.capabilities:
                meta_parts.append(" · ".join(m.capabilities[:2]))
            opts.append(Option(
                f"{star}{m.display}",
                mid,
                hint=mid,
                searchable=f"{mid} {m.display} {m.name} free {group}",
                meta=" · ".join(meta_parts) if meta_parts else mid,
                group=group,
            ))
        else:
            opts.append(Option(
                f"{star}{label or mid}",
                mid,
                hint=mid,
                searchable=f"{mid} free {group}",
                meta=meta or mid,
                group=group,
            ))

    # Free / recommended first (curated + live :free)
    for hid in free_ids_for(pid):
        if live_ids and hid not in live_ids:
            continue
        add(hid, "✦ Free / recommended")
    for m in models:
        if is_free_id(m.id):
            add(m.id, "✦ Free / recommended")
    # If catalog empty, still surface curated free hints for search/paste UX
    if not live_ids:
        for hid in free_ids_for(pid):
            add(hid, "✦ Free / recommended")

    for rid in recents:
        if not is_plausible_model_id(str(rid)):
            continue
        if rid in by_id:
            add(str(rid), "Recent")
        elif not live_ids:
            add(str(rid), "Recent")

    for m in models:
        vendor = m.vendor_name or "All models"
        add(m.id, vendor)
    return opts


def _model_details(opt: Option) -> list[Line]:
    return [
        Line.plain(opt.label, "primary", bold=True),
        Line.plain(f"ID         {opt.value}", "muted"),
        Line.plain(f"{opt.group + ' · ' if opt.group else ''}{opt.meta or ''}", "muted"),
    ]


def _remember_model(model_id: str) -> None:
    if not is_plausible_model_id(model_id):
        return
    recents = [
        m for m in (cfg.get("recent_models") or [])
        if m != model_id and is_plausible_model_id(str(m))
    ]
    recents.insert(0, model_id)
    cfg.set_value("recent_models", recents[:20])


def _settings_info(category: str) -> list[str]:
    mapping = {
        "general": [
            f"Default mode        {cfg.get('mode', 'agent')}",
            f"Confirm destructive {cfg.get('system.confirm_destructive', True)}",
            f"Prompt history      {cfg.get('interface.prompt_history', True)}",
            f"Animations          {cfg.get('interface.animations', True)}",
        ],
        "interface": [
            f"Theme               {cfg.get('theme', 'dark')}",
            f"Compact             {cfg.get('interface.compact', False)}",
            f"Status bar          {cfg.get('interface.status_bar', True)}",
            f"Unicode             {cfg.get('interface.unicode', 'auto')}",
        ],
        "agent": [
            f"Max iterations      {cfg.get('agent.max_iterations', 60)}",
            f"Command timeout     {cfg.get('agent.command_timeout', 120)}",
            f"Auto approve        {cfg.get('agent.auto_approve', False)}",
            f"Memory              {cfg.get('agent.enable_memory', True)}",
            f"Skills              {cfg.get('agent.enable_skills', True)}",
            f"Subagents           {cfg.get('agent.enable_delegate', True)}",
            f"Persist sessions    {cfg.get('agent.persist_sessions', True)}",
        ],
        "security": [
            f"Confirm commands    {cfg.get('system.confirm_destructive', True)}",
            f"Safe mode           {cfg.get('safe_mode', False)}",
            "Secret redaction    on",
        ],
        "terminal": [
            f"Unicode             {cfg.get('interface.unicode', 'auto')}",
            f"Animations          {cfg.get('interface.animations', True)}",
            "Alternate screen    on",
        ],
        "performance": [
            "Streaming           on",
            "Model cache TTL     1h",
        ],
        "advanced": [
            f"Temperature         {cfg.get('system.temperature', 0.7)}",
            f"Max tokens          {cfg.get('system.max_tokens', 8192)}",
        ],
        "tools": [
            "Files, edit_file, search, shell, git,",
            "web_search, browse_page (HTTP; Chrome opt-in),",
            "memory, skills, poll_process, delegate_task.",
        ],
        "git": ["Git status is shown in the session footer. OMGA never auto-commits."],
    }
    return mapping.get(category, [f"No extra settings for {category}."])


def _load_prompt_history() -> list[str]:
    try:
        text = history_file().read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if ln][-500:]
    except OSError:
        return []


def _save_prompt_history(items: list[str]) -> None:
    try:
        path = history_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(items[-500:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _short_path(path: str) -> str:
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None

