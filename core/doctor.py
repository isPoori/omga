"""
`omga doctor` — diagnostics and optional auto-repair (`--fix`).
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable

from config import store as cfg
from core.errors import NetworkError, OmgaError, ProviderError
from providers import create_provider
from ui.console import OmgaConsole
from ui.theme import get_theme


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    repair: Callable[[], str] | None = field(default=None, repr=False)

    @property
    def status(self) -> str:
        return "PASS" if self.ok else "FAIL"


def _check_python() -> Check:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 10)
    return Check(
        "Python",
        ok,
        detail=f"{platform.python_version()} ({sys.implementation.name})",
        fix="Install Python 3.10+ from https://www.python.org/downloads/",
    )


def _check_encoding() -> Check:
    enc = (sys.stdout.encoding or "").lower()
    utf = "utf" in enc.replace("-", "")
    lang = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    if utf:
        return Check("Encoding", True, detail=enc or "utf-8")
    return Check(
        "Encoding", False,
        detail=f"stdout encoding is {enc or 'unknown'}",
        fix="export LANG=en_US.UTF-8",
        repair=_repair_encoding_hint,
    )


def _repair_encoding_hint() -> str:
    return "Set LANG=en_US.UTF-8 in your shell profile (manual)."


def _check_unicode() -> Check:
    from ui.glyphs import unicode_enabled
    if unicode_enabled():
        return Check("Unicode", True, detail="UTF-8 glyphs enabled")
    return Check(
        "Unicode", False,
        detail="Falling back to ASCII glyphs",
        fix="(warn) export OMGA_UNICODE=1",
    )


def _check_terminal() -> Check:
    ok = sys.stdout.isatty()
    return Check(
        "Terminal", ok,
        detail="Interactive TTY" if ok else "Not a TTY (piped)",
        fix="Run in an interactive terminal for the full TUI.",
    )


def _check_config() -> Check:
    if cfg.has_config():
        return Check(
            "Configuration", True,
            detail=f"{cfg.get('provider')} / {cfg.get('model') or 'auto'} · theme {cfg.get('theme')}",
        )

    def repair() -> str:
        from core.paths import config_dir
        config_dir().mkdir(parents=True, exist_ok=True)
        example = cfg.export_example()
        path = config_dir() / "config.yaml"
        if not path.exists():
            path.write_text(example, encoding="utf-8")
        return f"Wrote starter config at {path}. Run `omga init` to finish."

    return Check(
        "Configuration", False,
        detail="No config yet.",
        fix="Run `omga init` or `omga doctor --fix`.",
        repair=repair,
    )


def _check_apikey() -> Check:
    provider = cfg.get("provider", "openrouter")
    key = cfg.get_api_key(provider)
    if key:
        masked = (key[:4] + "…" + key[-2:]) if len(key) >= 8 else "(set)"
        return Check(f"API key ({provider})", True, detail=masked)
    # Local providers don't need keys.
    if provider in ("ollama", "lmstudio"):
        return Check(f"API key ({provider})", True, detail="local — not required")
    return Check(
        f"API key ({provider})", False,
        detail="No key configured.",
        fix=f"Run `omga init` or set OMGA_{provider.upper()}_API_KEY.",
    )


def _check_network() -> Check:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=4)
    except OSError:
        return Check("Network", False, detail="No outbound connectivity.",
                     fix="Check your network connection.")
    return Check("Network", True, detail="Reachable.")


def _check_provider() -> Check:
    provider = cfg.get("provider", "openrouter")
    try:
        prov = create_provider(provider)
        return Check(f"Provider ({prov.name})", True, detail=prov.base_url())
    except OmgaError as exc:
        return Check("Provider", False, detail=str(exc), fix=exc.hint)


def _check_model_id() -> Check:
    from providers.errors import is_plausible_model_id

    mid = str(cfg.get("model") or "").strip()
    if not mid:
        return Check("Configured model", True, detail="(provider default)")
    if is_plausible_model_id(mid):
        return Check("Configured model", True, detail=mid)

    def repair() -> str:
        fallback = "openrouter/auto"
        try:
            prov = create_provider()
            fallback = prov._default_model()
        except Exception:
            pass
        cfg.set_value("model", fallback)
        return f"Reset invalid model {mid!r} → {fallback}"

    return Check(
        "Configured model", False,
        detail=f"Invalid model id {mid!r}",
        fix="Run `/model` or `omga doctor --fix`.",
        repair=repair,
    )


def _check_models() -> Check:
    provider = cfg.get("provider", "openrouter")
    try:
        prov = create_provider(provider)
        models = prov.list_models()
        return Check("Model availability", True, detail=f"{len(models)} models fetched.")
    except (ProviderError, NetworkError, OmgaError) as exc:
        detail = str(exc)
        hint = getattr(exc, "hint", "") or "Check API key / base URL / VPN."
        if "security policy" in detail.lower() or "blocked" in detail.lower():
            hint = (
                "Cloudflare/WAF block. Run `/proxy test`, `/proxy 7890`, `/proxy off`, or "
                "`socks5://127.0.0.1:1080`, or switch `/provider`."
            )
        return Check("Model availability", False, detail=detail, fix=hint)


def _check_proxy_path() -> Check:
    from providers.http import proxy_status_label
    from providers.transport import curl_available, prefers_curl

    label = proxy_status_label()
    curl = curl_available()
    detail = f"{label} · curl {'yes' if curl else 'NO'}"
    if prefers_curl("https://openrouter.ai/api/v1/models") and not curl:
        return Check(
            "HTTP transport", False, detail=detail,
            fix="Install curl — OMGA uses it to bypass Cloudflare JA3 blocks on OpenRouter.",
        )
    return Check("HTTP transport", True, detail=detail)


def _check_memory() -> Check:
    def repair() -> str:
        from core.paths import memory_dir, state_db
        from memory.store import MemoryStore
        memory_dir()
        MemoryStore(state_db())
        return f"Initialized memory store at {state_db()}"

    try:
        from memory.store import MemoryStore
        from core.paths import memory_dir, state_db
        store = MemoryStore()
        _ = store.list_sessions(limit=1)
        memory_dir()
        return Check("Memory store", True, detail=f"SQLite ready ({state_db().name})")
    except Exception as exc:
        return Check("Memory store", False, detail=str(exc),
                     fix="omga doctor --fix", repair=repair)


def _check_skills() -> Check:
    try:
        from skills.loader import load_skills
        catalog = load_skills()
        return Check("Skills", True, detail=f"{len(catalog.skills)} skill(s) available")
    except Exception as exc:
        return Check("Skills", False, detail=str(exc))


def _check_git() -> Check:
    path = shutil.which("git")
    if path:
        try:
            out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
            return Check("Git", True, detail=out.stdout.strip())
        except Exception:
            return Check("Git", True, detail=path)
    return Check(
        "Git", False, detail="Not installed.",
        fix="Install git (apt/brew/winget).",
        repair=_repair_git,
    )


def _repair_git() -> str:
    system = platform.system().lower()
    cmds = []
    if system == "darwin" and shutil.which("brew"):
        cmds = [["brew", "install", "git"]]
    elif shutil.which("apt-get"):
        cmds = [["sudo", "apt-get", "install", "-y", "git"]]
    elif shutil.which("dnf"):
        cmds = [["sudo", "dnf", "install", "-y", "git"]]
    elif shutil.which("pacman"):
        cmds = [["sudo", "pacman", "-S", "--noconfirm", "git"]]
    elif shutil.which("winget"):
        cmds = [["winget", "install", "-e", "--id", "Git.Git"]]
    if not cmds:
        return "Could not auto-install git — install it manually."
    for cmd in cmds:
        try:
            subprocess.run(cmd, check=True, timeout=300)
            return f"Installed git via {' '.join(cmd)}"
        except Exception as exc:
            return f"git install failed: {exc}"
    return "git install failed"


def _check_ripgrep() -> Check:
    if shutil.which("rg"):
        return Check("ripgrep", True, detail=shutil.which("rg") or "rg")
    return Check(
        "ripgrep", False, detail="Optional — faster search.",
        fix="(warn) Install ripgrep for faster codebase search.",
        repair=_repair_ripgrep,
    )


def _check_browser() -> Check:
    from tools.browser import find_browser

    path = find_browser()
    if path:
        return Check("Browser", True, detail=path)
    return Check(
        "Browser",
        False,
        detail="Optional — Chrome/Chromium for web_search / browse_page.",
        fix="(warn) Install chromium or google-chrome, or set OMGA_BROWSER=/path/to/chrome",
    )


def _repair_ripgrep() -> str:
    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        cmd = ["brew", "install", "ripgrep"]
    elif shutil.which("apt-get"):
        cmd = ["sudo", "apt-get", "install", "-y", "ripgrep"]
    elif shutil.which("pacman"):
        cmd = ["sudo", "pacman", "-S", "--noconfirm", "ripgrep"]
    elif shutil.which("dnf"):
        cmd = ["sudo", "dnf", "install", "-y", "ripgrep"]
    else:
        return "Install ripgrep manually: https://github.com/BurntSushi/ripgrep"
    try:
        subprocess.run(cmd, check=True, timeout=300)
        return f"Installed ripgrep via {' '.join(cmd)}"
    except Exception as exc:
        return f"ripgrep install failed: {exc}"


def _check_deps() -> Check:
    missing = []
    for mod in ("requests", "rich", "yaml", "click"):
        try:
            __import__("yaml" if mod == "yaml" else mod)
        except ImportError:
            missing.append("PyYAML" if mod == "yaml" else mod)
    if not missing:
        return Check("Python deps", True, detail="requests, rich, PyYAML, click")

    def repair() -> str:
        pkgs = ["requests", "rich", "PyYAML", "click"]
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *pkgs]
        try:
            subprocess.run(cmd, check=True, timeout=300)
            return "Installed/updated Python dependencies."
        except Exception as exc:
            return f"pip install failed: {exc}"

    return Check(
        "Python deps", False,
        detail="Missing: " + ", ".join(missing),
        fix="omga doctor --fix   or   pip install -e .",
        repair=repair,
    )


def _check_dirs() -> Check:
    from core.paths import config_dir, log_dir, memory_dir, skills_dir

    def repair() -> str:
        for d in (config_dir, log_dir, memory_dir, skills_dir):
            d()
        return f"Ensured directories under {config_dir()}"

    try:
        config_dir()
        log_dir()
        memory_dir()
        skills_dir()
        return Check("State dirs", True, detail=str(config_dir()))
    except Exception as exc:
        return Check("State dirs", False, detail=str(exc), repair=repair,
                     fix="omga doctor --fix")


def _check_path() -> Check:
    which = shutil.which("omga")
    if which:
        return Check("PATH", True, detail=which)
    local = os.path.expanduser("~/.local/bin/omga")
    if os.path.exists(local):
        return Check(
            "PATH", False,
            detail="omga exists in ~/.local/bin but not on PATH",
            fix="export PATH=\"$HOME/.local/bin:$PATH\"",
            repair=lambda: _repair_path(),
        )
    return Check(
        "PATH", False,
        detail="omga not found on PATH",
        fix="Re-run install.sh or: pip install -e .",
    )


def _repair_path() -> str:
    line = 'export PATH="$HOME/.local/bin:$PATH"'
    added = []
    for rc in (".bashrc", ".zshrc"):
        path = os.path.expanduser(f"~/{rc}")
        try:
            text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            if line not in text:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(f"\n# OMGA\n{line}\n")
                added.append(rc)
        except OSError:
            pass
    if added:
        return f"Appended PATH export to {', '.join(added)}. Restart your shell."
    return "Could not update shell rc — add ~/.local/bin to PATH manually."


def gather_checks() -> list[Check]:
    return [
        _check_python(),
        _check_deps(),
        _check_encoding(),
        _check_unicode(),
        _check_terminal(),
        _check_dirs(),
        _check_config(),
        _check_apikey(),
        _check_network(),
        _check_provider(),
        _check_model_id(),
        _check_proxy_path(),
        _check_models(),
        _check_memory(),
        _check_skills(),
        _check_git(),
        _check_browser(),
        _check_ripgrep(),
        _check_path(),
    ]


def run_doctor(console: OmgaConsole | None = None, *, fix: bool = False) -> int:
    console = console or OmgaConsole(get_theme(cfg.get("theme", "ink")))
    console.plain()
    title = "Diagnostics + repair" if fix else "Diagnostics"
    console.info("Checking your OMGA setup…", title=title)
    console.plain()

    checks = gather_checks()
    failed = 0
    repaired = 0

    for c in checks:
        if c.ok:
            console.console.print(f"  [green]✓[/] {c.name:<22} {c.detail}")
            continue
        # Soft warnings (optional tools) don't count as hard failures when prefixed.
        soft = c.fix.startswith("(warn)") if c.fix else False
        if not soft:
            failed += 1
        mark = "[yellow]![/]" if soft else "[red]✗[/]"
        console.console.print(f"  {mark} {c.name:<22} {c.detail}")
        if c.fix:
            console.console.print(f"      [yellow]→ {c.fix}[/]")
        if fix and c.repair is not None:
            try:
                msg = c.repair()
                repaired += 1
                console.console.print(f"      [green]✓ fixed · {msg}[/]")
            except Exception as exc:
                console.console.print(f"      [red]✗ repair failed · {exc}[/]")

    console.plain()
    if fix and repaired:
        console.info(f"Applied {repaired} repair(s).", title="Repair")
        console.plain()

    if failed == 0:
        console.success("All critical checks passed.", title="Ready")
        return 0
    console.warning(
        f"{failed} check(s) need attention."
        + (" Re-run `omga doctor --fix`." if not fix else ""),
        title="Action required",
    )
    return 1
