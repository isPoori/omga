"""Tracked background processes started by the shell tool."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


_PROCS: dict[int, subprocess.Popen] = {}
_cancel = lambda: False


def set_cancel(fn) -> None:
    global _cancel
    _cancel = fn if fn else (lambda: False)


def cancelled() -> bool:
    try:
        return bool(_cancel())
    except Exception:
        return False


def start(command: str, cwd: str | None, timeout: int | None = None) -> dict[str, Any]:
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _PROCS[proc.pid] = proc
    return {
        "command": command,
        "pid": proc.pid,
        "background": True,
        "status": "running",
        "note": "Started in the background. It will keep running until it exits or you stop OMGA.",
    }


def poll(pid: int) -> dict[str, Any]:
    proc = _PROCS.get(pid)
    if proc is None:
        return {"pid": pid, "status": "unknown"}
    code = proc.poll()
    if code is None:
        return {"pid": pid, "status": "running", "command": " ".join(map(str, proc.args)) if proc.args else ""}
    stdout, stderr = "", ""
    try:
        stdout, stderr = proc.communicate(timeout=0.2)
    except Exception:
        pass
    _PROCS.pop(pid, None)
    return {
        "pid": pid,
        "status": "exited",
        "exit_code": code,
        "stdout": (stdout or "")[-8000:],
        "stderr": (stderr or "")[-4000:],
    }


def kill_all() -> int:
    n = 0
    for pid, proc in list(_PROCS.items()):
        _kill(proc)
        n += 1
        _PROCS.pop(pid, None)
    return n


def _kill(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:
            pass
