"""Provider model-list cache with TTL and per-provider isolation."""

from __future__ import annotations

import json
import time
from typing import Any

from core.models import Model
from core.paths import config_dir

TTL_SECONDS = 60 * 60  # 1 hour


def _path():
    return config_dir() / "models-cache.json"


def _load() -> dict[str, Any]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_cached_models(provider: str) -> list[Model] | None:
    blob = _load().get(provider)
    if not isinstance(blob, dict):
        return None
    ts = float(blob.get("ts") or 0)
    if time.time() - ts > TTL_SECONDS:
        return None
    items = blob.get("models") or []
    models: list[Model] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        models.append(
            Model(
                id=str(it["id"]),
                name=str(it.get("name") or it["id"]),
                provider=provider,
                context_window=it.get("context_window"),
                capabilities=tuple(it.get("capabilities") or ()),
            )
        )
    return models or None


def store_models(provider: str, models: list[Model]) -> None:
    data = _load()
    data[provider] = {
        "ts": time.time(),
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "context_window": m.context_window,
                "capabilities": list(m.capabilities),
            }
            for m in models
        ],
    }
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


def invalidate(provider: str | None = None) -> None:
    if provider is None:
        try:
            _path().unlink()
        except FileNotFoundError:
            pass
        return
    data = _load()
    data.pop(provider, None)
    path = _path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
