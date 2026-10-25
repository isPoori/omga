from __future__ import annotations

from providers.compat import CompatProvider


class OpenAIProvider(CompatProvider):
    id = "openai"
    name = "OpenAI"
    default_base_url = "https://api.openai.com/v1"
    docs_url = "https://platform.openai.com/api-keys"
    env_key = "OPENAI_API_KEY"
    default_model = "gpt-4o-mini"
