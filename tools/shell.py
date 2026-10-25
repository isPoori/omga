"""
Shell tool for the OMGA agent (with the safety layer applied).

The handler inspects a shell command, runs it through the safety layer,
captures stdout/stderr, and returns a structured result the agent can read.
Interactive/destructive commands are surfaced for approval before running.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from core.errors import CommandError, SafetyError
from tools.safety import assess
from tools import procs as bg

_BG_RE = re.compile(
    r"\b(watch|serve|start|dev|nodemon|tail\s+-f)\b",
    re.IGNORECASE,
)


def run_shell_command(
    command: str,
    cwd: str | Path | None = None,
    timeout: int = 120,
    background: bool = False,
    cancel=None,
) -> dict[str, Any]:
    """Execute *command* in a shell under *cwd*, applying the safety layer."""
    verdict = assess(command)
    if not verdict.allowed:
        raise SafetyError(verdict.reason)

    should_bg = bool(background) or bool(_BG_RE.search(command))
    if should_bg:
        return bg.start(command, str(cwd) if cwd else None)

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        bg._PROCS[proc.pid] = proc
        while True:
            if bg.cancelled() or (cancel is not None and callable(cancel) and cancel()):
                bg._kill(proc)
                bg._PROCS.pop(proc.pid, None)
                return {
                    "command": command,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Stopped by the user.",
                    "cancelled": True,
                    "elapsed_seconds": round(time.monotonic() - start, 2),
                }
            try:
                stdout, stderr = proc.communicate(timeout=0.25)
                bg._PROCS.pop(proc.pid, None)
                elapsed = time.monotonic() - start
                return {
                    "command": command,
                    "exit_code": proc.returncode,
                    "stdout": stdout[-12000:] if stdout else "",
                    "stderr": stderr[-6000:] if stderr else "",
                    "elapsed_seconds": round(elapsed, 2),
                }
            except subprocess.TimeoutExpired:
                if time.monotonic() - start >= timeout:
                    bg._kill(proc)
                    bg._PROCS.pop(proc.pid, None)
                    raise CommandError(
                        f"Command timed out after {timeout}s.",
                        hint="Start long jobs with background=true, or raise the timeout.",
                        debug=command,
                    ) from None
    except CommandError:
        raise


def shell_tool(root: str | Path) -> "Tool":
    from tools.base import Tool

    def handler(command: str, timeout: int = 120, background: bool = False) -> dict[str, Any]:
        return run_shell_command(
            command,
            cwd=str(root),
            timeout=timeout,
            background=background,
        )

    return Tool(
        "run_command",
        "Run a shell command in the project directory. "
        "Set background=true for long-running or watch processes (dev servers). "
        "Destructive commands are blocked or require approval. "
        "Prefer targeted commands over scanning the whole tree on large projects.",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds for foreground runs (default 120).",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "If true, start the process and return immediately.",
                    },
                },
                "required": ["command"],
            }
        },
    )
