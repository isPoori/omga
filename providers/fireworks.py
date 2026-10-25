from __future__ import annotations

from providers.compat import CompatProvider


class FireworksProvider(CompatProvider):
    id = "fireworks"
    name = "Fireworks"
    default_base_url = "https://api.fireworks.ai/inference/v1"
    docs_url = "https://fireworks.ai/"
    env_key = "FIREWORKS_API_KEY"
    default_model = "accounts/fireworks/models/llama-v3p1-70b-instruct"
