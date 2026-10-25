"""Terminal clipboard helpers (OSC 52) for yanking chat text."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys


def copy_text(text: str) -> tuple[bool, str]:
    """Copy *text* to the system clipboard.

    Prefer OSC 52 (works over SSH / alt-screen when the terminal allows it),
    then fall back to wl-copy / xclip / pbcopy.
    Returns (ok, method_label).
    """
    text = text or ""
    if not text.strip():
        return False, "empty"

    if _osc52(text):
        return True, "terminal"

    for cmd, label in (
        (["wl-copy"], "wl-copy"),
        (["xclip", "-selection", "clipboard"], "xclip"),
        (["xsel", "--clipboard", "--input"], "xsel"),
        (["pbcopy"], "pbcopy"),
        (["clip.exe"], "clip"),  # WSL
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                check=True,
                timeout=3,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, label
        except Exception:
            continue
    return False, "unavailable"


def _osc52(text: str) -> bool:
    """Emit OSC 52 clipboard set. Returns True if we wrote the sequence."""
    if os.environ.get("OMGA_OSC52", "1").strip().lower() in ("0", "off", "false", "no"):
        return False
    try:
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        # Limit payload size — some terminals truncate huge OSC sequences
        if len(payload) > 100_000:
            return False
        seq = f"\x1b]52;c;{payload}\x07"
        # Write directly to the tty when possible so nested redirects still work
        fd = None
        try:
            fd = os.open("/dev/tty", os.O_WRONLY)
            os.write(fd, seq.encode("ascii", errors="ignore"))
            return True
        except Exception:
            sys.stdout.write(seq)
            sys.stdout.flush()
            return True
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
    except Exception:
        return False
