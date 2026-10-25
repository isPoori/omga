"""State-driven TUI kernel.

Interactive screens never print incrementally. Every keystroke updates
application state; the renderer paints a complete frame in the alternate
screen buffer. Only the top screen receives keyboard events.

Architecture:
    Key  →  Screen.on_key  →  state  →  Screen.render  →  Frame  →  Terminal.paint
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from core.paths import is_windows
from ui.ansi import paint as ansi_paint, style_close
from ui.glyphs import Glyphs, sanitize
from ui.keys import Key, KeyReader, RESIZE
from ui.measure import display_width, pad, truncate
from ui.theme import Theme, get_theme

# ── Frame model ────────────────────────────────────────────────────────────────


@dataclass
class Span:
    text: str
    token: str = "fg"
    bold: bool = False
    dim: bool = False
    inverse: bool = False


@dataclass
class Line:
    spans: list[Span] = field(default_factory=list)

    @classmethod
    def plain(cls, text: str, token: str = "fg", **kw: Any) -> "Line":
        return cls([Span(sanitize(text), token, **kw)])

    @classmethod
    def mixed(cls, *parts: tuple[str, str] | Span) -> "Line":
        spans: list[Span] = []
        for part in parts:
            if isinstance(part, Span):
                spans.append(part)
            else:
                text, token = part
                spans.append(Span(sanitize(text), token))
        return cls(spans)

    def width(self) -> int:
        return sum(display_width(s.text) for s in self.spans)

    def to_plain(self) -> str:
        return "".join(s.text for s in self.spans)

    def render(self, theme: Theme, width: int) -> str:
        raw = "".join(
            ansi_paint(s.text, theme, s.token, bold=s.bold, dim=s.dim, inverse=s.inverse)
            for s in self.spans
        )
        visible = self.width()
        if visible < width:
            raw += " " * (width - visible)
        elif visible > width:
            # Rebuild truncated plain then restyle as fg — safer than clipping ANSI.
            return ansi_paint(truncate(self.to_plain(), width), theme, "fg") + (
                " " * max(0, width - min(width, display_width(truncate(self.to_plain(), width))))
            )
        return raw + style_close()


@dataclass
class Frame:
    lines: list[Line] = field(default_factory=list)
    cursor: tuple[int, int] | None = None  # (row, col) 0-based; None hides

    def to_plain(self) -> str:
        return "\n".join(line.to_plain() for line in self.lines)


def hline(width: int, glyphs: Glyphs, token: str = "border") -> Line:
    return Line.plain(glyphs.hline * max(0, width), token)


def blank() -> Line:
    return Line.plain("")


# ── Screen protocol ────────────────────────────────────────────────────────────


@dataclass
class Action:
    kind: str  # redraw | push | pop | replace | quit | nop
    screen: Any = None
    value: Any = None

    @staticmethod
    def redraw() -> "Action":
        return Action("redraw")

    @staticmethod
    def nop() -> "Action":
        return Action("nop")

    @staticmethod
    def push(screen: Any) -> "Action":
        return Action("push", screen=screen)

    @staticmethod
    def pop(value: Any = None) -> "Action":
        return Action("pop", value=value)

    @staticmethod
    def replace(screen: Any) -> "Action":
        return Action("replace", screen=screen)

    @staticmethod
    def quit(value: Any = None) -> "Action":
        return Action("quit", value=value)


class Screen(Protocol):
    tick_interval: float

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame: ...
    def on_key(self, key: Key) -> Action: ...
    def tick(self) -> None: ...
    def on_resize(self, width: int, height: int) -> None: ...


class BaseScreen:
    tick_interval: float = 0.08
    name: str = "base"

    def tick(self) -> None:
        return None

    def on_resize(self, width: int, height: int) -> None:
        return None

    def on_key(self, key: Key) -> Action:
        if key.name == "ctrl-c":
            return Action.quit()
        return Action.nop()

    def render(self, width: int, height: int, theme: Theme, glyphs: Glyphs) -> Frame:
        return Frame([Line.plain("OMGA")])


# ── Terminal backend ───────────────────────────────────────────────────────────


class Backend(Protocol):
    def enter(self) -> None: ...
    def leave(self) -> None: ...
    def size(self) -> tuple[int, int]: ...
    def paint(self, frame: Frame, theme: Theme) -> None: ...
    def read_key(self, timeout: float | None) -> Key | None: ...
    def debug(self, message: str) -> None: ...


_RESTORE: list[Callable[[], None]] = []
_RESTORED = False


def _restore_all() -> None:
    global _RESTORED
    if _RESTORED:
        return
    _RESTORED = True
    for fn in reversed(_RESTORE):
        try:
            fn()
        except Exception:
            pass


def _install_crash_hooks() -> None:
    atexit.register(_restore_all)
    previous = sys.excepthook

    def _hook(exc_type, exc, tb):  # pragma: no cover
        _restore_all()
        previous(exc_type, exc, tb)

    sys.excepthook = _hook


class TerminalBackend:
    """Raw-mode alternate-screen backend with full-frame painting."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._old = None
        self._entered = False
        self._reader: KeyReader | None = None
        self._resized = False
        self._debug = os.environ.get("OMGA_DEBUG_UI") == "1"
        self._debug_log: list[str] = []
        self._prev_sigwinch = None
        self._prev_rows: list[str] | None = None
        self._prev_cursor: tuple[int, int] | None = None
        self._prev_size: tuple[int, int] | None = None

    def enter(self) -> None:
        if self._entered:
            return
        _install_crash_hooks()
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            self._entered = True
            self._reader = KeyReader()
            return
        if sys.stdin.isatty() and not is_windows():
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self._reader = KeyReader(self._fd)

            def _restore_term() -> None:
                try:
                    termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
                except Exception:
                    pass
                self._write(
                    "\x1b[?1049l"  # leave alt screen
                    "\x1b[?25h"    # show cursor
                    "\x1b[0m"      # reset colours
                    "\x1b[?2004l"  # bracketed paste off
                    "\x1b[?1006l\x1b[?1000l\x1b[?1002l\x1b[?1003l"  # mouse off
                )

            _RESTORE.append(_restore_term)
        else:
            self._reader = KeyReader()

        if hasattr(signal, "SIGWINCH"):
            self._prev_sigwinch = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, self._on_winch)

        # Do NOT enable mouse reporting (1000/1006): it steals click-drag
        # so users cannot select/copy chat text. Scroll with keys / PgUp.
        # Optional: OMGA_MOUSE=1 re-enables wheel reporting for power users.
        mouse_on = os.environ.get("OMGA_MOUSE", "").strip().lower() in (
            "1", "on", "true", "yes",
        )
        mouse_seq = "\x1b[?1000h\x1b[?1006h" if mouse_on else ""
        self._write(
            "\x1b[?1049h"  # enter alt screen
            "\x1b[?25l"    # hide cursor
            "\x1b[?2004h"  # bracketed paste
            f"{mouse_seq}"
            "\x1b[2J\x1b[H"
        )
        self._entered = True

    def leave(self) -> None:
        if not self._entered:
            return
        self._entered = False
        if hasattr(signal, "SIGWINCH") and self._prev_sigwinch is not None:
            try:
                signal.signal(signal.SIGWINCH, self._prev_sigwinch)
            except Exception:
                pass
        _restore_all()
        global _RESTORED
        _RESTORED = False
        _RESTORE.clear()

    def _on_winch(self, *_args) -> None:
        self._resized = True

    def size(self) -> tuple[int, int]:
        try:
            import shutil
            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            return max(20, cols), max(8, rows)
        except Exception:
            return 80, 24

    def paint(self, frame: Frame, theme: Theme) -> None:
        width, height = self.size()
        rows: list[str] = []
        for i in range(height):
            if i < len(frame.lines):
                rows.append(frame.lines[i].render(theme, width))
            else:
                rows.append(" " * width)
        cursor = frame.cursor
        size = (width, height)
        if (
            self._prev_rows == rows
            and self._prev_cursor == cursor
            and self._prev_size == size
        ):
            return
        if (
            self._prev_rows is not None
            and self._prev_size == size
            and len(self._prev_rows) == len(rows)
        ):
            out: list[str] = []
            for i, (old, new) in enumerate(zip(self._prev_rows, rows)):
                if old != new:
                    out.append(f"\x1b[{i + 1};1H")
                    out.append(new)
                    out.append("\x1b[K")
            if cursor is not None:
                r, c = cursor
                r = max(0, min(height - 1, r))
                c = max(0, min(width - 1, c))
                out.append("\x1b[?25h")
                out.append(f"\x1b[{r + 1};{c + 1}H")
            else:
                out.append("\x1b[?25l")
            if out:
                self._write("".join(out))
        else:
            out = ["\x1b[H"]
            for i, row in enumerate(rows):
                out.append(row)
                out.append("\x1b[K")
                if i < height - 1:
                    out.append("\r\n")
            if cursor is not None:
                r, c = cursor
                r = max(0, min(height - 1, r))
                c = max(0, min(width - 1, c))
                out.append("\x1b[?25h")
                out.append(f"\x1b[{r + 1};{c + 1}H")
            else:
                out.append("\x1b[?25l")
            self._write("".join(out))
        self._prev_rows = rows
        self._prev_cursor = cursor
        self._prev_size = size
        if self._debug:
            self._debug_log.append(
                f"paint {width}x{height} lines={len(frame.lines)} cursor={frame.cursor}"
            )

    def read_key(self, timeout: float | None) -> Key | None:
        if self._resized:
            self._resized = False
            return Key(RESIZE)
        if self._reader is None:
            return None
        key = self._reader.read(timeout)
        if self._debug and key is not None:
            self._debug_log.append(f"key {key.name} {key.char!r}")
        return key

    def debug(self, message: str) -> None:
        if self._debug:
            self._debug_log.append(message)

    def _write(self, text: str) -> None:
        data = text.encode("utf-8", errors="ignore")
        try:
            buf = getattr(sys.stdout, "buffer", None)
            if buf is not None:
                buf.write(data)
                buf.flush()
            else:  # pragma: no cover
                sys.stdout.write(text)
                sys.stdout.flush()
        except Exception:
            pass


class HeadlessBackend:
    """In-memory backend for tests. Never touches the real terminal."""

    def __init__(
        self,
        keys: list[Key] | None = None,
        width: int = 80,
        height: int = 24,
    ) -> None:
        self.keys = list(keys or [])
        self.width = width
        self.height = height
        self.frames: list[str] = []
        self.entered = False

    def enter(self) -> None:
        self.entered = True

    def leave(self) -> None:
        self.entered = False

    def size(self) -> tuple[int, int]:
        return self.width, self.height

    def paint(self, frame: Frame, theme: Theme) -> None:
        self.frames.append(frame.to_plain())

    def read_key(self, timeout: float | None) -> Key | None:
        if not self.keys:
            return Key("quit-sentinel")
        return self.keys.pop(0)

    def debug(self, message: str) -> None:
        return None


# ── Application ────────────────────────────────────────────────────────────────


class App:
    def __init__(
        self,
        backend: Backend | None = None,
        theme: Theme | None = None,
        glyphs: Glyphs | None = None,
    ) -> None:
        self.backend = backend or TerminalBackend()
        self.theme = theme or get_theme("ink")
        self.glyphs = glyphs or Glyphs.detect()
        self.stack: list[Any] = []
        self.result: Any = None
        self._running = False
        self._max_frames = 50_000

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme

    def run(self, root: Any) -> Any:
        self.stack = [root]
        self._running = True
        self.backend.enter()
        try:
            idle_quits = 0
            while self._running and self.stack:
                screen = self.stack[-1]
                if hasattr(screen, "poll"):
                    polled = screen.poll()
                    if polled is not None and getattr(polled, "kind", "nop") != "nop":
                        self._apply(polled, screen)
                        continue
                width, height = self.backend.size()
                frame = screen.render(width, height, self.theme, self.glyphs)
                self.backend.paint(frame, self.theme)
                timeout = getattr(screen, "tick_interval", 0.08)
                key = self.backend.read_key(timeout)
                if key is None:
                    if hasattr(screen, "tick"):
                        screen.tick()
                    continue
                if key.name == "quit-sentinel":
                    # Headless: no more keys. Stop rather than spin forever.
                    idle_quits += 1
                    self._running = False
                    break
                if key.name == RESIZE:
                    if hasattr(screen, "on_resize"):
                        screen.on_resize(width, height)
                    continue
                action = screen.on_key(key)
                self._apply(action, screen)
            return self.result
        finally:
            self.backend.leave()
            self._running = False

    def _apply(self, action: Action, screen: Any) -> None:
        if action.kind == "nop":
            return
        if action.kind == "redraw":
            return
        if action.kind == "push" and action.screen is not None:
            self.stack.append(action.screen)
            return
        if action.kind == "replace" and action.screen is not None:
            if self.stack:
                self.stack[-1] = action.screen
            else:
                self.stack.append(action.screen)
            return
        if action.kind == "pop":
            self.stack.pop()
            if not self.stack:
                self.result = action.value
                self._running = False
            elif hasattr(self.stack[-1], "on_child_result"):
                self.stack[-1].on_child_result(action.value)
            else:
                self.result = action.value
            return
        if action.kind == "quit":
            self.result = action.value
            self._running = False
            self.stack.clear()


def is_interactive() -> bool:
    """Return True when stdin and stdout are live TTYs."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def terminal_size() -> tuple[int, int]:
    try:
        import shutil
        return shutil.get_terminal_size(fallback=(80, 24))
    except Exception:
        return 80, 24
