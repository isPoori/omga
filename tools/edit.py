"""Surgical file edit (exact string replace) — preferred over full rewrites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.errors import ToolError
from tools.files import BasePathTools


def edit_file_tool(root: str | Path) -> "Tool":
    from tools.base import Tool

    base = BasePathTools(root)

    def handler(
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        if old_string == new_string:
            raise ToolError("old_string and new_string are identical.")
        if not old_string:
            raise ToolError("old_string must not be empty.")
        target = base._resolve(path)
        if not target.is_file():
            raise ToolError(f"File not found: {path}")
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Cannot read {path}: {exc}") from exc
        count = content.count(old_string)
        if count == 0:
            raise ToolError(
                f"old_string not found in {path}. "
                "Read the file again and use an exact contiguous snippet."
            )
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string matched {count} times in {path}. "
                "Provide a larger unique snippet, or set replace_all=true."
            )
        if replace_all:
            updated = content.replace(old_string, new_string)
            replacements = count
        else:
            updated = content.replace(old_string, new_string, 1)
            replacements = 1
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Cannot write {path}: {exc}") from exc
        return {
            "path": str(path),
            "replacements": replacements,
            "success": True,
        }

    return Tool(
        "edit_file",
        "Surgically edit a file by replacing an exact string match. "
        "Prefer this over write_file for existing files. "
        "old_string must match the file contents exactly (including whitespace).",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path within the project.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to find.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every match (default false).",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            }
        },
    )
