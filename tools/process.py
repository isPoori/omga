"""Background process polling for the agent."""

from __future__ import annotations

from typing import Any

from tools import procs


def process_tools() -> list["Tool"]:
    from tools.base import Tool

    def poll_process(pid: int = 0) -> dict[str, Any]:
        if pid:
            return procs.poll(int(pid))
        from tools.procs import _PROCS

        out = []
        for p in list(_PROCS.keys()):
            info = procs.poll(p)
            if info.get("status") == "running":
                # poll() consumes exited procs; re-check via dict for running ones
                out.append(info)
            elif info.get("status") != "unknown":
                out.append(info)
        # Also surface still-running without re-polling exited twice
        for p, proc in list(_PROCS.items()):
            if proc.poll() is None and not any(i.get("pid") == p for i in out):
                out.append({"pid": p, "status": "running"})
        return {"processes": out, "count": len(out)}

    return [
        Tool(
            "poll_process",
            "Poll a background process started with run_command(background=true). "
            "Omit pid to list all tracked processes.",
            poll_process,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pid": {
                            "type": "integer",
                            "description": "Process id; 0 lists all.",
                        },
                    },
                }
            },
        ),
    ]
