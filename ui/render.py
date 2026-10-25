"""
Rendering helpers for the OMGA terminal UI.

Everything the user sees is drawn with Rich using the centralised theme
tokens — no module hard-codes a colour. Logos, panels, rules, code
blocks, unified diffs and status lines all live here.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Iterable, Sequence

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from core.branding import TAGLINE, WORDMARK
from ui.theme import Theme, get_theme
from ui.terminal import supports_color

_EDGE = box.ROUNDED


# ── Console singleton ──────────────────────────────────────────────────────────

def make_console(theme: Theme) -> Console:
    return Console(
        markup=True,
        highlight=False,
        soft_wrap=True,
        color_system="truecolor" if supports_color() else None,
    )


def render_logo(theme: Theme, *, robot: bool = False) -> Text:
    """Minimal wordmark. The *robot* flag is ignored (legacy)."""
    out = Text()
    out.append(WORDMARK, style=theme.style("primary", bold=True))
    out.append("  ")
    out.append(TAGLINE, style=theme.style("muted"))
    return out


def logo_panel(theme: Theme) -> Panel:
    return Panel(
        render_logo(theme),
        border_style=theme["border"],
        box=box.SIMPLE,
        padding=(0, 1),
    )


# ── Panels / messages ──────────────────────────────────────────────────────────

def panel(
    content,
    theme: Theme,
    *,
    title: str = "",
    border_token: str = "border",
    box_: box.Box = _EDGE,
    padding: tuple[int, int] = (0, 2),
) -> Panel:
    title_str = ""
    if title:
        title_str = title
    return Panel(
        content,
        title=title_str,
        border_style=theme[border_token],
        box=box_,
        padding=padding,
    )


def info_panel(message: str, theme: Theme, title: str = "Info") -> Panel:
    text = Text(message)
    return Panel(
        text,
        title=title,
        border_style=theme["info"],
        box=_EDGE,
        padding=(0, 2),
    )


def message_panel(message: str, theme: Theme, *, token: str, icon: str,
                  title: str) -> Panel:
    body = Text()
    body.append(f"{icon}  ", style=theme.style(token, bold=True))
    body.append(message, style=theme["fg"])
    return Panel(body, title=title, border_style=theme[token], box=_EDGE,
                 padding=(0, 2))


def success_panel(message: str, theme: Theme, title: str = "Success") -> Panel:
    return message_panel(message, theme, token="success", icon="✓", title=title)


def error_panel(message: str, theme: Theme, title: str = "Error") -> Panel:
    return message_panel(message, theme, token="error", icon="✗", title=title)


def warning_panel(message: str, theme: Theme, title: str = "Warning") -> Panel:
    return message_panel(message, theme, token="warning", icon="⚠", title=title)


def rule(text: str, theme: Theme, token: str = "border") -> Rule:
    return Rule(text or "", style=theme[token])


# ── Code / markdown ────────────────────────────────────────────────────────────

def code_block(code: str, theme: Theme, language: str = "python",
               title: str = "") -> Panel:
    syn = Syntax(
        code,
        language,
        line_numbers=True,
        word_wrap=True,
        theme=theme.name if theme.name in _SYNTAX_THEMES else "default",
        background_color=theme["bg"],
    )
    return Panel(
        syn,
        title=title,
        border_style=theme["code"],
        box=_EDGE,
        padding=(1, 2),
    )


_SYNTAX_THEMES = {"ink", "dark", "light", "dracula", "nord", "minimal"}


def markdown(text: str, theme: Theme) -> Markdown:
    return Markdown(text, code_theme=theme.name if theme.name in _SYNTAX_THEMES
                    else "default")


def styled_text(text: str, theme: Theme, token: str = "fg") -> Text:
    return Text(text, style=theme[token])


# ── Diff ───────────────────────────────────────────────────────────────────────

@dataclass
class DiffLine:
    kind: str  # ' ', '+', '-', '@', ''
    text: str
    old_no: int | None = None
    new_no: int | None = None


def unified_diff(old: str, new: str, *, n: int = 3) -> list[DiffLine]:
    """Produce a line-numbered unified diff between *old* and *new*."""
    old_lines = old.splitlines(keepends=False)
    new_lines = new.splitlines(keepends=False)
    raw = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=n))
    result: list[DiffLine] = []
    old_num, new_num = 0, 0
    hunk_re = __import__("re").compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)")
    for line in raw:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            m = hunk_re.search(line)
            if m:
                old_num = int(m.group(1))
                new_num = int(m.group(2))
            result.append(DiffLine("@", line))
            continue
        if line.startswith("+"):
            result.append(DiffLine("+", line[1:], new_no=new_num))
            new_num += 1
        elif line.startswith("-"):
            result.append(DiffLine("-", line[1:], old_no=old_num))
            old_num += 1
        else:
            text = line[1:] if line.startswith(" ") else line
            result.append(DiffLine(" ", text, old_no=old_num, new_no=new_num))
            old_num += 1
            new_num += 1
    return result


def render_diff(diff: list[DiffLine], theme: Theme, *, width: int = 100) -> Text:
    """Render a list of DiffLines into a single Rich Text object."""
    out = Text()
    for d in diff:
        style = theme["fg"]
        prefix = ""
        line_no = ""
        if d.kind == "+":
            prefix = "+"
            style = theme["added"]
            no = f"{d.new_no:>4} " if d.new_no else ""
            out.append(f"{no}│ {prefix} {d.text}\n", style=style)
            continue
        elif d.kind == "-":
            prefix = "-"
            style = theme["removed"]
            no = f"{d.old_no:>4} " if d.old_no else ""
            out.append(f"{no}│ {prefix} {d.text}\n", style=style)
            continue
        elif d.kind == "@":
            out.append(f"  {d.text}\n", style=theme["muted"])
            continue
        no = f"{d.new_no or d.old_no or 0:>4} "
        out.append(f"{no}│   {d.text}\n", style=style)
    return out


def diff_panel(diff: list[DiffLine], theme: Theme, *, title: str = "",
               width: int = 100) -> Panel:
    return Panel(
        render_diff(diff, theme, width=width),
        title=title,
        border_style=theme["border"],
        box=_EDGE,
        padding=(1, 2),
    )


# ── Status / spinners ──────────────────────────────────────────────────────────

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def spinner_frame(i: int) -> str:
    return _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]


def status_line(message: str, theme: Theme, *, token: str = "info",
                icon: str = "") -> Text:
    t = Text()
    if icon:
        t.append(f"{icon}  ", style=theme.style(token))
    t.append(message, style=theme[token])
    return t


def tool_line(message: str, theme: Theme, *, icon: str = "") -> Text:
    t = Text()
    if icon:
        t.append(f"{icon}  ", style=theme.style("tool", bold=True))
    t.append(message, style=theme["tool"])
    return t


def ok_line(message: str, theme: Theme, icon: str = "✓") -> Text:
    return tool_line(message, theme, icon=icon)


# Re-export the default console factory for callers that want a shared console.
def default_console(theme_name: str = "ink") -> Console:
    return make_console(get_theme(theme_name))
