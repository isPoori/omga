"""Parse provider HTTP error bodies into actionable Omga errors.

OpenRouter / Cloudflare / gateways return several shapes:
  {"error": {"message": "...", "code": 401}}
  {"error": {"message": "...", "metadata": {...}}}
  {"error": "Access denied by security policy."}   # WAF / geo block
  {"success": false, "error": "..."}
  {"message": "..."}
"""

from __future__ import annotations

import json
from typing import Any

import requests

from core.errors import (
    ModelNotFoundError,
    NetworkError,
    ProviderAuthError,
    ProviderBlockedError,
    ProviderError,
)


def extract_error_detail(resp: Any) -> tuple[str, dict[str, Any]]:
    """Return (human message, raw payload dict)."""
    text = (getattr(resp, "text", None) or "")[:2000]
    status = getattr(resp, "status_code", "?")
    payload: dict[str, Any] = {}
    try:
        data = resp.json()
        if isinstance(data, dict):
            payload = data
    except Exception:
        # HTML Cloudflare pages
        low = text.lower()
        if "access denied" in low or "just a moment" in low or "cloudflare" in low:
            return (text.strip()[:240] or f"HTTP {status}", {})
        return (text.strip() or f"HTTP {status}", {})

    err = payload.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg") or str(err)
        return (str(msg).strip(), payload)
    if isinstance(err, str) and err.strip():
        return (err.strip(), payload)
    if payload.get("message"):
        return (str(payload["message"]).strip(), payload)
    if payload.get("detail"):
        return (str(payload["detail"]).strip(), payload)
    return (text.strip() or f"HTTP {resp.status_code}", payload)


def _looks_like_waf(message: str) -> bool:
    low = message.lower()
    needles = (
        "access denied by security policy",
        "attention required",
        "cloudflare",
        "just a moment",
        "blocked by",
        "geo",
        "region",
        "not available in your country",
        "forbidden by security",
        "security policy",
    )
    return any(n in low for n in needles)


def _looks_like_bad_key(message: str) -> bool:
    low = message.lower()
    needles = (
        "invalid api key",
        "incorrect api key",
        "invalid credentials",
        "unauthorized",
        "authentication",
        "no auth",
        "missing api key",
        "api key not found",
        "user not found",
        "key revoked",
        "disabled key",
    )
    return any(n in low for n in needles)


def _looks_like_credits(message: str) -> bool:
    low = message.lower()
    return any(
        n in low
        for n in ("credit", "insufficient", "payment", "billing", "balance", "top up", "top-up")
    )


def _looks_like_bad_model(message: str) -> bool:
    low = message.lower()
    return any(
        n in low
        for n in (
            "invalid model",
            "model not found",
            "no endpoints found",
            "is not a valid model",
            "unknown model",
            "does not exist",
        )
    )


def raise_for_provider_status(
    resp: Any,
    *,
    provider_name: str,
    docs_url: str = "",
) -> None:
    """Raise the right OmgaError for a failed provider response."""
    if getattr(resp, "ok", False):
        return

    status = int(getattr(resp, "status_code", 0) or 0)
    detail, payload = extract_error_detail(resp)
    docs = docs_url or "provider dashboard"

    # curl/requests failed before any HTTP response (dead proxy, DNS, TLS)
    if status == 0:
        raise NetworkError(
            f"{provider_name} connection failed (HTTP 0 · no response).",
            hint=(
                "No HTTP response — usually a dead proxy or offline network. "
                "Try `/proxy off` to force direct, `/proxy 7890` for Clash/V2Ray, "
                "`/proxy test` to diagnose, or `/provider` to switch. "
                f"Docs: {docs}"
            ),
            debug=detail,
        )

    # Network / WAF / geo / TLS-fingerprint blocks (Cloudflare JSON or HTML).
    if status == 403 and _looks_like_waf(detail):
        raise ProviderBlockedError(
            f"{provider_name} blocked this client (HTTP 403 · security policy).",
            hint=(
                "Cloudflare WAF — often TLS fingerprint or exit IP, not a bad key. "
                "OMGA uses curl for OpenRouter when available. Try: "
                "`/proxy 7890` (or socks5://127.0.0.1:1080), `/proxy off`, "
                "`/proxy test`, or `/provider` → groq / openai / ollama. "
                f"Docs: {docs}"
            ),
            debug=detail,
        )

    if status == 401 or (status == 403 and _looks_like_bad_key(detail)):
        raise ProviderAuthError(
            f"{provider_name} rejected the API key (HTTP {status}).",
            hint=(
                "Update the key: /key  or  Settings → API key. "
                "Paste the raw key only (no Bearer / quotes). "
                f"Docs: {docs}"
            ),
            debug=detail,
        )

    if status == 402 or _looks_like_credits(detail):
        raise ProviderError(
            f"{provider_name}: insufficient credits (HTTP {status}).",
            hint=f"Add credits on the provider dashboard, then retry. Docs: {docs}",
            debug=detail,
        )

    if status == 404 or _looks_like_bad_model(detail):
        raise ModelNotFoundError(
            f"{provider_name}: model unavailable — {detail[:160]}",
            hint=(
                "Open `/model` to pick a live model, or type/paste any id "
                "(`openai/gpt-oss-120b`, `openrouter/auto`, …)."
            ),
            debug=detail,
        )

    if status == 400 and _looks_like_bad_model(detail):
        raise ModelNotFoundError(
            f"{provider_name}: invalid model — {detail[:160]}",
            hint=(
                "Run `/model`, search the list, or paste a full model id. "
                "Single letters like `i` are not valid."
            ),
            debug=detail,
        )

    if status == 403:
        # Permission / moderation / key scope — not always a bad key paste
        raise ProviderError(
            f"{provider_name} forbidden (HTTP 403): {detail[:180]}",
            hint=(
                "Key may lack permission, or the request was moderated. "
                "Check key limits / allowed models, or try `/model` and `/key`. "
                f"Docs: {docs}"
            ),
            debug=json.dumps(payload)[:500] if payload else detail,
        )

    if status == 429:
        raise ProviderError(
            f"{provider_name} rate limit (HTTP 429).",
            hint="Wait a moment and try again.",
            debug=detail,
        )

    if status >= 500:
        raise ProviderError(
            f"{provider_name} upstream error (HTTP {status}): {detail[:160]}",
            hint="The provider or model is down. Retry or pick another model with `/model`.",
            debug=detail,
        )

    raise ProviderError(
        f"{provider_name} error (HTTP {status}): {detail[:180]}",
        hint="Check model, key, and network. `/doctor` can help diagnose.",
        debug=detail,
    )


def is_plausible_model_id(model_id: str) -> bool:
    """Reject accidental single-key / empty model ids before they hit the API."""
    mid = (model_id or "").strip()
    if len(mid) < 3:
        return False
    if mid.lower() in {"null", "none", "undefined", "model", "auto"}:
        # bare "auto" is ambiguous — use openrouter/auto instead
        return False
    # Must be mostly printable model-id charset
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-")
    if any(ch not in allowed for ch in mid):
        return False
    return True
