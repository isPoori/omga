from __future__ import annotations

from providers.compat import CompatProvider


class DeepSeekProvider(CompatProvider):
    id = "deepseek"
    name = "DeepSeek"
    default_base_url = "https://api.deepseek.com/v1"
    docs_url = "https://platform.deepseek.com/"
    env_key = "DEEPSEEK_API_KEY"
    default_model = "deepseek-chat"
