"""Generic OpenAI-compatible provider — base for most backends."""

from __future__ import annotations

from providers.base import BaseProvider


class CompatProvider(BaseProvider):
    """Subclass and set metadata; inherits streaming chat/completions."""

    id: str = "compat"
    name: str = "Compatible"
    default_base_url: str = "https://api.openai.com/v1"
    docs_url: str = ""
    env_key: str = "OMGA_API_KEY"
    supports_model_discovery: bool = True
    requires_base_url: bool = False
    default_model: str = "gpt-4o-mini"

    def _default_model(self) -> str:
        return self.default_model
