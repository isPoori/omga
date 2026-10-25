"""9Router provider implementation.

9Router is an OpenAI-compatible AI gateway/router (self-hostable). Its
exact public endpoint was not reachable from the build environment, so
the default base URL below is a best-effort placeholder that can be
corrected at runtime via the OMGA_9ROUTER_BASE_URL environment variable.
"""

from __future__ import annotations

from providers.base import BaseProvider


class NineRouterProvider(BaseProvider):
    id = "9router"
    name = "9Router"
    default_base_url = "https://9router.com/api/v1"
    docs_url = "https://9router.com/docs"
    env_key = "OMGA_9ROUTER_API_KEY"
    supports_model_discovery = True
    requires_base_url = True

    def _default_model(self) -> str:
        return "openrouter/auto"
