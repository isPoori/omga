"""Memory tools — remember, recall, search past sessions, update profile."""

from __future__ import annotations

from typing import Any

from memory.profile import save_profile_note, update_user_field
from memory.store import MemoryStore


def memory_tools(
    store: MemoryStore,
    *,
    cwd: str = "",
) -> list["Tool"]:
    from tools.base import Tool

    def remember(
        content: str,
        kind: str = "note",
        tags: str = "",
        importance: int = 1,
        also_profile: bool = False,
        profile_section: str = "Lessons",
    ) -> dict[str, Any]:
        mid = store.remember(
            content,
            kind=kind,
            tags=tags,
            cwd=cwd,
            importance=int(importance or 1),
        )
        if also_profile:
            save_profile_note(profile_section, content)
        return {"id": mid, "saved": True, "profile_updated": bool(also_profile)}

    def recall(query: str = "", limit: int = 10) -> dict[str, Any]:
        hits = store.search_memories(query, limit=int(limit or 10), cwd=cwd)
        return {"query": query, "results": hits, "count": len(hits)}

    def search_sessions(query: str, limit: int = 10) -> dict[str, Any]:
        hits = store.search_messages(query, limit=int(limit or 10), cwd=cwd or None)
        return {"query": query, "results": hits, "count": len(hits)}

    def update_profile(field: str, value: str) -> dict[str, Any]:
        field = (field or "").strip()
        value = (value or "").strip()
        if not field or not value:
            return {"error": "field and value are required"}
        # Common fields map to USER.md lines; anything else goes to MEMORY.md.
        user_fields = {
            "name": "- Name:",
            "prefers": "- Prefers:",
            "stack": "- Languages / stack:",
            "languages": "- Languages / stack:",
            "notes": "- Notes:",
        }
        key = field.lower()
        if key in user_fields:
            update_user_field(user_fields[key], value)
            return {"updated": "USER.md", "field": key}
        save_profile_note(field, value)
        return {"updated": "MEMORY.md", "section": field}

    def forget(memory_id: str) -> dict[str, Any]:
        ok = store.forget(memory_id)
        return {"id": memory_id, "deleted": ok}

    tools = [
        Tool(
            "remember",
            "Persist a durable fact, preference, or lesson for future sessions. "
            "Use for things that should survive /clear. Set also_profile=true "
            "to also append to MEMORY.md.",
            remember,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["note", "preference", "project", "lesson", "person"],
                        },
                        "tags": {"type": "string"},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                        "also_profile": {"type": "boolean"},
                        "profile_section": {"type": "string"},
                    },
                    "required": ["content"],
                }
            },
        ),
        Tool(
            "recall",
            "Search long-term memories. Empty query returns recent important notes.",
            recall,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                }
            },
        ),
        Tool(
            "search_sessions",
            "Full-text search across past conversation sessions (FTS).",
            search_sessions,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                }
            },
        ),
        Tool(
            "update_user_profile",
            "Update who the user is (name, prefers, stack, notes) or append a "
            "MEMORY.md section. Helps the agent grow with the user.",
            update_profile,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "name|prefers|stack|notes or a MEMORY section",
                        },
                        "value": {"type": "string"},
                    },
                    "required": ["field", "value"],
                }
            },
        ),
        Tool(
            "forget",
            "Delete a memory by id returned from remember/recall.",
            forget,
            {
                "parameters": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                }
            },
        ),
    ]
    return tools
