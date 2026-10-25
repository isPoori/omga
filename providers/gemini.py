"""Google Gemini via OpenAI-compatible endpoint.

Docs: https://ai.google.dev/gemini-api/docs/openai
"""

from __future__ import annotations

from providers.compat import CompatProvider


class GeminiProvider(CompatProvider):
    id = "gemini"
    name = "Google Gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    docs_url = "https://ai.google.dev/gemini-api/docs/openai"
    env_key = "GOOGLE_API_KEY"
    default_model = "gemini-2.5-flash"
