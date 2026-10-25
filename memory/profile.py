"""
Durable user/project profile files (USER.md + MEMORY.md).

The agent deepens its model of who you are across sessions by reading
these files into every system prompt and updating them via memory tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.paths import memory_file, user_profile_file

_USER_TEMPLATE = """# User

- Name:
- Prefers: concise answers, small diffs, verify with tests when cheap
- Languages / stack:
- Notes:
"""

_MEMORY_TEMPLATE = """# Long-term memory

Curated facts the agent should remember across sessions.
Keep entries short. Prefer durable preferences and project facts over
ephemeral task state.

## Preferences

## Projects

## Lessons
"""


@dataclass
class MemoryProfile:
    user_md: str = ""
    memory_md: str = ""

    def prompt_block(self, *, max_chars: int = 6000) -> str:
        parts: list[str] = []
        user = self.user_md.strip()
        mem = self.memory_md.strip()
        if user:
            parts.append("## Who the user is\n" + user)
        if mem:
            parts.append("## Long-term memory\n" + mem)
        text = "\n\n".join(parts)
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        return text


def load_profile() -> MemoryProfile:
    user_path = user_profile_file()
    mem_path = memory_file()
    _ensure(user_path, _USER_TEMPLATE)
    _ensure(mem_path, _MEMORY_TEMPLATE)
    return MemoryProfile(
        user_md=_read(user_path),
        memory_md=_read(mem_path),
    )


def save_profile_note(section: str, note: str) -> None:
    """Append a short note under a MEMORY.md section heading."""
    path = memory_file()
    _ensure(path, _MEMORY_TEMPLATE)
    note = (note or "").strip()
    if not note:
        return
    section = (section or "Lessons").strip().lstrip("#").strip() or "Lessons"
    text = _read(path)
    heading = f"## {section}"
    bullet = f"- {note}"
    if heading in text:
        # Insert after the heading line.
        lines = text.splitlines()
        out: list[str] = []
        inserted = False
        for i, line in enumerate(lines):
            out.append(line)
            if not inserted and line.strip() == heading:
                # Skip blank line after heading if present.
                if i + 1 < len(lines) and lines[i + 1].strip() == "":
                    out.append("")
                    # Will still process next blank via loop — avoid dup by
                    # marking and appending bullet after blank handling below.
                out.append(bullet)
                inserted = True
        if not inserted:
            out.append("")
            out.append(heading)
            out.append(bullet)
        path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    else:
        path.write_text(
            text.rstrip() + f"\n\n{heading}\n{bullet}\n",
            encoding="utf-8",
        )


def update_user_field(line_prefix: str, value: str) -> None:
    """Update a `- Prefix:` line in USER.md, or append it."""
    path = user_profile_file()
    _ensure(path, _USER_TEMPLATE)
    value = (value or "").strip()
    if not value:
        return
    prefix = line_prefix if line_prefix.endswith(":") else f"{line_prefix}:"
    if not prefix.startswith("- "):
        prefix = f"- {prefix}"
    lines = _read(path).splitlines()
    updated = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(prefix.split(":")[0]):
            out.append(f"{prefix} {value}")
            updated = True
        else:
            out.append(line)
    if not updated:
        out.append(f"{prefix} {value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _ensure(path: Path, template: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template, encoding="utf-8")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
