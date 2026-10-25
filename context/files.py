"""
Load project context files (AGENTS.md, .omga/*, etc.).

These shape every conversation the same way Hermes context files do —
stable project instructions that sit above volatile memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Ordered by priority (first wins when names collide for the same role).
_CANDIDATES = (
    "AGENTS.md",
    "OMGA.md",
    ".omga/AGENTS.md",
    ".omga/rules.md",
    ".omga/instructions.md",
    "CLAUDE.md",
    ".cursorrules",
    "CONTRIBUTING.md",
)

_MAX_TOTAL = 12_000
_MAX_PER_FILE = 6_000


@dataclass
class ContextBundle:
    files: list[tuple[str, str]] = field(default_factory=list)

    def prompt_block(self) -> str:
        if not self.files:
            return ""
        parts = ["## Project instructions"]
        budget = _MAX_TOTAL
        for name, body in self.files:
            chunk = body.strip()
            if not chunk:
                continue
            if len(chunk) > _MAX_PER_FILE:
                chunk = chunk[: _MAX_PER_FILE - 1] + "…"
            if len(chunk) > budget:
                chunk = chunk[: max(0, budget - 1)] + "…"
            parts.append(f"### {name}\n{chunk}")
            budget -= len(chunk)
            if budget <= 0:
                break
        return "\n\n".join(parts)


def load_context_files(root: Path) -> ContextBundle:
    root = Path(root).resolve()
    seen: set[str] = set()
    files: list[tuple[str, str]] = []
    for rel in _CANDIDATES:
        path = root / rel
        key = path.name.lower()
        # Allow both AGENTS.md and .omga/rules.md; skip duplicate basenames
        # only for the primary instruction names.
        if key in seen and key in {"agents.md", "claude.md", ".cursorrules"}:
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        seen.add(key)
        files.append((rel, text))
    return ContextBundle(files=files)
