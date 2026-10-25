"""
Filesystem locations for OMGA state.

All persistent state lives under one OS-appropriate base directory.
API keys NEVER live in config.json — they live in a dedicated,
mode-restricted secrets file.

Layout (default):
    ~/.config/omga/config.json
    ~/.config/omga/secrets.json          (chmod 600)
    ~/.config/omga/history.txt
    ~/.config/omga/state.sqlite          sessions + memories (FTS5)
    ~/.config/omga/memory/USER.md        durable user profile
    ~/.config/omga/memory/MEMORY.md      curated long-term notes
    ~/.config/omga/skills/               user skills (agentskills.io)
    ~/.config/omga/logs/core.log
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

_APP_DIR_NAME = "omga"


def _base_dir() -> Path:
    """Return the OS-appropriate base directory, creating it on demand."""
    override = os.environ.get("OMGA_HOME")
    if override:
        root = Path(override).expanduser()
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support" / _APP_DIR_NAME
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            root = Path(xdg) / _APP_DIR_NAME
        else:
            root = Path.home() / ".config" / _APP_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_dir() -> Path:
    d = _base_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return config_dir() / "config.json"


def secrets_file() -> Path:
    return config_dir() / "secrets.json"


def history_file() -> Path:
    return config_dir() / "history.txt"


def cache_file() -> Path:
    """Legacy alias — model list cache lives beside state.sqlite."""
    return config_dir() / "cache.sqlite"


def state_db() -> Path:
    return config_dir() / "state.sqlite"


def memory_dir() -> Path:
    d = config_dir() / "memory"
    _mkdir(d)
    return d


def user_profile_file() -> Path:
    return memory_dir() / "USER.md"


def memory_file() -> Path:
    return memory_dir() / "MEMORY.md"


def skills_dir() -> Path:
    d = config_dir() / "skills"
    _mkdir(d)
    return d


def sessions_dir() -> Path:
    d = config_dir() / "sessions"
    _mkdir(d)
    return d


def _mkdir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass



def log_dir() -> Path:
    d = config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return log_dir() / "core.log"


def is_windows() -> bool:
    return sys.platform == "win32"
