"""
Normalised data models for OMGA — providers, models, messages and events.

The rest of the application works ONLY with these types; provider-specific
shapes are converted here and never leak outward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from core.names import pretty_model_name, vendor_label


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    provider: str
    context_window: int | None = None
    capabilities: tuple[str, ...] = ()
    vendor: str = ""
    owned_by: str = ""

    @property
    def display(self) -> str:
        return pretty_model_name(self.id, self.name)

    @property
    def vendor_name(self) -> str:
        return self.vendor or vendor_label(self.id) or self.provider


@dataclass
class ToolCall:
    """A completed tool-call request attached to an assistant message."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: str  # 'system' | 'user' | 'assistant' | 'tool'
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None

    def to_openai(self) -> dict[str, Any]:
        """Serialize to an OpenAI-compatible chat message dict."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.role == "assistant" and self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": _json_args(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
            # Some providers reject empty content when tool_calls are present.
            if not self.content:
                msg["content"] = None
        if self.role == "tool":
            if self.tool_call_id:
                msg["tool_call_id"] = self.tool_call_id
            if self.name:
                msg["name"] = self.name
        elif self.name and self.role != "assistant":
            msg["name"] = self.name
        return msg


def _json_args(arguments: dict[str, Any]) -> str:
    import json

    try:
        return json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


# ── Streaming events ───────────────────────────────────────────────────────────

class ChatEvent:
    """Base event yielded by provider streams."""


@dataclass
class ChunkEvent(ChatEvent):
    """A partial assistant text delta."""

    text: str


@dataclass
class ToolCallEvent(ChatEvent):
    """A structured tool-call request from the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class DoneEvent(ChatEvent):
    """End of the stream (with usage metadata when available)."""

    reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)


# ── Response envelope ──────────────────────────────────────────────────────────

@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCallEvent] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str = ""


# ── Provider metadata ──────────────────────────────────────────────────────────

@dataclass
class ProviderInfo:
    id: str
    name: str
    default_base_url: str
    docs_url: str
    env_key: str  # e.g. OPENROUTER_API_KEY
    supports_model_discovery: bool = True
    requires_base_url: bool = False


def models_to_lines(models: Iterable[Model], max_width: int = 90) -> Iterator[str]:
    """Yield human-friendly, space-padded model lines for the model selector."""
    items = list(models)
    if not items:
        return
    width = max(len(m.display) for m in items)
    width = min(width, max_width)
    for m in items:
        cap = ""
        if m.capabilities:
            cap = "  [" + ", ".join(m.capabilities[:3]) + "]"
        yield f"{m.display:<{width}}{cap}"
