"""Keyboard event model and UTF-8-safe byte decoder.

Arrow keys, Ctrl chords and pasted text are decoded into a single Key
event. Multi-byte UTF-8 sequences are assembled before decoding so the
UI never sees U+FFFD replacement characters from a truncated read.

Bracketed paste (``ESC[200~`` … ``ESC[201~``) is collected into one
``Key("paste", char=…)`` so terminals never inject ESC/Enter mid-paste.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from core.paths import is_windows


@dataclass(frozen=True)
class Key:
    name: str
    char: str = ""
    ctrl: bool = False
    alt: bool = False

    @property
    def is_char(self) -> bool:
        return self.name == "char" and bool(self.char)

    def matches(self, spec: str) -> bool:
        return self.name == spec or (
            self.ctrl and spec == f"ctrl-{self.char.lower()}"
        )


# Named keys produced by the decoder.
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
ENTER = "enter"
ESC = "esc"
TAB = "tab"
BACKSPACE = "backspace"
DELETE = "delete"
HOME = "home"
END = "end"
PAGE_UP = "page-up"
PAGE_DOWN = "page-down"
CTRL_C = "ctrl-c"
CTRL_D = "ctrl-d"
CTRL_L = "ctrl-l"
CTRL_M = "ctrl-m"
CTRL_P = "ctrl-p"
CTRL_T = "ctrl-t"
CTRL_K = "ctrl-k"
CTRL_Y = "ctrl-y"
CTRL_ENTER = "ctrl-enter"
RESIZE = "resize"
PASTE = "paste"
WHEEL_UP = "wheel-up"
WHEEL_DOWN = "wheel-down"
MOUSE = "mouse"

_PASTE_START = "[200~"
_PASTE_END = "\x1b[201~"


_CSI = {
    "A": UP,
    "B": DOWN,
    "C": RIGHT,
    "D": LEFT,
    "H": HOME,
    "F": END,
    "Z": "shift-tab",
}

_CSI_TILDE = {
    "1": HOME,
    "3": DELETE,
    "4": END,
    "5": PAGE_UP,
    "6": PAGE_DOWN,
    "7": HOME,
    "8": END,
}

_CTRL_MAP = {
    "\x01": "ctrl-a",
    "\x02": "ctrl-b",
    "\x03": CTRL_C,
    "\x04": CTRL_D,
    "\x05": "ctrl-e",
    "\x06": "ctrl-f",
    "\x0b": CTRL_K,
    "\x0c": CTRL_L,
    "\x0d": ENTER,
    "\x0e": "ctrl-n",  # newline in the prompt editor
    "\x0a": ENTER,
    "\x10": CTRL_P,
    "\x14": CTRL_T,
    "\x15": "ctrl-u",
    "\x17": "ctrl-w",
    "\x19": CTRL_Y,  # Ctrl+Y yank / copy
    "\x1a": "ctrl-z",
    "\x7f": BACKSPACE,
    "\x08": BACKSPACE,
    "\t": TAB,
}


def _utf8_needed(first: int) -> int:
    if first < 0x80:
        return 1
    if first < 0xE0:
        return 2
    if first < 0xF0:
        return 3
    return 4


def read_utf8_char(fd: int) -> str:
    """Read one Unicode character from *fd*, never using ``errors='replace'``."""
    first = os.read(fd, 1)
    if not first:
        return ""
    needed = _utf8_needed(first[0])
    buf = first
    while len(buf) < needed:
        more = os.read(fd, needed - len(buf))
        if not more:
            break
        buf += more
    try:
        return buf.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def decode_sequence(lead: str, rest: str) -> Key:
    """Map an ESC sequence to a Key (not used for bracketed-paste body)."""
    if not rest:
        return Key(ESC)
    # Paste end marker alone — ignore (should be consumed inside paste reader)
    if rest == "[201~":
        return Key("paste-end")
    if rest.startswith(_PASTE_START):
        # Incomplete / bare start — paste body should be read by KeyReader
        return Key(PASTE, char="")
    mouse = _decode_mouse(rest)
    if mouse is not None:
        return mouse
    if rest.startswith("[") and rest.endswith("~"):
        inner = rest[1:-1].split(";")[0]
        name = _CSI_TILDE.get(inner)
        if name:
            return Key(name)
        if inner == "13" or rest == "[13;5u":
            return Key(CTRL_ENTER)
        # Unknown CSI ~  — ignore rather than fake Esc (avoids closing dialogs)
        return Key("unknown")
    if rest.startswith("["):
        cmd = rest[-1] if rest else ""
        if cmd in _CSI:
            mods = rest[1:-1]
            name = _CSI[cmd]
            if ";5" in mods or ";6" in mods:
                if name == ENTER or cmd == "M":
                    return Key(CTRL_ENTER)
            return Key(name)
    if rest.startswith("O") and len(rest) >= 2:
        return Key(_CSI.get(rest[1], ESC))
    return Key(ESC)


def _decode_mouse(rest: str) -> Key | None:
    """SGR (`[<64;x;yM`) and X10 (`[M...`) mouse / wheel events."""
    if rest.startswith("[<") and rest[-1:] in ("M", "m"):
        inner = rest[2:-1]
        btn = inner.split(";")[0] if inner else ""
        try:
            code = int(btn)
        except ValueError:
            return Key(MOUSE)
        if code == 64:
            return Key(WHEEL_UP)
        if code == 65:
            return Key(WHEEL_DOWN)
        return Key(MOUSE)
    if rest.startswith("[M") and len(rest) >= 5:
        cb = ord(rest[2]) - 32
        if cb == 64:
            return Key(WHEEL_UP)
        if cb == 65:
            return Key(WHEEL_DOWN)
        return Key(MOUSE)
    return None


def key_from_char(ch: str) -> Key:
    if not ch:
        return Key(ESC)
    if ch in _CTRL_MAP:
        mapped = _CTRL_MAP[ch]
        if mapped == ENTER:
            return Key(ENTER)
        if mapped.startswith("ctrl-"):
            return Key(mapped, char=chr(ord(ch) + 96) if ord(ch) < 27 else "", ctrl=True)
        return Key(mapped)
    if ch == "\x1b":
        return Key(ESC)
    if ch.isprintable():
        return Key("char", char=ch)
    return Key("unknown")


class KeyReader:
    """Blocking/non-blocking key reader over a file descriptor."""

    def __init__(self, fd: int | None = None) -> None:
        self.fd = fd if fd is not None else (sys.stdin.fileno() if sys.stdin.isatty() else None)
        self._pending: list[Key] = []

    def read(self, timeout: float | None = None) -> Key | None:
        if self._pending:
            return self._pending.pop(0)
        if self.fd is None:
            return None
        if not _ready(self.fd, timeout):
            return None
        ch = read_utf8_char(self.fd)
        if not ch:
            return None
        if ch == "\x1b":
            return self._read_escape()
        return key_from_char(ch)

    def _read_escape(self) -> Key:
        if self.fd is None:
            return Key(ESC)
        if not _ready(self.fd, 0.05):
            return Key(ESC)
        seq = read_utf8_char(self.fd)
        if not seq:
            return Key(ESC)
        # CSI / SS3: keep consuming while more bytes are immediately available.
        while _ready(self.fd, 0.0):
            nxt = read_utf8_char(self.fd)
            if not nxt:
                break
            seq += nxt
            # Bracketed paste start — swallow the whole paste block
            if seq.startswith(_PASTE_START) and seq.endswith("~"):
                return self._read_bracketed_paste()
            if seq.startswith("[<") and nxt in "Mm":
                break
            if seq.startswith("[M") and len(seq) >= 4:
                break
            if nxt.isalpha() or nxt == "~":
                break
        if seq == "[M":
            extra = ""
            for _ in range(2):
                if self.fd is not None and _ready(self.fd, 0.02):
                    extra += read_utf8_char(self.fd)
            seq += extra
        # Paste end leaked somehow — ignore
        if seq == "[201~":
            return Key("unknown")
        return decode_sequence("\x1b", seq)

    def _read_bracketed_paste(self) -> Key:
        """Read bytes until ESC[201~ and return a single paste Key."""
        if self.fd is None:
            return Key(PASTE, char="")
        buf: list[str] = []
        # Hard cap to avoid hanging on a broken terminal
        limit = 256_000
        end_tail = ""
        while len(buf) < limit:
            if not _ready(self.fd, 0.35):
                break
            ch = read_utf8_char(self.fd)
            if not ch:
                break
            if ch == "\x1b":
                # Possible paste-end or nested CSI — peek ahead
                peek = ""
                while _ready(self.fd, 0.02) and len(peek) < 8:
                    nxt = read_utf8_char(self.fd)
                    if not nxt:
                        break
                    peek += nxt
                    if peek == "[201~":
                        text = "".join(buf)
                        return Key(PASTE, char=text)
                    if peek.startswith("[201~"):
                        text = "".join(buf)
                        return Key(PASTE, char=text)
                    # Not paste-end — keep ESC+peek as literal (rare)
                    if len(peek) >= 2 and not _PASTE_END[1:].startswith(peek):
                        buf.append("\x1b" + peek)
                        peek = ""
                        break
                else:
                    if peek == "[201~" or peek.startswith("[201~"):
                        return Key(PASTE, char="".join(buf))
                    if peek:
                        buf.append("\x1b" + peek)
                continue
            buf.append(ch)
        return Key(PASTE, char="".join(buf))


def _ready(fd: int, timeout: float | None) -> bool:
    if is_windows():  # pragma: no cover
        import msvcrt
        if timeout == 0 or timeout is None:
            return msvcrt.kbhit()
        import time
        end = time.time() + (timeout or 0)
        while time.time() < end:
            if msvcrt.kbhit():
                return True
            time.sleep(0.01)
        return msvcrt.kbhit()
    import select
    if timeout is None:
        timeout = 0.0
    try:
        return bool(select.select([fd], [], [], timeout)[0])
    except (OSError, ValueError):
        return False
