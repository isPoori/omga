from __future__ import annotations

from providers.compat import CompatProvider


class TogetherProvider(CompatProvider):
    id = "together"
    name = "Together AI"
    default_base_url = "https://api.together.xyz/v1"
    docs_url = "https://api.together.xyz/"
    env_key = "TOGETHER_API_KEY"
    default_model = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
