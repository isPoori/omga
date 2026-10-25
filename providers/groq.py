from __future__ import annotations

from providers.compat import CompatProvider


class GroqProvider(CompatProvider):
    id = "groq"
    name = "Groq"
    default_base_url = "https://api.groq.com/openai/v1"
    docs_url = "https://console.groq.com/keys"
    env_key = "GROQ_API_KEY"
    # llama-3.3-70b-versatile retired for free/dev tiers (Aug 2026)
    default_model = "openai/gpt-oss-120b"
