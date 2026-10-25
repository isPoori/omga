"""Normalize and resolve outbound proxy URLs for providers."""

from __future__ import annotations

import os
import re
from typing import Any

DIRECT = "__direct__"
# clear/env → fall back to process env; off/direct → force no proxy at all
_CLEAR = frozenset({"clear", "env", "auto", "default", "-"})
_DIRECT_WORDS = frozenset({
    "off", "none", "direct", "direct!", "noproxy", "no-proxy",
    "force-direct", "disable", "disabled",
})


def normalize_proxy_url(raw: str | None) -> str | None:
    """Return canonical proxy URL, DIRECT sentinel, or None (use process env).

    Shorthand accepted in the TUI:
      7890                 → http://127.0.0.1:7890
      :2080                → http://127.0.0.1:2080
      127.0.0.1:7890       → http://127.0.0.1:7890
      socks5://host:1080   → socks5h://host:1080  (DNS via proxy)
      clear / env          → None (use HTTPS_PROXY env)
      off / direct         → DIRECT (force no proxy)
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    low = text.lower()
    if low in _CLEAR:
        return None
    if low in _DIRECT_WORDS or text == DIRECT:
        return DIRECT

    if text.isdigit():
        return f"http://127.0.0.1:{text}"
    if re.fullmatch(r":?\d{2,5}", text):
        return f"http://127.0.0.1:{text.lstrip(':')}"
    if "://" not in text and re.fullmatch(r"[\w.-]+:\d{2,5}", text):
        return f"http://{text}"

    if not text.startswith(("http://", "https://", "socks5://", "socks5h://", "socks4://")):
        raise ValueError(
            "Proxy must look like http://127.0.0.1:7890, socks5://127.0.0.1:1080, or just 7890"
        )

    if text.startswith("socks5://"):
        text = "socks5h://" + text[len("socks5://") :]
    return text


def _from_process_env() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return None


def resolve_proxy() -> str | None:
    """Active proxy URL, DIRECT sentinel, or None (no override — use env via requests).

    Precedence:
      1. OMGA_HTTPS_PROXY / OMGA_HTTP_PROXY
      2. config network.https_proxy (URL | DIRECT | null/"" → env)
      3. process HTTPS_PROXY / HTTP_PROXY / ALL_PROXY
    """
    from config.store import get

    for key in ("OMGA_HTTPS_PROXY", "OMGA_HTTP_PROXY"):
        val = (os.environ.get(key) or "").strip()
        if val:
            try:
                norm = normalize_proxy_url(val)
                return DIRECT if norm == DIRECT else (norm or val)
            except ValueError:
                return val

    configured: Any = get("network.https_proxy", None)
    if configured is not None and str(configured).strip() != "":
        raw = str(configured).strip()
        if raw == DIRECT or raw.lower() in _DIRECT_WORDS:
            return DIRECT
        try:
            norm = normalize_proxy_url(raw)
            if norm == DIRECT:
                return DIRECT
            if norm:
                return norm
        except ValueError:
            return raw

    return _from_process_env()


def proxy_mapping() -> dict[str, str] | None:
    """For HTTP clients: URL map, {} to force direct, or None to inherit env."""
    proxy = resolve_proxy()
    if proxy is None:
        return None
    if proxy == DIRECT:
        return {}
    return {"http": proxy, "https": proxy}


def curl_proxy_args() -> list[str]:
    """Args to append to a curl command for the active proxy."""
    proxy = resolve_proxy()
    if proxy is None:
        return []  # curl uses env HTTPS_PROXY itself
    if proxy == DIRECT:
        return ["--noproxy", "*"]
    # socks5h already in URL; curl accepts --proxy
    return ["--proxy", proxy]


def proxy_status_label() -> str:
    from config.store import get

    configured = get("network.https_proxy", None)
    proxy = resolve_proxy()
    if proxy == DIRECT:
        return "direct · forced"
    if proxy:
        src = "config" if configured not in (None, "") else "env"
        return f"{src} · {proxy}"
    return "direct · no proxy detected"
