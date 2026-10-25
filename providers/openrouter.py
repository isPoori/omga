"""OpenRouter provider — https://openrouter.ai/docs/api/reference/overview"""

from __future__ import annotations

from providers.base import BaseProvider


class OpenRouterProvider(BaseProvider):
    id = "openrouter"
    name = "OpenRouter"
    default_base_url = "https://openrouter.ai/api/v1"
    docs_url = "https://openrouter.ai/docs/api-reference/authentication"
    env_key = "OPENROUTER_API_KEY"
    supports_model_discovery = True

    def _headers(self) -> dict[str, str]:
        # Auth: Bearer token. Attribution headers per OpenRouter docs
        # (HTTP-Referer + X-OpenRouter-Title; X-Title kept for compatibility).
        headers = super()._headers()
        headers["HTTP-Referer"] = "https://github.com/isPoori/omga"
        headers["X-OpenRouter-Title"] = "OMGA"
        headers["X-Title"] = "OMGA"
        headers["Accept"] = "application/json"
        headers["User-Agent"] = "OMGA/3.2 (+https://github.com/isPoori/omga)"
        return headers

    def _default_model(self) -> str:
        return "openrouter/auto"
