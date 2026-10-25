"""HTTP transports for providers.

OpenRouter sits behind Cloudflare bot management. Python ``requests`` /
urllib3 present a TLS fingerprint (JA3) that Cloudflare often blocks with:

    {"success": false, "error": "Access denied by security policy."}

``curl`` (and browsers) use a different fingerprint and usually pass.
This module prefers curl for Cloudflare-fronted hosts, with a requests
fallback. Streaming uses ``curl -N`` and yields SSE lines.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urlparse

from providers.proxyutil import DIRECT, curl_proxy_args, proxy_mapping, resolve_proxy

_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)


def _curl_subprocess_env() -> dict[str, str]:
    """Build env for curl: when forcing direct, strip proxy vars so curl obeys."""
    env = os.environ.copy()
    proxy = resolve_proxy()
    if proxy == DIRECT:
        for key in _PROXY_ENV_KEYS:
            env.pop(key, None)
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
    return env


# Hosts known to sit behind aggressive Cloudflare bot checks
_CURL_PREFERRED_HOSTS = frozenset({
    "openrouter.ai",
    "www.openrouter.ai",
})


@dataclass
class TransportResponse:
    """Minimal response object compatible with our provider code."""

    status_code: int
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    url: str = ""
    _stream_proc: subprocess.Popen | None = None
    _stream_tmp: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return json.loads(self.text or "{}")

    def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]:
        if self._stream_proc is None:
            for line in (self.text or "").splitlines():
                yield line
            return
        assert self._stream_proc.stdout is not None
        try:
            for raw in self._stream_proc.stdout:
                if isinstance(raw, bytes):
                    yield raw.decode("utf-8", errors="replace").rstrip("\r\n")
                else:
                    yield raw.rstrip("\r\n")
        finally:
            self.close()

    def close(self) -> None:
        if self._stream_proc is not None:
            try:
                if self._stream_proc.poll() is None:
                    self._stream_proc.kill()
                self._stream_proc.wait(timeout=2)
            except Exception:
                pass
            self._stream_proc = None
        tmp = self._stream_tmp
        self._stream_tmp = None
        if tmp is None:
            return
        items = tmp if isinstance(tmp, tuple) else (tmp,)
        for item in items:
            try:
                item.close()
            except Exception:
                pass


def prefers_curl(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in _CURL_PREFERRED_HOSTS:
        return True
    # Also when config asks for curl transport globally
    try:
        from config.store import get
        mode = str(get("network.http_transport", "auto") or "auto").lower()
        return mode == "curl"
    except Exception:
        return False


def curl_available() -> bool:
    return bool(shutil.which("curl"))


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    timeout: float = 60,
    stream: bool = False,
) -> TransportResponse:
    """Dispatch to curl (preferred for OpenRouter) or requests."""
    use_curl = prefers_curl(url) and curl_available()
    # Allow forcing requests
    try:
        from config.store import get
        mode = str(get("network.http_transport", "auto") or "auto").lower()
        if mode == "requests":
            use_curl = False
        elif mode == "curl":
            use_curl = curl_available()
    except Exception:
        pass

    if use_curl:
        try:
            resp = _curl_request(
                method, url, headers=headers or {}, json_body=json_body,
                timeout=timeout, stream=stream,
            )
            # HTTP 0 = no response — fall back to requests (stream included)
            if int(getattr(resp, "status_code", 0) or 0) != 0:
                return resp
            try:
                resp.close()
            except Exception:
                pass
        except Exception:
            pass
    return _requests_request(
        method, url, headers=headers or {}, json_body=json_body,
        timeout=timeout, stream=stream,
    )


def _curl_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: Any,
    timeout: float,
    stream: bool,
) -> TransportResponse:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not found")

    cmd = [
        curl,
        "-sS",
        "-X", method.upper(),
        "--http1.1",          # more compatible through some proxies
        "-L",
        "--max-time", str(max(5, int(timeout))),
        "-D", "-",           # headers to stdout before body (non-stream) — handled below
    ]
    cmd.extend(curl_proxy_args())

    # Browser-like UA helps some WAF paths; JA3 is still curl's (good).
    merged = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        **headers,
    }
    for k, v in merged.items():
        if v is None:
            continue
        cmd.extend(["-H", f"{k}: {v}"])

    body_file = None
    if json_body is not None:
        body_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=True)
        json.dump(json_body, body_file)
        body_file.flush()
        cmd.extend(["-H", "Content-Type: application/json"])
        cmd.extend(["--data-binary", f"@{body_file.name}"])

    if stream:
        # Stream body only; status via -w after... use -D to temp for headers
        hdr_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=True)
        cmd_stream = [
            curl, "-sS", "-N", "-X", method.upper(), "--http1.1", "-L",
            "--max-time", str(max(30, int(timeout))),
            "-D", hdr_file.name,
            "-o", "-",
        ]
        cmd_stream.extend(curl_proxy_args())
        for k, v in merged.items():
            if v is None:
                continue
            cmd_stream.extend(["-H", f"{k}: {v}"])
        if json_body is not None:
            cmd_stream.extend(["-H", "Content-Type: application/json"])
            cmd_stream.extend(["--data-binary", f"@{body_file.name}"])
        cmd_stream.append(url)

        proc = subprocess.Popen(
            cmd_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_curl_subprocess_env(),
        )
        # Read status from header file after a short wait for headers to flush
        import time
        status = 0
        hdrs: dict[str, str] = {}
        for _ in range(50):
            time.sleep(0.05)
            hdr_file.seek(0)
            raw_hdr = hdr_file.read()
            if raw_hdr:
                status, hdrs = _parse_curl_headers(raw_hdr)
                if status:
                    break
        resp = TransportResponse(
            status_code=status or 0,
            text="",
            headers=hdrs,
            url=url,
            _stream_proc=proc,
            _stream_tmp=body_file,
        )
        # Keep hdr_file referenced so it isn't GC'd until close
        resp._stream_tmp = (body_file, hdr_file)  # type: ignore[assignment]
        if status and status >= 400:
            # Drain error body for message
            err_body, _ = proc.communicate(timeout=timeout)
            resp.text = err_body or ""
            resp._stream_proc = None
            try:
                proc.kill()
            except Exception:
                pass
        return resp

    # Non-streaming: capture headers+body with -w for status
    cmd.extend(["-w", "\n__OMGA_HTTP_STATUS__:%{http_code}"])
    cmd.append(url)
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            env=_curl_subprocess_env(),
        )
    finally:
        if body_file is not None:
            body_file.close()

    out = completed.stdout or ""
    err = (completed.stderr or "").strip()
    status = 0
    body_only = out
    hdrs: dict[str, str] = {}
    if "__OMGA_HTTP_STATUS__:" in out:
        body, _, status_part = out.rpartition("__OMGA_HTTP_STATUS__:")
        try:
            status = int(status_part.strip().split()[0])
        except ValueError:
            status = 0
        # body still starts with HTTP headers because of -D -
        status_from_hdr, hdrs, body_only = _split_headers_body(body)
        if status_from_hdr:
            status = status or status_from_hdr
    else:
        status_from_hdr, hdrs, body_only = _split_headers_body(out)
        status = status_from_hdr

    # curl reports 000 when the TCP/TLS/proxy hop failed entirely
    if status == 0 or completed.returncode != 0:
        detail = err or body_only.strip() or f"curl exit {completed.returncode}"
        # Prefer raising so callers get NetworkError, not opaque HTTP 0
        if completed.returncode != 0 or not (body_only or "").strip():
            raise RuntimeError(detail[:300])

    return TransportResponse(
        status_code=status,
        text=body_only,
        headers=hdrs,
        url=url,
    )


def _parse_curl_headers(raw: str) -> tuple[int, dict[str, str]]:
    status = 0
    hdrs: dict[str, str] = {}
    for block in raw.split("\r\n\r\n"):
        lines = [ln for ln in block.replace("\r\n", "\n").split("\n") if ln]
        if not lines:
            continue
        if lines[0].upper().startswith("HTTP/"):
            parts = lines[0].split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
            for ln in lines[1:]:
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    hdrs[k.strip().lower()] = v.strip()
    return status, hdrs


def _split_headers_body(raw: str) -> tuple[int, dict[str, str], str]:
    # curl -D - prints headers then body on stdout
    if "\r\n\r\n" in raw:
        header_part, _, body = raw.partition("\r\n\r\n")
    elif "\n\n" in raw:
        header_part, _, body = raw.partition("\n\n")
    else:
        return 0, {}, raw
    # May be multiple header blocks on redirects — take the last status
    status, hdrs = _parse_curl_headers(header_part)
    # If more header blocks embedded (redirect), body may still start with HTTP/
    while body.upper().startswith("HTTP/"):
        if "\r\n\r\n" in body:
            hp, _, body = body.partition("\r\n\r\n")
        elif "\n\n" in body:
            hp, _, body = body.partition("\n\n")
        else:
            break
        st, hd = _parse_curl_headers(hp)
        if st:
            status = st
            hdrs = hd
    return status, hdrs, body


def _requests_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: Any,
    timeout: float,
    stream: bool,
) -> TransportResponse:
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": "OMGA/3.2 (+https://github.com/isPoori/omga)",
        "Accept": "application/json",
    })
    proxies = proxy_mapping()
    if proxies is not None:
        session.proxies.update(proxies)
        if proxies == {}:
            session.trust_env = False

    # Soft dependency for socks5h://
    proxy = resolve_proxy()
    if proxy and str(proxy).startswith("socks"):
        try:
            import socks  # noqa: F401  # PySocks
        except ImportError as exc:
            raise RuntimeError(
                "SOCKS proxy requires PySocks. Install with: pip install PySocks"
            ) from exc

    resp = session.request(
        method,
        url,
        headers=headers,
        json=json_body,
        timeout=timeout,
        stream=stream,
    )
    if stream:
        # Wrap so iter_lines works; caller must close
        wrapped = TransportResponse(
            status_code=resp.status_code,
            text="",
            headers={k.lower(): v for k, v in resp.headers.items()},
            url=url,
        )

        def _iter(decode_unicode: bool = True, **_kwargs: Any) -> Iterator[str]:
            # Signature matches TransportResponse.iter_lines / requests.Response
            try:
                for line in resp.iter_lines(decode_unicode=decode_unicode):
                    if line is None:
                        continue
                    if isinstance(line, bytes):
                        yield line.decode("utf-8", errors="replace")
                    else:
                        yield line
            finally:
                resp.close()

        wrapped.iter_lines = _iter  # type: ignore[method-assign]
        wrapped.close = resp.close  # type: ignore[method-assign]
        if not resp.ok:
            # Load error body
            try:
                wrapped.text = resp.text
            except Exception:
                wrapped.text = ""
        return wrapped

    return TransportResponse(
        status_code=resp.status_code,
        text=resp.text,
        headers={k.lower(): v for k, v in resp.headers.items()},
        url=url,
    )


def probe_openrouter() -> dict[str, Any]:
    """Compare curl vs requests against OpenRouter /models (no auth needed)."""
    url = "https://openrouter.ai/api/v1/models"
    result: dict[str, Any] = {
        "proxy": resolve_proxy(),
        "curl_available": curl_available(),
    }
    if curl_available():
        try:
            r = _curl_request("GET", url, headers={}, json_body=None, timeout=25, stream=False)
            result["curl_status"] = r.status_code
            result["curl_body"] = (r.text or "")[:120]
        except Exception as exc:
            result["curl_error"] = str(exc)[:200]
    try:
        r = _requests_request("GET", url, headers={}, json_body=None, timeout=25, stream=False)
        result["requests_status"] = r.status_code
        result["requests_body"] = (r.text or "")[:120]
    except Exception as exc:
        result["requests_error"] = str(exc)[:200]
    return result
