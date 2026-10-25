from __future__ import annotations

from providers.compat import CompatProvider


class LMStudioProvider(CompatProvider):
    id = "lmstudio"
    name = "LM Studio"
    default_base_url = "http://127.0.0.1:1234/v1"
    docs_url = "https://lmstudio.ai/"
    env_key = "LMSTUDIO_API_KEY"
    default_model = "local-model"

    def _api_key(self) -> str:
        from config.store import get_api_key
        return get_api_key(self.id) or "lmstudio"

    def validate_credentials(self) -> bool:
        return True
