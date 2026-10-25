"""
Agent hooks — the UI-facing event surface for the agent loop.

The agent is UI-agnostic; it reports interesting events (tool start,
tool result, streaming text, requested approvals) through a Hooks object.
The terminal UI implements these to render tool execution, diffs and the
approval flow, keeping the agent decoupled from Rich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Hooks:
    on_stream: Callable[[str], None] | None = None
    on_tool_start: Callable[[str, dict], None] | None = None
    on_tool_result: Callable[[str, Any], None] | None = None
    on_approval: Callable[[str, list[dict]], bool] | None = None
    on_progress: Callable[[str], None] | None = None
    on_final: Callable[[str], None] | None = None
    on_usage: Callable[[dict], None] | None = None
    should_cancel: Callable[[], bool] | None = None

    def stream(self, text: str) -> None:
        if self.on_stream:
            self.on_stream(text)

    def tool_start(self, name: str, args: dict) -> None:
        if self.on_tool_start:
            self.on_tool_start(name, args)

    def tool_result(self, name: str, result: Any) -> None:
        if self.on_tool_result:
            self.on_tool_result(name, result)

    def approve(self, description: str, files: list[dict]) -> bool:
        if self.on_approval:
            return self.on_approval(description, files)
        return True

    def progress(self, message: str) -> None:
        if self.on_progress:
            self.on_progress(message)

    def final(self, text: str) -> None:
        if self.on_final:
            self.on_final(text)

    def usage(self, data: dict) -> None:
        if self.on_usage:
            self.on_usage(data)

    def cancelled(self) -> bool:
        if self.should_cancel:
            return self.should_cancel()
        return False
