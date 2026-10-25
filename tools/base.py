"""
Tool abstraction for the OMGA coding agent.

A Tool is a named, described operation the agent can invoke (file read,
file write, shell, search, git). The agent presents each tool's schema to
the model, receives tool-call requests, and dispatches to the concrete
implementation. Tools stay decoupled from the provider layer.
"""

from __future__ import annotations

from typing import Any, Callable

from core.errors import OmgaError, ToolError


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
        schema: dict[str, Any],
    ) -> None:
        self.name = name
        self.description = description
        self.handler = handler
        self.schema = {"name": name, "description": description, **schema}

    def run(self, **kwargs: Any) -> Any:
        try:
            return self.handler(**kwargs)
        except OmgaError:
            raise
        except Exception as exc:  # normalise so the agent can report it
            raise ToolError(f"{self.name}: {exc}") from exc

    def to_openai(self) -> dict[str, Any]:
        """Convert the tool to an OpenAI function-calling schema."""
        return {"type": "function", "function": self.schema}
