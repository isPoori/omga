"""Reusable TUI widgets: viewport selector, text editor, chrome."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ui.glyphs import Glyphs
from ui.kernel import Frame, Line, Span, blank, hline
from ui.keys import Key
from ui.measure import display_width, format_count, pad, slice_display, truncate


@dataclass
class Option:
    label: str
    value: Any
    hint: str = ""
    searchable: str = ""
    meta: str = ""
    group: str = ""


class Selector:
    """Viewport-scrolling list with optional live search.

    Keeps the highlight inside the visible window. Rows are single-line by
    default (``compact=True``) so option count matches rendered height.
    """

    def __init__(
        self,
        options: Sequence[Option],
        *,
        allow_search: bool = True,
        default_index: int = 0,
        compact: bool = True,
    ) -> None:
        self.options = list(options)
        self.allow_search = allow_search
        self.compact = compact
        self.query = ""
        self.searching = False
        self.index = default_index if self.options else 0
        self.offset = 0
        self._viewport = 8
        self._filter()

    def set_viewport(self, viewport: int) -> None:
        self._viewport = max(1, int(viewport))
        self._clamp_offset()

    def _filter(self) -> None:
        q = self.query.lower().strip()
        if not q:
            self.visible = list(self.options)
        else:
            parts = q.split()
            self.visible = [
                o for o in self.options
                if all(
                    p in (o.searchable or o.label).lower()
                    or p in o.label.lower()
                    or p in (o.hint or "").lower()
                    or p in (o.meta or "").lower()
                    or p in (o.group or "").lower()
                    or p in str(o.value).lower()
                    for p in parts
                )
            ]
        if self.visible:
            self.index = min(max(0, self.index), len(self.visible) - 1)
        else:
            self.index = 0
        self.offset = 0
        self._clamp_offset()

    def _clamp_offset(self) -> None:
        if not self.visible:
            self.offset = 0
            return
        viewport = max(1, self._viewport)
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + viewport:
            self.offset = self.index - viewport + 1
        max_off = max(0, len(self.visible) - viewport)
        self.offset = max(0, min(self.offset, max_off))

    def selected(self) -> Option | None:
        if not self.visible:
            return None
        return self.visible[self.index]

    def move(self, delta: int) -> None:
        if not self.visible:
            return
        n = len(self.visible)
        self.index = max(0, min(n - 1, self.index + int(delta)))
        self.searching = False
        self._clamp_offset()

    def handle(self, key: Key) -> str | None:
        if key.name in ("esc", "ctrl-c"):
            return "cancel"
        if key.name == "enter":
            return "select" if self.visible else None
        if key.name == "up":
            self.move(-1)
            return None
        if key.name == "down":
            self.move(1)
            return None
        if key.name == "wheel-up":
            self.move(-3)
            return None
        if key.name == "wheel-down":
            self.move(3)
            return None
        if key.name == "page-up":
            self.move(-max(1, self._viewport - 1))
            return None
        if key.name == "page-down":
            self.move(max(1, self._viewport - 1))
            return None
        if key.name == "home":
            self.index = 0
            self._clamp_offset()
            return None
        if key.name == "end" and self.visible:
            self.index = len(self.visible) - 1
            self._clamp_offset()
            return None
        if not self.allow_search:
            return None
        if key.name == "backspace":
            if self.query:
                self.query = self.query[:-1]
                self.searching = bool(self.query)
                self.index = 0
                self._filter()
            return None
        if key.is_char:
            # j/k navigate when search box is empty
            if not self.query and key.char in ("j", "J"):
                self.move(1)
                return None
            if not self.query and key.char in ("k", "K"):
                self.move(-1)
                return None
            self.query += key.char
            self.searching = True
            self.index = 0
            self._filter()
            return None
        return None

    def lines(
        self,
        width: int,
        viewport: int,
        glyphs: Glyphs,
        *,
        show_search: bool = True,
    ) -> list[Line]:
        self.set_viewport(viewport)
        out: list[Line] = []
        if show_search and self.allow_search:
            if self.searching or self.query:
                label = f"Search: {self.query}▌" if self.searching else f"Search: {self.query}"
            else:
                label = "Search: (type to filter · free · gpt · llama)"
            out.append(Line.plain(truncate(label, width), "muted"))
            out.append(blank())
        if not self.visible:
            out.append(Line.plain("  No matches — clear search or choose Custom", "muted"))
            return out

        end = min(len(self.visible), self.offset + self._viewport)
        last_group = None
        for i in range(self.offset, end):
            opt = self.visible[i]
            if opt.group and opt.group != last_group:
                out.append(Line.plain(f"  {opt.group}", "accent", dim=True))
                last_group = opt.group
            marker = glyphs.selected if i == self.index else " "
            token = "primary" if i == self.index else "fg"
            label = truncate(opt.label, max(8, width - 4))
            out.append(Line.mixed(
                (f"{marker} ", "accent" if i == self.index else "muted"),
                Span(label, token, bold=(i == self.index)),
            ))
            if not self.compact and opt.meta:
                out.append(Line.plain(truncate(f"    {opt.meta}", width), "muted"))

        if len(self.visible) > self._viewport:
            out.append(blank())
            out.append(Line.plain(
                pad(f"↓↑  {self.index + 1} / {len(self.visible)}", width, "center"),
                "muted",
            ))
        return out


class Editor:
    """Multiline prompt editor with display-width-aware cursor + history."""

    def __init__(
        self,
        history: list[str] | None = None,
        *,
        single_line: bool = False,
    ) -> None:
        self.lines: list[str] = [""]
        self.row = 0
        self.col = 0  # codepoint index within the current line
        self.history = list(history or [])
        self._hist_index: int | None = None
        self._stash = ""
        self.hscroll = 0  # display-column offset for long lines
        self.single_line = single_line

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def set_text(self, text: str) -> None:
        self.lines = text.split("\n") or [""]
        self.row = len(self.lines) - 1
        self.col = len(self.lines[self.row])
        self.hscroll = 0

    def clear(self) -> None:
        self.lines = [""]
        self.row = 0
        self.col = 0
        self.hscroll = 0
        self._hist_index = None

    def current_line(self) -> str:
        return self.lines[self.row] if self.lines else ""

    def cursor_display_col(self) -> int:
        """Terminal columns from start of line to the cursor."""
        return display_width(self.current_line()[: self.col])

    def visible_segment(self, field_cols: int) -> tuple[str, int]:
        """Return (visible text, cursor col within field) for the active line.

        Horizontally scrolls so the cursor stays inside *field_cols*.
        """
        field_cols = max(4, field_cols)
        line = self.current_line()
        cursor_abs = self.cursor_display_col()
        if cursor_abs < self.hscroll:
            self.hscroll = cursor_abs
        elif cursor_abs >= self.hscroll + field_cols:
            self.hscroll = cursor_abs - field_cols + 1
        # Keep scroll in range
        total = display_width(line)
        max_scroll = max(0, total - field_cols + 1)
        self.hscroll = max(0, min(self.hscroll, max_scroll))

        # Slice by display columns
        visible = slice_display(line, self.hscroll, field_cols)
        cursor_in_field = cursor_abs - self.hscroll
        return visible, max(0, min(field_cols, cursor_in_field))

    def handle(self, key: Key) -> str | None:
        """Return 'submit' | 'cancel' | 'cleared' | None."""
        if key.name == "enter":
            return "submit"
        if key.name in ("ctrl-n", "ctrl-enter", "alt-enter", "shift-enter"):
            if self.single_line:
                return "submit"
            self._newline()
            return None
        if key.name == "ctrl-c":
            if self.text:
                self.clear()
                return "cleared"
            return "cancel"
        if key.name == "backspace":
            self._backspace()
            return None
        if key.name == "delete":
            self._delete()
            return None
        if key.name == "left":
            self._left()
            return None
        if key.name == "right":
            self._right()
            return None
        if key.name in ("home", "ctrl-a"):
            self.col = 0
            return None
        if key.name in ("end", "ctrl-e"):
            self.col = len(self.lines[self.row])
            return None
        if key.name == "up":
            if self.single_line or len(self.lines) == 1 or self.row == 0:
                self._history(-1)
            else:
                self.row -= 1
                self.col = min(self.col, len(self.lines[self.row]))
            return None
        if key.name == "down":
            if self.single_line or self.row >= len(self.lines) - 1:
                self._history(1)
            else:
                self.row += 1
                self.col = min(self.col, len(self.lines[self.row]))
            return None
        if key.name == "ctrl-u":
            self.lines[self.row] = self.lines[self.row][self.col :]
            self.col = 0
            return None
        if key.name == "ctrl-w":
            self._delete_word()
            return None
        if key.is_char:
            self._insert(key.char)
            return None
        if key.name == "paste" and key.char is not None:
            self._paste(key.char)
            return None
        # Ignore unknown / paste-end / mouse so they never cancel dialogs
        return None

    def commit_history(self) -> None:
        text = self.text.strip("\n")
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
            if len(self.history) > 500:
                self.history = self.history[-500:]
        self._hist_index = None

    def _history(self, delta: int) -> None:
        if not self.history:
            return
        if self._hist_index is None:
            self._stash = self.text
            idx = len(self.history) if delta < 0 else -1
        else:
            idx = self._hist_index
        idx += delta
        if idx < 0:
            idx = 0
        if idx >= len(self.history):
            self._hist_index = None
            self.set_text(self._stash)
            return
        self._hist_index = idx
        self.set_text(self.history[idx])

    def _paste(self, text: str) -> None:
        """Insert clipboard text. In single_line mode, drop newlines (keep spaces)."""
        if not text:
            return
        if self.single_line:
            # Trailing clipboard \\n must not create lines / fake Enter.
            # Keep spaces so "Bearer sk-…" still cleans correctly on submit.
            cleaned = text.replace("\r", "").replace("\n", "").replace("\t", "")
            if cleaned:
                self._insert(cleaned)
            return
        self._insert(text)

    def _insert(self, text: str) -> None:
        for ch in text:
            if ch == "\n":
                if self.single_line:
                    continue
                self._newline()
                continue
            if ch == "\r":
                continue
            if ch == "\x1b":
                continue
            line = self.lines[self.row]
            self.lines[self.row] = line[: self.col] + ch + line[self.col :]
            self.col += 1

    def _newline(self) -> None:
        line = self.lines[self.row]
        left, right = line[: self.col], line[self.col :]
        self.lines[self.row] = left
        self.lines.insert(self.row + 1, right)
        self.row += 1
        self.col = 0
        self.hscroll = 0

    def _backspace(self) -> None:
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[: self.col - 1] + line[self.col :]
            self.col -= 1
            return
        if self.row == 0:
            return
        prev = self.lines[self.row - 1]
        cur = self.lines[self.row]
        self.col = len(prev)
        self.lines[self.row - 1] = prev + cur
        del self.lines[self.row]
        self.row -= 1

    def _delete(self) -> None:
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[: self.col] + line[self.col + 1 :]
            return
        if self.row + 1 < len(self.lines):
            self.lines[self.row] = line + self.lines[self.row + 1]
            del self.lines[self.row + 1]

    def _left(self) -> None:
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])

    def _right(self) -> None:
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row + 1 < len(self.lines):
            self.row += 1
            self.col = 0

    def _delete_word(self) -> None:
        line = self.lines[self.row]
        i = self.col
        while i > 0 and line[i - 1].isspace():
            i -= 1
        while i > 0 and not line[i - 1].isspace():
            i -= 1
        self.lines[self.row] = line[:i] + line[self.col :]
        self.col = i


def header_lines(
    title: str, width: int, glyphs: Glyphs, subtitle: str = ""
) -> list[Line]:
    out = [
        hline(width, glyphs),
        Line.mixed(
            (" ", "fg"),
            Span(truncate(title, width - 2), "primary", bold=True),
        ),
    ]
    if subtitle:
        out.append(Line.plain(" " + truncate(subtitle, width - 2), "muted"))
    out.append(hline(width, glyphs))
    out.append(blank())
    return out


def footer_lines(hints: str, width: int, glyphs: Glyphs) -> list[Line]:
    return [
        blank(),
        Line.plain(truncate(hints, width), "muted"),
    ]


def chrome_overhead(*, subtitle: str = "", hints: str = "", status: bool = False) -> int:
    """Line count consumed by chrome_frame chrome (header + footer)."""
    header = 4 + (1 if subtitle else 0)  # rule, title, [subtitle], rule, blank
    footer = (2 if hints else 0) + (1 if status else 0)
    return header + footer


def chrome_frame(
    body: list[Line],
    width: int,
    height: int,
    glyphs: Glyphs,
    *,
    title: str,
    subtitle: str = "",
    hints: str = "",
    cursor: tuple[int, int] | None = None,
    status: Line | None = None,
) -> Frame:
    lines = header_lines(title, width, glyphs, subtitle)
    overhead = chrome_overhead(subtitle=subtitle, hints=hints, status=status is not None)
    budget = max(1, height - overhead)
    if len(body) > budget:
        body = body[:budget]
    lines.extend(body)
    target = height - (2 if hints else 0) - (1 if status else 0)
    while len(lines) < target:
        lines.append(blank())
    if hints:
        lines.extend(footer_lines(hints, width, glyphs))
    if status:
        if len(lines) >= height:
            lines = lines[: height - 1]
        lines.append(status)
    if len(lines) > height:
        lines = lines[:height]
    return Frame(lines, cursor=cursor)


def status_line_text(
    parts: Sequence[str], width: int, glyphs: Glyphs
) -> Line:
    text = f" {f' {glyphs.sep} '.join(p for p in parts if p)} "
    return Line.plain(truncate(text, width), "muted")
