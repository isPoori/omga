"""
The AIProvider protocol — the contract every provider implementation meets.

Keeping this as a Protocol (rather than forcing inheritance) makes it easy
to add a new provider by implementing the interface directly; the shared
HTTP/SSE logic lives in BaseProvider for those that want it.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable

from core.models import ChatEvent, ChatResult, Message, Model


@runtime_checkable
class AIProvider(Protocol):
    id: str
    name: str
    docs_url: str
    env_key: str
    supports_streaming: bool
    supports_model_discovery: bool

    def info(self) -> Any: ...
    def validate_credentials(self) -> bool: ...
    def list_models(self) -> list[Model]: ...
    def chat(self, messages: list[Message], **kwargs: Any) -> Iterator[ChatEvent]: ...
    def complete(self, messages: list[Message], **kwargs: Any) -> ChatResult: ...
    def resolve_model(self) -> str: ...
