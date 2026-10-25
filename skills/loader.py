"""
Skill discovery and loading (agentskills.io-compatible SKILL.md).

Skills are procedural memory: reusable playbooks the agent loads on demand
and can create/refine after complex tasks (Hermes-style learning loop).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from core.paths import skills_dir

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    source: str = "user"  # bundled | user | project

    def prompt_block(self, *, max_chars: int = 8_000) -> str:
        text = f"# Skill: {self.name}\n\n{self.description}\n\n{self.body}".strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        return text


@dataclass
class SkillCatalog:
    skills: list[Skill] = field(default_factory=list)

    def by_name(self, name: str) -> Skill | None:
        key = name.strip().lower()
        for s in self.skills:
            if s.name.lower() == key:
                return s
        return None

    def search(self, query: str) -> list[Skill]:
        q = (query or "").lower().strip()
        if not q:
            return list(self.skills)
        hits = []
        for s in self.skills:
            blob = f"{s.name} {s.description} {' '.join(s.tags)}".lower()
            if q in blob or all(tok in blob for tok in q.split()):
                hits.append(s)
        return hits


def load_skills(project_root: Path | None = None) -> SkillCatalog:
    found: dict[str, Skill] = {}
    # Bundled (lowest priority)
    for skill in _iter_skill_dirs(_bundled_dir()):
        found[skill.name.lower()] = skill
    # User
    for skill in _iter_skill_dirs(skills_dir()):
        skill.source = "user"
        found[skill.name.lower()] = skill
    # Project (highest)
    if project_root:
        for rel in (".omga/skills", "skills"):
            for skill in _iter_skill_dirs(Path(project_root) / rel):
                skill.source = "project"
                found[skill.name.lower()] = skill
    skills = sorted(found.values(), key=lambda s: s.name.lower())
    return SkillCatalog(skills=skills)


def format_skills_catalog(catalog: SkillCatalog, *, max_items: int = 40) -> str:
    if not catalog.skills:
        return ""
    lines = [
        "## Available skills",
        "Use load_skill(name) to pull a full playbook into context when relevant.",
    ]
    for s in catalog.skills[:max_items]:
        desc = s.description.replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "…"
        lines.append(f"- {s.name}: {desc}")
    if len(catalog.skills) > max_items:
        lines.append(f"- … and {len(catalog.skills) - max_items} more")
    return "\n".join(lines)


def create_skill(
    name: str,
    description: str,
    body: str,
    *,
    dest: Path | None = None,
    tags: list[str] | None = None,
) -> Skill:
    """Write a new skill under the user skills directory."""
    safe = _safe_name(name)
    root = dest or (skills_dir() / safe)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "SKILL.md"
    tag_line = ""
    if tags:
        tag_line = "\n  tags: [" + ", ".join(tags) + "]"
    content = (
        f"---\n"
        f"name: {safe}\n"
        f"description: \"{_escape_yaml(description)}\"\n"
        f"version: 1.0.0\n"
        f"metadata:\n"
        f"  omga:{tag_line}\n"
        f"---\n\n"
        f"{body.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    return Skill(
        name=safe,
        description=description.strip(),
        body=body.strip(),
        path=path,
        tags=list(tags or []),
        source="user",
    )


def _bundled_dir() -> Path:
    return Path(__file__).resolve().parent / "bundled"


def _iter_skill_dirs(root: Path) -> Iterator[Skill]:
    if not root.is_dir():
        return
    # Flat SKILL.md
    direct = root / "SKILL.md"
    if direct.is_file():
        skill = _parse_skill(direct, fallback_name=root.name)
        if skill:
            yield skill
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            md = child / "SKILL.md"
            if md.is_file():
                skill = _parse_skill(md, fallback_name=child.name)
                if skill:
                    yield skill
        elif child.name.endswith(".md") and child.name.upper() != "README.MD":
            skill = _parse_skill(child, fallback_name=child.stem)
            if skill:
                yield skill


def _parse_skill(path: Path, *, fallback_name: str) -> Skill | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    name = fallback_name
    description = ""
    version = "1.0.0"
    tags: list[str] = []
    body = raw
    m = _FRONTMATTER.match(raw)
    if m:
        meta, body = m.group(1), m.group(2)
        parsed = _parse_frontmatter(meta)
        name = str(parsed.get("name") or name)
        description = str(parsed.get("description") or "")
        version = str(parsed.get("version") or version)
        raw_tags = parsed.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags]
        elif isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    if not description:
        # First non-empty non-heading line as description.
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                description = line[:200]
                break
    if not name.strip():
        return None
    return Skill(
        name=name.strip(),
        description=description.strip() or name.strip(),
        body=body.strip(),
        path=path,
        version=version,
        tags=tags,
        source="bundled",
    )


def _parse_frontmatter(text: str) -> dict:
    data: dict = {}
    for line in text.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            data[key] = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
        else:
            data[key] = val
        # Nested metadata.omga.tags — keep simple flat keys.
        if key == "tags" or key.endswith("tags"):
            if isinstance(data[key], list):
                data["tags"] = data[key]
    return data


def _safe_name(name: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip().lower()).strip("-")
    return raw or "skill"


def _escape_yaml(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
