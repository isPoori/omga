"""
Subagent delegation — spawn an isolated child Agent for a focused subtask.

The child gets a fresh history, the same tools (minus delegate), and returns
a concise result so the parent can parallelize reasoning without context bloat.
"""

from __future__ import annotations

from typing import Any, Callable


def delegate_tool(
    *,
    make_child: Callable[[str], str],
) -> "Tool":
    from tools.base import Tool

    def handler(task: str, context: str = "") -> dict[str, Any]:
        task = (task or "").strip()
        if not task:
            return {"error": "task is required"}
        prompt = task
        if context.strip():
            prompt = f"{task}\n\nContext:\n{context.strip()}"
        try:
            result = make_child(prompt)
        except Exception as exc:
            return {"error": str(exc), "success": False}
        text = (result or "").strip()
        if len(text) > 12_000:
            text = text[:12_000] + "\n… truncated"
        return {"success": True, "result": text}

    return Tool(
        "delegate_task",
        "Spawn an isolated subagent for a focused subtask. Use for parallel "
        "investigation or to keep the parent context clean. The subagent "
        "cannot itself delegate. Return value is the subagent's final text.",
        handler,
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Clear, self-contained instruction for the subagent.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional background the subagent needs.",
                    },
                },
                "required": ["task"],
            }
        },
    )
