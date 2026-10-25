"""
Live web search + page reading for the OMGA agent.

Default path is lightweight HTTP (requests). Chromium/Chrome is used only when
explicitly requested or as a last-resort fallback — launching a full browser for
every search was hanging terminals and thrashing machines.
"""

from __future__ import annotations

import base64
import html as html_lib
import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from core.errors import ToolError

_BROWSER_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "chrome",
    "brave-browser",
    "brave",
    "microsoft-edge",
    "microsoft-edge-stable",
    "msedge",
)

_WIN_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
)

_MAC_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

_MAX_DOM_CHARS = 250_000
_MAX_TEXT_CHARS = 20_000
_DEFAULT_TIMEOUT = 20
_CHROME_TIMEOUT = 18
_BROWSER_LOCK = threading.Lock()
_BROWSER_BUSY = False

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _cfg_mode() -> str:
    """Normalize browser policy: http | allow | chrome.

    - http/off: never spawn Chrome (default)
    - allow/auto: Chrome only if the tool call passes use_browser=true
    - chrome: always try headless Chrome
    """
    try:
        from config.store import get

        mode = str(get("tools.browser.mode", "http") or "http").lower().strip()
    except Exception:
        mode = (os.environ.get("OMGA_BROWSER_MODE") or "http").lower().strip()
    if mode in ("off", "http", "none", "disabled"):
        return "http"
    if mode in ("allow", "auto", "optional"):
        return "allow"
    if mode in ("chrome", "browser", "chromium"):
        return "chrome"
    return "http"


def _chrome_allowed(*, use_browser: bool = False) -> bool:
    """Gate: Chromium must not start just because a web tool was invoked."""
    mode = _cfg_mode()
    if mode == "http":
        return False
    if mode == "chrome":
        return True
    # mode == allow
    return bool(use_browser)


def find_browser() -> str | None:
    """Locate a Chrome/Chromium-family binary (path lookup only — never launches)."""
    env = (os.environ.get("OMGA_BROWSER") or os.environ.get("CHROME_PATH") or "").strip()
    if env and Path(env).exists():
        return env
    for name in _BROWSER_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        for path in _WIN_CANDIDATES:
            if Path(path).exists():
                return path
        local = os.environ.get("LOCALAPPDATA", "")
        for rel in (
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        ):
            candidate = Path(local) / rel
            if candidate.exists():
                return str(candidate)
    else:
        for path in _MAC_CANDIDATES:
            if Path(path).exists():
                return path
    return None


def browser_info(*, resolve_binary: bool = False) -> dict[str, Any]:
    """Status for doctor / diagnostics. Skips binary scan unless asked."""
    mode = _cfg_mode()
    path = find_browser() if resolve_binary or mode != "http" else None
    return {
        "available": bool(path) if path is not None else None,
        "path": path,
        "mode": mode,
        "hint": (
            f"mode={mode} · HTTP-only (Chrome never auto-starts)"
            if mode == "http"
            else (
                f"mode={mode} · Chrome on demand"
                + (f" · {path}" if path else " · binary not found")
            )
        ),
    }


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Hard-kill Chromium and its zygote/renderer children."""
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _chrome_dump_dom(url: str, *, timeout: int = _CHROME_TIMEOUT) -> str:
    """One headless Chromium dump — serialized, hard-killed on timeout."""
    global _BROWSER_BUSY
    browser = find_browser()
    if not browser:
        raise ToolError("No Chrome/Chromium browser found on this system.")

    # Never stack multiple Chromium launches (that was freezing machines).
    if not _BROWSER_LOCK.acquire(timeout=1.5):
        raise ToolError("Browser busy — another page fetch is in progress.")
    if _BROWSER_BUSY:
        _BROWSER_LOCK.release()
        raise ToolError("Browser busy — another page fetch is in progress.")
    _BROWSER_BUSY = True

    root = tempfile.mkdtemp(prefix="omga-chrome-")
    profile = Path(root) / "profile"
    runtime = Path(root) / "run"
    cfg = Path(root) / "config"
    cache = Path(root) / "cache"
    for d in (profile, runtime, cfg, cache):
        d.mkdir(parents=True, exist_ok=True)

    timeout = max(8, min(int(timeout or _CHROME_TIMEOUT), 30))
    cmd = [
        browser,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-translate",
        "--disable-features=TranslateUI,BlinkGenPropertyTrees,AudioServiceOutOfProcess",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-software-rasterizer",
        "--mute-audio",
        "--hide-scrollbars",
        "--single-process",  # fewer child processes; much lighter for dump-dom
        f"--user-data-dir={profile}",
        f"--crash-dumps-dir={Path(root) / 'crashes'}",
        f"--user-agent={_USER_AGENT}",
        "--virtual-time-budget=8000",
        "--timeout=10000",
        "--dump-dom",
        url,
    ]
    if os.environ.get("OMGA_BROWSER_SANDBOX", "").lower() in ("1", "true", "yes"):
        cmd = [c for c in cmd if c != "--no-sandbox"]

    env = {
        **os.environ,
        "HOME": root,
        "XDG_CONFIG_HOME": str(cfg),
        "XDG_CACHE_HOME": str(cache),
        "XDG_RUNTIME_DIR": str(runtime),
        "CHROME_HEADLESS": "1",
    }

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=(os.name != "nt"),
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            raise ToolError(f"Browser timed out loading {url} ({timeout}s)") from None

        dom = (stdout or "").strip()
        if dom and ("<html" in dom.lower() or "<!doctype" in dom.lower() or len(dom) > 200):
            if len(dom) > _MAX_DOM_CHARS:
                dom = dom[:_MAX_DOM_CHARS]
            return dom
        err = (stderr or "").strip()
        raise ToolError(
            f"Browser returned empty DOM for {url} "
            f"(exit {proc.returncode}): {err[:300]}"
        )
    finally:
        if proc is not None and proc.poll() is None:
            _kill_process_tree(proc)
        shutil.rmtree(root, ignore_errors=True)
        _BROWSER_BUSY = False
        try:
            _BROWSER_LOCK.release()
        except RuntimeError:
            pass


def _http_get(url: str, *, timeout: int = _DEFAULT_TIMEOUT) -> str:
    timeout = max(5, min(int(timeout or _DEFAULT_TIMEOUT), 30))
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    text = ""
    try:
        import requests

        resp = requests.get(
            url,
            timeout=timeout,
            headers=headers,
            allow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text or ""
    except ImportError:
        # Stdlib fallback — keeps search usable even outside the OMGA venv.
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(_MAX_DOM_CHARS + 1)
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            raise ToolError(f"HTTP fetch failed for {url}: {exc}") from exc
        except Exception as exc:
            raise ToolError(f"HTTP fetch failed for {url}: {exc}") from exc
    except Exception as exc:
        raise ToolError(f"HTTP fetch failed for {url}: {exc}") from exc
    if len(text) > _MAX_DOM_CHARS:
        text = text[:_MAX_DOM_CHARS]
    return text


def fetch_dom(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    use_browser: bool = False,
) -> dict[str, Any]:
    """Fetch page HTML.

    Default: HTTP only (fast, weak-PC safe). Chromium is spawned **only** when
    policy allows it — ``mode=chrome``, or ``mode=allow`` + ``use_browser=true``.
    Calling web_search/browse_page alone never starts a browser.
    """
    url = _normalize_url(url)
    errors: list[str] = []
    want_chrome = _chrome_allowed(use_browser=use_browser)

    if want_chrome:
        try:
            if not find_browser():
                raise ToolError("Chrome/Chromium binary not found")
            chrome_timeout = min(int(timeout or _CHROME_TIMEOUT), _CHROME_TIMEOUT)
            dom = _chrome_dump_dom(url, timeout=chrome_timeout)
            return {
                "url": url,
                "engine": "browser",
                "browser": find_browser(),
                "html": dom,
            }
        except Exception as exc:
            errors.append(f"browser: {exc}")
            # Fall through to HTTP — still useful on weak machines / missing binary.

    try:
        dom = _http_get(url, timeout=timeout)
        return {"url": url, "engine": "http", "browser": None, "html": dom}
    except Exception as exc:
        errors.append(f"http: {exc}")
        raise ToolError("Could not fetch page. " + " | ".join(errors)) from exc


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ToolError("url is required")
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError(f"Unsupported URL scheme: {parsed.scheme}")
    return url


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False
        self.links: list[dict[str, str]] = []
        self._base = ""

    def set_base(self, base: str) -> None:
        self._base = base

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "br":
            self._chunks.append("\n")
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
            self._chunks.append("\n")
        if tag == "a":
            href = ad.get("href", "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self.links.append({"href": urljoin(self._base, href), "text": ""})

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg", "template") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self._chunks.append(text + " ")
        if self.links and not self.links[-1]["text"]:
            self.links[-1]["text"] = text[:200]

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_page(html: str, *, base_url: str = "") -> dict[str, Any]:
    parser = _TextExtractor()
    parser.set_base(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    text = parser.text()
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + "\n…[truncated]"
    seen: set[str] = set()
    links: list[dict[str, str]] = []
    for link in parser.links:
        href = link["href"]
        if href in seen:
            continue
        seen.add(href)
        links.append(link)
        if len(links) >= 40:
            break
    return {"title": parser.title, "text": text, "links": links}


def _ddg_url(query: str) -> str:
    return f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"


def _bing_url(query: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(query)}&setlang=en-US"


def _google_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}&hl=en&num=10"


def _unwrap_ddg_redirect(href: str) -> str:
    if "duckduckgo.com/l/?" in href or "duckduckgo.com//l/?" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


def _b64_url(raw: str) -> str:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                out = decoder(padded.encode("ascii", "ignore")).decode("utf-8", "ignore")
                if out.startswith("http"):
                    return out
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _unwrap_redirect(href: str) -> str:
    href = html_lib.unescape(href or "").strip()
    if not href:
        return href
    href = _unwrap_ddg_redirect(href)
    parsed = urlparse(href)
    host = (parsed.netloc or "").lower()
    qs = parse_qs(parsed.query)

    if "bing.com" in host:
        for key in ("u", "r", "url"):
            if key not in qs:
                continue
            raw = unquote(qs[key][0])
            if raw.startswith("a1"):
                raw = raw[2:]
            decoded = _b64_url(raw)
            if decoded.startswith("http"):
                return decoded
            if raw.startswith("http"):
                return raw

    if "google." in host and parsed.path.startswith("/url"):
        for key in ("q", "url"):
            if key in qs and qs[key][0].startswith("http"):
                return qs[key][0]

    return href


def _parse_ddg_results(html: str, *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for block in re.finditer(
        r'class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?(?:class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>)?',
        html,
        re.I | re.S,
    ):
        href = _unwrap_redirect(block.group(1))
        title = _strip_tags(block.group(2))
        snippet = _strip_tags(block.group(3) or "")
        if not href or not title:
            continue
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break
    return results or _parse_generic_results(html, limit=limit)


def _parse_bing_results(html: str, *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for block in re.finditer(
        r'<li class="b_algo".*?<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?(?:<p[^>]*>(.*?)</p>|<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>)?',
        html,
        re.I | re.S,
    ):
        href = _unwrap_redirect(block.group(1))
        title = _strip_tags(block.group(2))
        snippet = _strip_tags(block.group(3) or block.group(4) or "")
        if href.startswith("http") and title:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break
    return results or _parse_generic_results(html, limit=limit)


def _parse_google_results(html: str, *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for block in re.finditer(
        r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*<h3[^>]*>(.*?)</h3>',
        html,
        re.I | re.S,
    ):
        href = _unwrap_redirect(block.group(1))
        title = _strip_tags(block.group(2))
        if any(x in href for x in ("google.com/", "webcache", "accounts.google")):
            continue
        if href and title:
            results.append({"title": title, "url": href, "snippet": ""})
        if len(results) >= limit:
            break
    return results or _parse_generic_results(html, limit=limit)


def _parse_generic_results(html: str, *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href = _unwrap_redirect(m.group(1))
        title = _strip_tags(m.group(2))
        host = urlparse(href).netloc.lower()
        if not title or len(title) < 3:
            continue
        if any(
            bad in host
            for bad in (
                "duckduckgo.com",
                "bing.com",
                "google.com",
                "microsoft.com",
                "youtube.com/redirect",
            )
        ):
            continue
        if href in seen:
            continue
        seen.add(href)
        results.append({"title": title[:200], "url": href, "snippet": ""})
        if len(results) >= limit:
            break
    return results


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def web_search(
    query: str,
    *,
    engine: str = "bing",
    max_results: int = 8,
    timeout: int = _DEFAULT_TIMEOUT,
    use_browser: bool = False,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ToolError("query is required")
    max_results = max(1, min(int(max_results or 8), 12))
    timeout = max(5, min(int(timeout or _DEFAULT_TIMEOUT), 30))
    use_browser = bool(use_browser)
    engine = (engine or "bing").lower().strip()
    engines = {
        "bing": ("bing", _bing_url, _parse_bing_results),
        "duckduckgo": ("duckduckgo", _ddg_url, _parse_ddg_results),
        "ddg": ("duckduckgo", _ddg_url, _parse_ddg_results),
        "google": ("google", _google_url, _parse_google_results),
    }
    # At most 2 engines via HTTP — never a Chromium storm.
    primary = "duckduckgo" if engine == "ddg" else engine
    if primary not in engines:
        primary = "bing"
    order = [primary]
    for alt in ("bing", "duckduckgo"):
        if alt != primary and alt not in order:
            order.append(alt)
            break

    errors: list[str] = []
    mode = _cfg_mode()

    for key in order:
        label, build_url, parser = engines[key]
        search_url = build_url(query)
        try:
            fetched = fetch_dom(
                search_url, timeout=timeout, use_browser=use_browser
            )
            results = parser(fetched["html"], limit=max_results)
            if not results:
                raise ToolError(f"{label} returned no parseable results")
            return {
                "query": query,
                "engine": label,
                "fetch": fetched["engine"],
                "browser": fetched.get("browser"),
                "mode": mode,
                "use_browser": use_browser,
                "search_url": search_url,
                "count": len(results),
                "results": results,
            }
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue
    raise ToolError("web_search failed. " + " | ".join(errors))


def browse_page(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_chars: int = _MAX_TEXT_CHARS,
    use_browser: bool = False,
) -> dict[str, Any]:
    timeout = max(5, min(int(timeout or _DEFAULT_TIMEOUT), 30))
    use_browser = bool(use_browser)
    mode = _cfg_mode()
    fetched = fetch_dom(url, timeout=timeout, use_browser=use_browser)
    extracted = extract_page(fetched["html"], base_url=fetched["url"])
    text = extracted["text"]
    max_chars = max(500, min(int(max_chars or _MAX_TEXT_CHARS), _MAX_TEXT_CHARS))
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n…[truncated]"
    return {
        "url": fetched["url"],
        "title": extracted["title"],
        "fetch": fetched["engine"],
        "browser": fetched.get("browser"),
        "mode": mode,
        "use_browser": use_browser,
        "text": text,
        "truncated": truncated,
        "links": extracted["links"][:20],
    }


def browser_tools() -> list["Tool"]:
    from tools.base import Tool

    def search_handler(
        query: str,
        engine: str = "bing",
        max_results: int = 8,
        timeout: int = _DEFAULT_TIMEOUT,
        use_browser: bool = False,
    ) -> dict[str, Any]:
        return web_search(
            query,
            engine=engine,
            max_results=max_results,
            timeout=timeout,
            use_browser=use_browser,
        )

    def browse_handler(
        url: str,
        timeout: int = _DEFAULT_TIMEOUT,
        max_chars: int = _MAX_TEXT_CHARS,
        use_browser: bool = False,
    ) -> dict[str, Any]:
        return browse_page(
            url, timeout=timeout, max_chars=max_chars, use_browser=use_browser
        )

    return [
        Tool(
            "web_search",
            "Fast live web search over HTTP (no browser process). "
            "Use one precise query for docs/errors. "
            "Set use_browser=true only if the site needs JS and policy allows it "
            "(tools.browser.mode=allow|chrome). Do not call in parallel.",
            search_handler,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (precise keywords work best).",
                        },
                        "engine": {
                            "type": "string",
                            "enum": ["bing", "duckduckgo", "google"],
                            "description": "Search engine (default bing).",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results 1–12 (default 8).",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Seconds to wait (default 20, max 30).",
                        },
                        "use_browser": {
                            "type": "boolean",
                            "description": (
                                "If true AND tools.browser.mode is allow/chrome, "
                                "render with headless Chromium. Default false — "
                                "never starts Chrome just because this tool ran."
                            ),
                        },
                    },
                    "required": ["query"],
                }
            },
        ),
        Tool(
            "browse_page",
            "Fetch a URL via HTTP and return cleaned text + links (fast). "
            "use_browser=true only when JS rendering is required and policy allows. "
            "Use after web_search on one hit — not in parallel.",
            browse_handler,
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "http(s) URL to open.",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Seconds to wait (default 20, max 30).",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Max characters of extracted text to return.",
                        },
                        "use_browser": {
                            "type": "boolean",
                            "description": (
                                "If true AND tools.browser.mode is allow/chrome, "
                                "use headless Chromium. Default false."
                            ),
                        },
                    },
                    "required": ["url"],
                }
            },
        ),
    ]
