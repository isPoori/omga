"""
Command safety layer for the OMGA shell tool.

Potentially destructive commands are flagged and require explicit
approval. The check is token/word aware (not naive substring matching) and
is extensible: add a regex to *DENY* to hard-block, or to *WARN_IF* to
require confirmation.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Iterable

# Preceding tokens that may prefix otherwise-destructive commands (sudo, etc.).
_PREFIX_TOKENS = r"(sudo|doas|pkexec|env)\s+"

# Hard-blocked commands — never allowed, regardless of approval.
DENY_RE = [
    # rm -rf onto filesystem roots / home / mount roots / "." / "$HOME".
    re.compile(
        r"(?:^|[;&|])\s*(?:" + _PREFIX_TOKENS + r")?rm\s+"
        r"(?:-(?:[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*|[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*)\s+)?"
        r"(?:--?[a-zA-Z]+\s+)*"
        r"(?:\*|\*\.\*|/|/\.\b|/tmp|\$\{?HOME\}?|~|\.\s*(?:[;&|]|$)|\$HOME/)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|[;&|])\s*(?:" + _PREFIX_TOKENS + r")?mkfs(\.\w+)?\s", re.IGNORECASE),
    re.compile(r"(?:^|[;&|])\s*(?:" + _PREFIX_TOKENS + r")?dd\s+.*of=/dev/\w+", re.IGNORECASE),
    re.compile(r"(?:^|[;&|])\s*(?:" + _PREFIX_TOKENS + r")?(shutdown|reboot|poweroff)\b", re.IGNORECASE),
]

# Commands requiring explicit confirmation before running.
WARN_COMMANDS = {
    "rm", "rmdir", "mv", "kill", "pkill", "chmod", "chown",
    "dd", "mkfs", "mkfs.ext4", "format", "git-reset", "git-clean",
}

# Sub-command patterns that are destructive even when the base is benign.
WARN_PATTERNS = [
    re.compile(r"git\s+reset\s+--hard", re.IGNORECASE),
    re.compile(r"git\s+clean", re.IGNORECASE),
    re.compile(r"git\s+push\s+.*--force", re.IGNORECASE),
    re.compile(r"drop\s+database", re.IGNORECASE),
]


@dataclass
class SafetyResult:
    allowed: bool
    reason: str = ""
    requires_confirmation: bool = False


def _tokens(command: str, first: bool = False, rest: bool = False):
    try:
        toks = shlex.split(command)
    except ValueError:
        return []
    if first:
        return [toks[0]] if toks else []
    if rest:
        return toks
    return toks


def _base_command(command: str) -> str | None:
    toks = _tokens(command, first=True)
    if not toks:
        return None
    base = toks[0].lower()
    return base


def assess(command: str) -> SafetyResult:
    """Classify *command*: allowed, blocked, or needing confirmation."""
    for pat in DENY_RE:
        if pat.search(command):
            return SafetyResult(
                allowed=False,
                reason="This command is blocked by OMGA's safety layer "
                       "(too dangerous to run automatically).",
            )
    for pat in WARN_PATTERNS:
        if pat.search(command):
            return SafetyResult(
                allowed=True,
                reason=(
                    f"'{command}' may be destructive and is flagged for approval."
                ),
                requires_confirmation=True,
            )
    base = _base_command(command)
    # git reset --hard may be given as `git` with sub; patterns above cover it.
    if base in WARN_COMMANDS:
        return SafetyResult(
            allowed=True,
            reason=f"'{base}' may be destructive; confirmation required.",
            requires_confirmation=True,
        )
    return SafetyResult(allowed=True)
