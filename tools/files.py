"""
FileSystem + Search + Diff tools for the OMGA agent.

Each function is a standalone tool handler operating on an explicit base
(project root) so the agent cannot escape the project accidentally.
Path safety: every resolved path must stay within the project root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.errors import ToolError

_MAX_READ_BYTES = 512 * 1024  # 512 KB cap per file read


class BasePathTools:
    """Shared path-safety helpers; subclasses run under a project root."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getcwd()).resolve()

    def _resolve(self, path: str | Path) -> Path:
        p = (self.root / path).resolve()
        if not (p == self.root or self.root in p.parents or p.is_relative_to(self.root)):
            raise ToolError(f"Path outside project: {path}")
        return p


def read_file_tool(root: str | Path) -> "Tool":
    from tools.base import Tool

    base = BasePathTools(root)

    def handler(path: str, offset: int = 0, limit: int = 0) -> dict[str, Any]:
        target = base._resolve(path)
        if not target.is_file():
            raise ToolError(f"File not found: {path}")
        size = target.stat().st_size
        if size > _MAX_READ_BYTES:
            raise ToolError(f"File too large to read ({size} bytes > 512 KB): {path}")
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        lines = content.splitlines(keepends=True)
        if offset or limit:
            start = max(0, offset - 1)
            end = None if not limit else start + limit
            selected = "".join(lines[start:end])
        else:
            selected = content
        from config.store import get
        if get("security.redact_secrets", True):
            from core.security import redact
            selected, _hits = redact(selected)
        return {
            "path": str(path),
            "content": selected,
            "total_lines": len(lines),
        }

    return Tool(
        "read_file",
        "Read a text file within the project and return its contents. "
        "Use offset/limit to read a slice of very large files.",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Relative path within the project."},
                    "offset": {"type": "integer",
                               "description": "1-based start line (optional)."},
                    "limit": {"type": "integer",
                              "description": "Max lines to return (optional)."},
                },
                "required": ["path"],
            }
        },
    )


def write_file_tool(root: str | Path) -> "Tool":
    from tools.base import Tool

    base = BasePathTools(root)

    def handler(path: str, content: str, mode: str = "replace") -> dict[str, Any]:
        target = base._resolve(path)
        parent = target.parent
        # Only create new files, never walk upward out of the project.
        parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(content)
        else:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
        return {"path": str(path), "success": True}

    return Tool(
        "write_file",
        "Create or overwrite a text file within the project with the given "
        "content. mode='append' appends instead of replacing.",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Relative path within the project."},
                    "content": {"type": "string",
                                "description": "Full file content to write."},
                    "mode": {"type": "string",
                             "enum": ["replace", "append"],
                             "description": "replace (default) or append."},
                },
                "required": ["path", "content"],
            }
        },
    )


def delete_file_tool(root: str | Path) -> "Tool":
    from tools.base import Tool

    base = BasePathTools(root)

    def handler(path: str) -> dict[str, Any]:
        target = base._resolve(path)
        if not target.exists():
            raise ToolError(f"File not found: {path}")
        if target.is_dir():
            raise ToolError("Refusing to delete a directory. Use shell for that.")
        target.unlink()
        return {"path": str(path), "deleted": True}

    return Tool(
        "delete_file",
        "Delete a single file within the project. Only for explicit, "
        "safe cases (the agent still asks for approval on destructive steps).",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Relative path within the project."},
                },
                "required": ["path"],
            }
        },
    )


def list_files_tool(root: str | Path) -> "Tool":
    from tools.base import Tool
    from core.project import Project

    project = Project(Path(root).resolve())

    def handler(path: str = ".") -> dict[str, Any]:
        node = project.root / path
        if not node.is_dir():
            raise ToolError(f"Not a directory: {path}")
        names = sorted(os.listdir(node))
        skipped = [n for n in names if n in {
            "node_modules", ".git", "dist", "build", ".next", "target",
            ".venv", "venv", "__pycache__",
        }]
        visible = [n for n in names if n not in skipped]
        if len(visible) > 400:
            visible = visible[:400]
            truncated = True
        else:
            truncated = False
        return {
            "path": str(path),
            "entries": visible,
            "skipped": skipped,
            "truncated": truncated,
            "count": len(visible),
        }

    return Tool(
        "list_files",
        "List the immediate entries of a directory within the project.",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Directory path (default '.')."},
                },
            }
        },
    )


def search_tool(root: str | Path) -> "Tool":
    from tools.base import Tool
    from core.project import Project, is_ignored

    project = Project(Path(root).resolve())

    def handler(pattern: str, path: str = ".") -> dict[str, Any]:
        import re as _re
        try:
            rx = _re.compile(pattern, _re.IGNORECASE)
        except _re.error as exc:
            raise ToolError(f"Invalid regex: {exc}") from None
        results: list[dict[str, Any]] = []
        search_root = project.root / path
        if not search_root.is_dir():
            raise ToolError(f"Not a directory: {path}")
        for dirpath, dirnames, filenames in os.walk(search_root):
            dirnames[:] = [d for d in dirnames
                           if d not in _skip and not d.startswith(".")]
            for fn in filenames:
                fp = Path(dirpath) / fn
                if is_ignored(fp, project.root):
                    continue
                try:
                    if fp.stat().st_size > 256 * 1024:
                        continue
                    content = fp.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for lineno, line in enumerate(content.splitlines(), 1):
                    if rx.search(line):
                        results.append({
                            "file": str(fp.relative_to(project.root)),
                            "line": lineno,
                            "text": line.strip()[:200],
                        })
                if len(results) >= 200:
                    break
            if len(results) >= 200:
                break
        return {"pattern": pattern, "results": results}

    _skip = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist",
             "build", ".next", "target"}
    return Tool(
        "search",
        "Search file contents in the project using a regular expression. "
        "Returns matching lines with file and line number.",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string",
                                "description": "Regular expression to match."},
                    "path": {"type": "string",
                             "description": "Subdirectory to search (default '.')."},
                },
                "required": ["pattern"],
            }
        },
    )


def grep_tool(root: str | Path) -> "Tool":
    """Alias of search for agent clarity."""
    return search_tool(root)
