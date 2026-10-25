"""
Git-awareness tools for the OMGA agent.

These tools inspect the repository (status, branch, changed files, recent
log). OMGA never commits or performs destructive git operations on its
own — mutation is left to the safe shell tool with approval.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from core.errors import ToolError


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(root),
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:
        raise ToolError(f"git {args[0] if args else ''} failed: {exc}") from exc
    if out.returncode != 0:
        raise ToolError(f"git {args[0] if args else ''}: {out.stderr.strip()}")
    return out.stdout


def git_status(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    try:
        status = _git(root, "status", "--porcelain")
    except ToolError:
        return {"is_git": False}
    branch = "?"
    try:
        branch = _git(root, "branch", "--show-current").strip() or "HEAD"
    except ToolError:
        pass
    changed: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        code = line[:2].strip()
        path = line[3:].strip()
        changed.append({"status": code, "path": path})
    return {"is_git": True, "branch": branch, "changed": changed}


def git_diff(root: str | Path, path: str | None = None,
             staged: bool = False) -> str:
    root = Path(root)
    args = ["diff"]
    if staged:
        args.append("--cached")
    if path:
        args.append("--")
        args.append(path)
    try:
        return _git(root, *args)
    except ToolError:
        return ""


def git_log(root: str | Path, n: int = 8) -> list[dict[str, str]]:
    root = Path(root)
    try:
        raw = _git(root, "log", f"-{n}", "--format=%h|%s")
    except ToolError:
        return []
    rows = []
    for line in raw.splitlines():
        if "|" in line:
            h, s = line.split("|", 1)
            rows.append({"hash": h, "subject": s})
    return rows


def git_tools(root: str | Path) -> list["Tool"]:
    from tools.base import Tool

    root = Path(root)

    def status_handler() -> dict[str, Any]:
        return git_status(root)

    def diff_handler(path: str = "", staged: bool = False) -> dict[str, Any]:
        return {"diff": git_diff(root, path or None, staged)}

    def log_handler(count: int = 8) -> dict[str, Any]:
        return {"commits": git_log(root, count)}

    return [
        Tool("git_status",
             "Return the repository status: branch and changed files.",
             status_handler,
             {"parameters": {"type": "object",
                             "properties": {}}}),
        Tool("git_diff",
             "Return the git diff for a path (or the whole working tree).",
             diff_handler,
             {"parameters": {"type": "object",
                             "properties": {
                                 "path": {"type": "string",
                                          "description": "Optional path."},
                                 "staged": {"type": "boolean",
                                            "description": "Cached diff?"},
                             }}}),
        Tool("git_log",
             "Return the most recent commits (hash + subject).",
             log_handler,
             {"parameters": {"type": "object",
                             "properties": {
                                 "count": {"type": "integer",
                                           "description": "Number of commits."},
                             }}}),
    ]
