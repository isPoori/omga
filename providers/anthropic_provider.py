"""Anthropic via official OpenAI-compatible endpoint.

Docs: https://docs.anthropic.com/en/api/openai-sdk
Base URL: https://api.anthropic.com/v1/  + Bearer / x-api-key
"""

from __future__ import annotations

from typing import Any

from providers.compat import CompatProvider


class AnthropicProvider(CompatProvider):
    id = "anthropic"
    name = "Anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    docs_url = "https://docs.anthropic.com/en/api/openai-sdk"
    env_key = "ANTHROPIC_API_KEY"
    default_model = "claude-sonnet-4-5"
    requires_base_url = False

    def _headers(self) -> dict[str, str]:
        # Anthropic OpenAI-compat accepts Authorization Bearer; also send x-api-key.
        key = self._api_key()
        return {
            "Authorization": f"Bearer {key}",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _payload(self, messages, **kwargs: Any) -> dict[str, Any]:
        body = super()._payload(messages, **kwargs)
        # Claude OpenAI-compat: temperature must be in [0, 1]; values >1 are capped.
        if "temperature" in body:
            body["temperature"] = max(0.0, min(1.0, float(body["temperature"])))
        return body
