"""Unicode glyphs with ASCII fallbacks — professional terminal chrome."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


def stdout_is_utf8() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    if encoding in ("utf8", "utf8sig"):
        return True
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        val = os.environ.get(var, "").upper()
        if "UTF8" in val.replace("-", "") or "UTF-8" in val:
            return True
    return False


def unicode_enabled() -> bool:
    forced = os.environ.get("OMGA_UNICODE", "").strip().lower()
    if forced in ("0", "off", "false", "ascii", "no"):
        return False
    if forced in ("1", "on", "true", "yes"):
        return True
    cfg = os.environ.get("OMGA_UNICODE_MODE", "").strip().lower()
    if cfg in ("off", "ascii"):
        return False
    return stdout_is_utf8()


@dataclass(frozen=True)
class Glyphs:
    selected: str
    success: str
    error: str
    warning: str
    info: str
    active: str
    bullet: str
    empty: str
    star_on: str
    star_off: str
    prompt: str
    hline: str
    vline: str
    ellipsis: str
    spinner: tuple[str, ...]
    sep: str
    mark: str
    file: str
    edit: str
    search: str
    shell: str
    corner_tl: str
    corner_tr: str
    corner_bl: str
    corner_br: str
    tee_l: str
    tee_r: str
    block: str
    spark: str

    @classmethod
    def detect(cls, enabled: bool | None = None) -> "Glyphs":
        if enabled is None:
            enabled = unicode_enabled()
        if enabled:
            return cls(
                selected="❯",
                success="✓",
                error="✗",
                warning="⚠",
                info="ℹ",
                active="→",
                bullet="·",
                empty="○",
                star_on="★",
                star_off="☆",
                prompt="❯",
                hline="─",
                vline="│",
                ellipsis="…",
                spinner=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
                sep="·",
                mark="◆",
                file="▤",
                edit="✎",
                search="⌕",
                shell="$",
                corner_tl="╭",
                corner_tr="╮",
                corner_bl="╰",
                corner_br="╯",
                tee_l="├",
                tee_r="┤",
                block="█",
                spark="✦",
            )
        return cls(
            selected=">",
            success="+",
            error="x",
            warning="!",
            info="i",
            active=">",
            bullet="*",
            empty="o",
            star_on="*",
            star_off="-",
            prompt=">",
            hline="-",
            vline="|",
            ellipsis="...",
            spinner=("|", "/", "-", "\\"),
            sep=".",
            mark="*",
            file="#",
            edit="~",
            search="?",
            shell="$",
            corner_tl="+",
            corner_tr="+",
            corner_bl="+",
            corner_br="+",
            tee_l="+",
            tee_r="+",
            block="#",
            spark="*",
        )


REPLACEMENT = "\ufffd"


def sanitize(text: str) -> str:
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        if ch == REPLACEMENT:
            continue
        code = ord(ch)
        if ch in ("\n", "\t") or code >= 32:
            out.append(ch)
    return "".join(out)
