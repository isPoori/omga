from __future__ import annotations

from providers.compat import CompatProvider


class OllamaProvider(CompatProvider):
    id = "ollama"
    name = "Ollama"
    default_base_url = "http://127.0.0.1:11434/v1"
    docs_url = "https://ollama.com/"
    env_key = "OLLAMA_API_KEY"
    default_model = "llama3.2"
    requires_base_url = False

    def _api_key(self) -> str:
        # Ollama ignores the key; accept missing credentials.
        from config.store import get_api_key
        return get_api_key(self.id) or "ollama"

    def validate_credentials(self) -> bool:
        return True
