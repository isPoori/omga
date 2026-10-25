"""
Diagnostic logging for OMGA.

Logs go to a rotating file only — never to the terminal (so the TUI never
gets corrupted). Secrets are NEVER written: callers must not pass API keys
into log calls; a small guard redacts common secret patterns defensively.
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler

from core.paths import log_file

_LOGGER_NAME = "omga"

# Redact anything that looks like a bearer secret before it hits the log.
_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9._\-]{8,})"),
    re.compile(r"(api[_-]?key[\"':\s=]+)([A-Za-z0-9._\-]{8,})", re.IGNORECASE),
]


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        for pat in _SECRET_PATTERNS:
            msg = pat.sub("<redacted>", msg)
        record.msg = msg
        record.args = ()
        return True


logger = logging.getLogger(_LOGGER_NAME)
logger.setLevel(logging.DEBUG)
logger.propagate = False
logger.addFilter(_RedactFilter())

if not logger.handlers:
    try:
        log_file().parent.mkdir(parents=True, exist_ok=True)
        _handler = RotatingFileHandler(
            log_file(), maxBytes=2 * 1024 * 1024, backupCount=3,
            encoding="utf-8",
        )
        _handler.setLevel(logging.DEBUG)
        _handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _handler.addFilter(_RedactFilter())
        logger.addHandler(_handler)
    except OSError:  # pragma: no cover - cannot write logs; run silently.
        logger.addHandler(logging.NullHandler())


def debug(enabled: bool | None = None) -> None:
    """Enable/disable debug logging (console when OMGA_DEBUG is set)."""
    if enabled is None:
        enabled = sys.stdout.isatty() and bool(
            __import__("os").environ.get("OMGA_DEBUG")
        )
    logger.setLevel(logging.DEBUG if enabled else logging.INFO)
