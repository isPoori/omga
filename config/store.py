"""
Configuration persistence for OMGA.

Precedence (highest → lowest):
    CLI arguments
    Environment variables     (OMGA_*)
    User configuration        (~/.config/omga/config.yaml|json)
    Default configuration

Secrets live in secrets.json only (chmod 600) — never in config.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from core.paths import config_dir, config_file, secrets_file

DEFAULT_THEME = "ink"

KNOWN_PROVIDERS = (
    "openrouter", "openai", "anthropic", "groq", "deepseek", "ollama",
    "together", "mistral", "fireworks", "gemini", "lmstudio",
    "omnirouter", "9router",
)

# Standard env keys per provider (in addition to OMGA_<ID>_API_KEY).
_PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "ollama": ("OLLAMA_API_KEY",),
    "lmstudio": ("LMSTUDIO_API_KEY",),
}

_ENV_PREFIX = "OMGA_"

DEFAULTS: dict[str, Any] = {
    "schema_version": 3,
    "provider": "openrouter",
    "model": None,
    "theme": DEFAULT_THEME,
    "mode": "agent",
    "safe_mode": False,
    "recent_models": [],
    "favorite_models": [],
    "model_aliases": {},
    "endpoints": {},
    "trusted_workspaces": [],
    "network": {
        # Proxy: null = use HTTPS_PROXY env; "http://127.0.0.1:7890";
        # "__direct__" = force no proxy. Shorthand in TUI: /proxy 7890
        "https_proxy": None,
        # auto | curl | requests — OpenRouter prefers curl (Cloudflare JA3).
        "http_transport": "auto",
    },
    "interface": {
        "compact": False,
        "animations": True,
        "status_bar": True,
        "timestamps": False,
        "line_numbers": True,
        "unicode": "auto",
        "prompt_history": True,
        "alternate_screen": True,
        "show_tool_args": True,
    },
    "agent": {
        "max_iterations": 60,
        "command_timeout": 120,
        "confirm_destructive": True,
        "auto_approve": False,
        "compress_context": True,
        "persist_sessions": True,
        "enable_memory": True,
        "enable_skills": True,
        "enable_delegate": True,
        "subagent_max_iterations": 25,
        "system_access": True,
    },
    "memory": {
        "inject_profile": True,
        "max_recall": 8,
    },
    "security": {
        "redact_secrets": True,
        "confirm_destructive": True,
    },
    "system": {
        "temperature": 0.3,
        "max_tokens": 8192,
        "timeout_seconds": 90,
        "confirm_destructive": True,
        "cache_responses": True,
        "debug": False,
        "retries": 2,
    },
}


def _deep_merge(base: dict, override: Mapping[str, Any]) -> dict:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, Mapping):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _config_yaml() -> Path:
    return config_dir() / "config.yaml"


def _read_json(path, default: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _read_yaml(path: Path) -> dict:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path, data: dict, *, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def _write_yaml(path: Path, data: dict) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load() -> dict[str, Any]:
    """Return the fully-merged user configuration (no secrets)."""
    disk: dict = {}
    yml = _config_yaml()
    if yml.exists():
        disk = _read_yaml(yml)
    elif config_file().exists():
        disk = _read_json(config_file(), {})
    if disk and int(disk.get("schema_version") or 1) < 3:
        disk = _migrate(disk)
    return _deep_merge(DEFAULTS, disk)


def _migrate(disk: dict) -> dict:
    disk = dict(disk)
    disk["schema_version"] = 3
    if "theme" in disk and disk["theme"] == "dark":
        # Keep user's dark theme; ink is the new default for fresh installs only.
        pass
    try:
        save_config(disk)
    except OSError:
        pass
    return disk


def save_config(data: dict[str, Any]) -> None:
    """Persist full config preferring YAML."""
    # Strip secrets if somehow present.
    clean = {k: v for k, v in data.items() if k not in ("api_key", "secrets")}
    try:
        _write_yaml(_config_yaml(), clean)
        # Keep json mirror for older tools.
        _write_json(config_file(), clean)
    except Exception:
        _write_json(config_file(), clean)


def has_config() -> bool:
    return _config_yaml().exists() or config_file().exists()


def get(key_path: str, default: Any = None) -> Any:
    env = _env_for(key_path)
    if env is not None:
        return env
    cfg = load()
    for part in key_path.split("."):
        if not isinstance(cfg, dict) or part not in cfg:
            return default
        cfg = cfg[part]
    return cfg


def set_value(key_path: str, value: Any) -> None:
    cfg = load()
    parts = key_path.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    save_config(cfg)


def reset_config() -> None:
    for path in (_config_yaml(), config_file()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _env_for(key_path: str) -> Any | None:
    name = _ENV_PREFIX + key_path.upper().replace(".", "_")
    if name in os.environ:
        return os.environ[name]
    return None


def env_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def _secrets() -> dict[str, str]:
    return _read_json(secrets_file(), {})


def _write_secrets(data: dict[str, str]) -> None:
    mode = None
    if os.name == "posix":
        mode = stat.S_IRUSR | stat.S_IWUSR
    _write_json(secrets_file(), data, mode=mode)


def clean_api_key(key: str) -> str:
    """Normalize a pasted key (trim, strip quotes / Bearer prefix)."""
    key = (key or "").strip()
    if not key:
        return ""
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    # Drop accidental whitespace / newlines from multi-line pastes
    key = "".join(key.split())
    return key


def set_api_key(provider: str, key: str) -> None:
    secrets = _secrets()
    cleaned = clean_api_key(key)
    if not cleaned:
        raise ValueError("API key is empty after cleaning.")
    secrets[provider] = cleaned
    _write_secrets(secrets)


def unset_api_key(provider: str) -> None:
    secrets = _secrets()
    if provider in secrets:
        del secrets[provider]
        _write_secrets(secrets)


def get_api_key(provider: str | None = None) -> str | None:
    active = (provider or get("provider", "openrouter")).lower()

    generic = clean_api_key(os.environ.get("OMGA_API_KEY") or "")
    if generic:
        return generic

    per_provider = _ENV_PREFIX + active.upper().replace("-", "_") + "_API_KEY"
    per_value = clean_api_key(os.environ.get(per_provider) or "")
    if per_value:
        return per_value

    for env_name in _PROVIDER_ENV.get(active, ()):
        val = clean_api_key(os.environ.get(env_name) or "")
        if val:
            return val

    secrets = _secrets()
    key = clean_api_key(secrets.get(active) or "")
    return key or None


def is_workspace_trusted(path: str) -> bool:
    from pathlib import Path as P

    resolved = str(P(path).resolve())
    trusted = get("trusted_workspaces", []) or []
    return resolved in trusted


def trust_workspace(path: str) -> None:
    from pathlib import Path as P

    resolved = str(P(path).resolve())
    trusted = list(get("trusted_workspaces", []) or [])
    if resolved not in trusted:
        trusted.append(resolved)
        set_value("trusted_workspaces", trusted)


def export_example() -> str:
    """Return a documented example config.yaml."""
    return """# OMGA configuration (no secrets — keys live in secrets.json)
schema_version: 3
provider: openrouter          # openai | anthropic | groq | deepseek | ollama | …
model: null                   # null = provider default / auto
theme: ink                    # ink | light | nord | minimal | dracula | dark
mode: agent                   # ask | plan | agent | edit | review | think | debug
safe_mode: false

endpoints: {}                 # optional base URL overrides per provider
trusted_workspaces: []

interface:
  unicode: auto
  animations: true
  status_bar: true
  alternate_screen: true

agent:
  max_iterations: 60
  confirm_destructive: true
  auto_approve: false
  enable_memory: true
  enable_skills: true
  enable_delegate: true
  system_access: true         # allow shell / filesystem tools

system:
  temperature: 0.7
  max_tokens: 8192
  timeout_seconds: 90
  retries: 2
"""
