"""Curated free / recommended model hints per provider.

Live catalogs from ``/models`` win; these are used to surface a Free /
Recommended group and sensible defaults when a model is retired.
"""

from __future__ import annotations

# Display order matters — first entry is preferred default when available.
FREE_MODELS: dict[str, tuple[str, ...]] = {
    "groq": (
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3-32b",
        "llama-3.3-70b-versatile",  # enterprise-only; kept for search alias
    ),
    "openrouter": (
        "openrouter/auto",
        "openai/gpt-4o-mini",
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemma-3-27b-it:free",
        "qwen/qwen3-4b:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
        "deepseek/deepseek-r1:free",
    ),
    "ollama": (
        "llama3.2",
        "qwen2.5-coder",
        "mistral",
        "codellama",
    ),
    "openai": (
        "gpt-4o-mini",
        "gpt-4.1-mini",
        "o4-mini",
    ),
    "gemini": (
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ),
    "together": (
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    ),
    "fireworks": (
        "accounts/fireworks/models/llama-v3p1-8b-instruct",
    ),
}

# Retired ids → preferred replacement (provider-agnostic + per-provider)
RETIRED_MODELS: dict[str, str] = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "llama3-70b-8192": "openai/gpt-oss-120b",
    "llama3-8b-8192": "openai/gpt-oss-20b",
}


def is_free_id(model_id: str) -> bool:
    mid = (model_id or "").lower()
    if mid.endswith(":free"):
        return True
    if "free" in mid.split("/"):
        return True
    return False


def free_ids_for(provider_id: str) -> tuple[str, ...]:
    return FREE_MODELS.get((provider_id or "").lower(), ())


def preferred_default(provider_id: str, available: list[str] | None = None) -> str:
    hints = free_ids_for(provider_id)
    avail = list(available or [])
    avail_set = set(avail)
    pid = (provider_id or "").lower()
    for hid in hints:
        if hid in RETIRED_MODELS and pid == "groq":
            continue
        if not avail_set or hid in avail_set:
            return hid
    if avail:
        return avail[0]
    return hints[0] if hints else "openrouter/auto"


def resolve_retired(model_id: str, provider_id: str = "") -> str | None:
    mid = (model_id or "").strip()
    if mid in RETIRED_MODELS:
        # On OpenRouter the llama id may still exist under meta-llama/…
        if (provider_id or "").lower() in ("openrouter", "omnirouter", "9router"):
            return None
        return RETIRED_MODELS[mid]
    return None
