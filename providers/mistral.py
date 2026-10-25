from __future__ import annotations

from providers.compat import CompatProvider


class MistralProvider(CompatProvider):
    id = "mistral"
    name = "Mistral"
    default_base_url = "https://api.mistral.ai/v1"
    docs_url = "https://console.mistral.ai/"
    env_key = "MISTRAL_API_KEY"
    default_model = "mistral-small-latest"
