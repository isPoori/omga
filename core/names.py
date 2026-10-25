"""Human-friendly model names, vendors and search text."""

from __future__ import annotations

import re

_VENDOR_TITLES = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "google-ai-studio": "Google",
    "meta-llama": "Meta",
    "meta": "Meta",
    "mistralai": "Mistral",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "x-ai": "xAI",
    "xai": "xAI",
    "cohere": "Cohere",
    "amazon": "Amazon",
    "nvidia": "NVIDIA",
    "microsoft": "Microsoft",
    "perplexity": "Perplexity",
    "openrouter": "OpenRouter",
}

_KEEP_UPPER = {
    "gpt", "o1", "o3", "o4", "omni", "vl", "vlm", "moe", "r1",
}


def vendor_from_id(model_id: str) -> str:
    ident = (model_id or "").strip()
    if "/" in ident:
        return ident.split("/", 1)[0].lower()
    return ""


def vendor_label(model_id: str) -> str:
    raw = vendor_from_id(model_id)
    if not raw:
        return ""
    return _VENDOR_TITLES.get(raw, raw.replace("-", " ").title())


def pretty_model_name(model_id: str, name: str | None = None) -> str:
    """Readable label without mangling official names."""
    ident = (model_id or "").strip()
    raw = (name or "").strip()
    if raw:
        # OpenRouter often uses "Anthropic: Claude Sonnet 4.6"
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        if raw and raw.lower() not in {ident.lower(), ident.split("/")[-1].lower()}:
            return re.sub(r"\s+", " ", raw)
    source = ident.split("/")[-1] if "/" in ident else ident
    source = source.replace("_", "-")
    parts: list[str] = []
    for p in source.split("-"):
        if not p:
            continue
        low = p.lower()
        if low in _KEEP_UPPER or re.fullmatch(r"v?\d+(\.\d+)*", low):
            parts.append(p.upper() if low in {"gpt", "o1", "o3", "o4"} else p)
        else:
            parts.append(p.capitalize())
    return " ".join(parts) or ident or "Unknown"


def model_search_blob(model_id: str, name: str = "", extra: str = "") -> str:
    return " ".join(
        x for x in (model_id, name, pretty_model_name(model_id, name),
                    vendor_label(model_id), extra)
        if x
    ).lower()
