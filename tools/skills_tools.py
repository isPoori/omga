"""Skill tools — list, load, and create procedural playbooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills.loader import SkillCatalog, create_skill, load_skills


def skills_tools(catalog: SkillCatalog, project_root: Path | None = None) -> list["Tool"]:
    from tools.base import Tool

    def list_skills(query: str = "") -> dict[str, Any]:
        items = catalog.search(query) if query else catalog.skills
        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "source": s.source,
                    "tags": s.tags,
                }
                for s in items
            ],
            "count": len(items),
        }

    def load_skill(name: str) -> dict[str, Any]:
        skill = catalog.by_name(name)
        if skill is None:
            # Reload in case user created one mid-session.
            refreshed = load_skills(project_root)
            catalog.skills = refreshed.skills
            skill = catalog.by_name(name)
        if skill is None:
            return {
                "error": f"Unknown skill: {name}",
                "available": [s.name for s in catalog.skills[:30]],
            }
        return {
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "content": skill.prompt_block(),
        }

    def create_skill_tool(
        name: str,
        description: str,
        body: str,
        tags: str = "",
    ) -> dict[str, Any]:
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        skill = create_skill(name, description, body, tags=tag_list)
        catalog.skills = [s for s in catalog.skills if s.name.lower() != skill.name.lower()]
        catalog.skills.append(skill)
        catalog.skills.sort(key=lambda s: s.name.lower())
        return {
            "created": True,
            "name": skill.name,
            "path": str(skill.path),
        }

    return [
        Tool(
            "list_skills",
            "List available skills (procedural playbooks). Optional query filters.",
            list_skills,
            {
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                }
            },
        ),
        Tool(
            "load_skill",
            "Load the full body of a skill into the tool result for this turn.",
            load_skill,
            {
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            },
        ),
        Tool(
            "create_skill",
            "Save a new reusable skill under the user's skills directory after "
            "a complex procedure that will recur.",
            create_skill_tool,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "body": {"type": "string"},
                        "tags": {"type": "string", "description": "Comma-separated tags"},
                    },
                    "required": ["name", "description", "body"],
                }
            },
        ),
    ]
