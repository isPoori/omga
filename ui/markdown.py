"""Lightweight markdown → TUI lines (no Rich).

Assistant messages are rendered here so **bold**, `code`, headings and
fences show as styles instead of raw punctuation. Encoding glitches from
providers (mojibake of em-dashes and quotes) are repaired first.
"""

from __future__ import annotations

import re

from ui.kernel import Line, Span
from ui.measure import _take, display_width, wrap

_FENCE = re.compile(r"^```(\w+)?\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")


def repair_text(text: str) -> str:
    """Fix common UTF-8-as-latin1 damage and normalise punctuation."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if any(ch in text for ch in ("â", "Ã", "Â")):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if "\ufffd" not in repaired:
                text = repaired
        except UnicodeError:
            pass
    table = str.maketrans({
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    })
    return text.translate(table)


def render_markdown(text: str, width: int) -> list[Line]:
    text = repair_text(text)
    if width <= 0:
        width = 80
    lines: list[Line] = []
    fence_lang: str | None = None
    fence_buf: list[str] = []

    for raw in text.split("\n"):
        if fence_lang is not None:
            if _FENCE.match(raw.strip()):
                if fence_lang:
                    lines.append(Line.plain(f"  {fence_lang}", "muted"))
                for row in fence_buf:
                    for w in wrap(row, max(8, width - 4)) or [""]:
                        lines.append(Line.mixed(
                            Span("  ", "fg"),
                            Span(w, "code"),
                        ))
                fence_lang = None
                fence_buf = []
            else:
                fence_buf.append(raw)
            continue

        m = _FENCE.match(raw.strip())
        if m:
            fence_lang = m.group(1) or ""
            fence_buf = []
            continue

        if not raw.strip():
            lines.append(Line.plain(""))
            continue

        hm = _HEADING.match(raw)
        if hm:
            body = hm.group(2).strip()
            lines.extend(_wrap_spans([Span(body, "primary", bold=True)], width))
            continue

        um = _UL.match(raw)
        if um:
            indent = len(um.group(1) or "")
            body = um.group(3)
            prefix = Span(" " * min(indent, 4) + "• ", "accent")
            rest = _inline_spans(body)
            lines.extend(_wrap_spans([prefix, *rest], width))
            continue

        om = _OL.match(raw)
        if om:
            indent = len(om.group(1) or "")
            n = om.group(2)
            body = om.group(3)
            prefix = Span(" " * min(indent, 4) + f"{n}. ", "accent")
            lines.extend(_wrap_spans([prefix, *_inline_spans(body)], width))
            continue

        lines.extend(_wrap_spans(_inline_spans(raw), width))

    if fence_lang is not None:
        for row in fence_buf:
            for w in wrap(row, max(8, width - 4)) or [""]:
                lines.append(Line.mixed(Span("  ", "fg"), Span(w, "code")))
    return lines or [Line.plain("")]


def _inline_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    pos = 0
    for m in re.finditer(
        r"`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*]+)\*|_([^_]+)_",
        text,
    ):
        if m.start() > pos:
            spans.append(Span(text[pos:m.start()], "fg"))
        if m.group(1) is not None:
            spans.append(Span(m.group(1), "code"))
        elif m.group(2) is not None:
            spans.append(Span(m.group(2), "fg", bold=True))
        elif m.group(3) is not None:
            spans.append(Span(m.group(3), "fg", bold=True))
        elif m.group(4) is not None:
            spans.append(Span(m.group(4), "accent"))
        else:
            spans.append(Span(m.group(5), "accent"))
        pos = m.end()
    if pos < len(text):
        spans.append(Span(text[pos:], "fg"))
    return spans or [Span(text, "fg")]


def _wrap_spans(spans: list[Span], width: int) -> list[Line]:
    rows: list[Line] = []
    current: list[Span] = []
    used = 0
    for sp in spans:
        rest = sp.text
        while rest:
            room = width - used
            if room <= 0:
                rows.append(Line(current or [Span("", "fg")]))
                current = []
                used = 0
                continue
            take = _take(rest, room)
            if not take:
                take = rest[0]
            current.append(Span(take, sp.token, bold=sp.bold, dim=sp.dim, inverse=sp.inverse))
            used += display_width(take)
            rest = rest[len(take):]
            if used >= width:
                rows.append(Line(current))
                current = []
                used = 0
    if current:
        rows.append(Line(current))
    return rows or [Line.plain("")]
