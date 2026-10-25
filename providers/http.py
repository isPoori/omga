"""HTTP entrypoint for providers — curl transport for Cloudflare hosts."""

from __future__ import annotations

from typing import Any

from providers.proxyutil import (
    DIRECT,
    normalize_proxy_url,
    proxy_mapping,
    proxy_status_label,
    resolve_proxy,
)
from providers.transport import TransportResponse, prefers_curl, probe_openrouter, request as transport_request


def invalidate_http_cache() -> None:
    """Kept for call-site compatibility (sessions are no longer aggressively cached)."""
    return None


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: Any = None,
    timeout: float = 60,
    stream: bool = False,
) -> TransportResponse:
    return transport_request(
        method,
        url,
        headers=headers,
        json_body=json,
        timeout=timeout,
        stream=stream,
    )


__all__ = [
    "DIRECT",
    "invalidate_http_cache",
    "normalize_proxy_url",
    "prefers_curl",
    "probe_openrouter",
    "proxy_mapping",
    "proxy_status_label",
    "request",
    "resolve_proxy",
]
