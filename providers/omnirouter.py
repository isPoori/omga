"""OmniRouter provider implementation.

OmniRouter is an OpenAI-compatible AI gateway/router. Its exact public
endpoint was not reachable from the build environment, so the default
base URL below is a best-effort placeholder that can be corrected at
runtime via the OMGA_OMNIROUTER_BASE_URL environment variable.
"""

from __future__ import annotations

from providers.base import BaseProvider


class OmniRouterProvider(BaseProvider):
    id = "omnirouter"
    name = "OmniRouter"
    # Best-effort default — override with OMGA_OMNIROUTER_BASE_URL if yours differs.
    default_base_url = "https://omnirouter.ai/api/v1"
    docs_url = "https://omnirouter.ai/docs"
    env_key = "OMGA_OMNIROUTER_API_KEY"
    supports_model_discovery = True
    requires_base_url = True

    def _default_model(self) -> str:
        return "openrouter/auto"
