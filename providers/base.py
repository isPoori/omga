"""
The AIProvider abstraction and a base implementation shared by all
providers. The three providers inherit from BaseProvider and only override
id/name/URL/headers/parsing — no provider-specific logic leaks further up.

Each provider talks to an OpenAI-compatible ``/chat/completions`` endpoint
(and ``/models`` when model discovery is supported) streaming SSE.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import requests

from config.store import get, get_api_key
from core.errors import NetworkError, NoApiKeyError, ProviderError
from core.models import ChatEvent, ChatResult, ChunkEvent, DoneEvent, Model, Message
from providers.errors import is_plausible_model_id, raise_for_provider_status
from providers.http import request as http_request
from providers.protocol import AIProvider
from providers.transport import TransportResponse


class BaseProvider(AIProvider):
    """Shared OpenAI-compatible streaming implementation."""

    # ── Provider metadata (overridden by subclasses) ─────────────────────────
    id: str = "base"
    name: str = "Base"
    default_base_url: str = "https://example.com/api/v1"
    docs_url: str = ""
    env_key: str = ""
    supports_streaming: bool = True
    supports_model_discovery: bool = True
    requires_base_url: bool = False

    def info(self):
        from core.models import ProviderInfo

        return ProviderInfo(
            id=self.id,
            name=self.name,
            default_base_url=self.default_base_url,
            docs_url=self.docs_url,
            env_key=self.env_key,
            supports_model_discovery=self.supports_model_discovery,
            requires_base_url=self.requires_base_url,
        )

    # ── Configuration ─────────────────────────────────────────────────────────

    def base_url(self) -> str:
        import os

        env = f"OMGA_{self.id.upper().replace('-', '_')}_BASE_URL"
        override = os.environ.get(env)
        if override:
            return override.rstrip("/")
        configured = get(f"endpoints.{self.id}", None)
        if configured:
            return str(configured).rstrip("/")
        return self.default_base_url.rstrip("/")

    def _api_key(self) -> str:
        key = get_api_key(self.id)
        if not key:
            env = f"{self.env_key}"
            raise NoApiKeyError(
                f"No API key configured for {self.name}.",
                hint=(
                    f"Run `omga init` (or set the {env} environment "
                    "variable) to provide a key."
                ),
            )
        return key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    # ── HTTP plumbing ────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict[str, Any], *, stream: bool) -> TransportResponse:
        import time as _time

        url = self.base_url() + path
        timeout = float(get("system.timeout_seconds", 60) or 60)
        retries = int(get("system.retries", 2) or 0)
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = http_request(
                    "POST",
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=timeout,
                    stream=stream,
                )
                if resp.status_code == 429 and attempt < retries:
                    _time.sleep(delay)
                    delay = min(delay * 2, 16)
                    continue
                return resp
            except requests.exceptions.SSLError as exc:
                raise NetworkError(
                    f"TLS error talking to {self.name}.",
                    hint="Check your network / proxy settings. Try `/proxy`.",
                    debug=str(exc),
                ) from exc
            except requests.exceptions.ProxyError as exc:
                raise NetworkError(
                    f"Proxy blocked the connection to {self.name}.",
                    hint=(
                        "Proxy failed. Use `/proxy off` to disable, "
                        "`/proxy 7890` or `/proxy socks5://127.0.0.1:1080` to set one, "
                        "or `/proxy test` to diagnose."
                    ),
                    debug=str(exc),
                ) from exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                if attempt < retries:
                    _time.sleep(delay)
                    delay = min(delay * 2, 16)
                    continue
                if isinstance(exc, requests.exceptions.Timeout):
                    raise NetworkError(
                        f"Connection to {self.name} timed out.",
                        hint="Retry, raise system.timeout_seconds, or try `/proxy off`.",
                        debug=str(exc),
                    ) from exc
                raise NetworkError(
                    f"Unable to connect to {self.name}.",
                    hint="Check VPN/proxy with `/proxy test`, `/proxy off`, or switch `/provider`.",
                    debug=str(exc),
                ) from exc
            except RuntimeError as exc:
                msg = str(exc)
                raise NetworkError(
                    f"HTTP transport error talking to {self.name}.",
                    hint=(
                        f"{msg}  ·  Try `/proxy off` or `/proxy test`."
                        if "proxy" in msg.lower() or "curl" in msg.lower()
                        else msg
                    ),
                    debug=msg,
                ) from exc
        raise NetworkError(
            f"Unable to connect to {self.name}.",
            hint="Check your network connection, or try `/proxy off`.",
            debug=str(last_exc) if last_exc else "",
        )

    def _raise_for_status(self, resp: TransportResponse | requests.Response) -> None:
        raise_for_provider_status(
            resp,
            provider_name=self.name,
            docs_url=self.docs_url,
        )

    # ── Protocol: credentials ─────────────────────────────────────────────────

    def validate_credentials(self) -> bool:
        """Return True when an API key is configured for this provider."""
        return bool(get_api_key(self.id))

    # ── Protocol: model discovery ─────────────────────────────────────────────

    def list_models(self) -> list[Model]:
        url = self.base_url() + "/models"
        timeout = float(get("system.timeout_seconds", 60) or 60)
        try:
            r = http_request(
                "GET",
                url,
                headers={"Authorization": f"Bearer {self._api_key()}"},
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise NetworkError(
                f"Unable to fetch models from {self.name}.",
                hint="Check network / VPN, or set `/proxy http://127.0.0.1:PORT`.",
                debug=str(exc),
            ) from exc
        self._raise_for_status(r)
        return self._parse_models(r.json())

    def _parse_models(self, data: dict) -> list[Model]:
        from core.names import vendor_label

        items = data.get("data") or data.get("models") or []
        models: list[Model] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            model_id = it.get("id") or it.get("name")
            if not model_id:
                continue
            context = (
                it.get("context_length")
                or it.get("context_window")
                or (it.get("top_provider") or {}).get("context_length")
            )
            caps: list[str] = []
            arch = it.get("architecture") or {}
            modality = str(arch.get("modality") or arch.get("input_modalities") or "")
            if "image" in modality.lower() or "vision" in modality.lower():
                caps.append("vision")
            params = it.get("supported_parameters") or []
            if isinstance(params, list) and any(
                p in {"tools", "tool_choice", "functions"} for p in params
            ):
                caps.append("tools")
            if it.get("pricing"):
                caps.append("usage")
            models.append(
                Model(
                    id=str(model_id),
                    name=str(it.get("name") or model_id),
                    provider=self.id,
                    context_window=int(context) if context else None,
                    capabilities=tuple(caps),
                    vendor=vendor_label(str(model_id)),
                    owned_by=str(it.get("owned_by") or ""),
                )
            )
        models.sort(key=lambda m: ((m.vendor_name or "zzz").lower(), m.display.lower()))
        return models

    # ── Protocol: chat (streaming) ────────────────────────────────────────────

    def chat(self, messages: list[Message], **kwargs: Any) -> Iterator[ChatEvent]:
        payload = self._payload(messages, **kwargs)
        resp = self._post("/chat/completions", payload, stream=True)
        self._raise_for_status(resp)
        acc: dict[int, dict[str, str]] = {}
        last_usage: dict[str, Any] = {}
        try:
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                chunk = raw[6:].strip()
                if chunk == "[DONE]":
                    for evt in _flush_tool_calls(acc):
                        yield evt
                    yield DoneEvent(reason="stop", usage=last_usage)
                    return
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                # Mid-stream provider errors (OpenRouter / OpenAI shape)
                if data.get("error"):
                    err = data["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise ProviderError(
                        f"{self.name} stream error: {msg}",
                        hint="Retry, or switch model with `/model`.",
                        debug=str(err)[:400],
                    )
                if data.get("usage"):
                    last_usage = data["usage"]
                choices = data.get("choices") or [{}]
                choice0 = choices[0] if choices else {}
                delta = choice0.get("delta", {}) or {}
                if delta.get("content"):
                    yield ChunkEvent(text=delta["content"])
                if delta.get("reasoning") or delta.get("reasoning_content"):
                    pass
                if delta.get("tool_calls"):
                    _accumulate_tool_delta(acc, delta["tool_calls"])
                finish = choice0.get("finish_reason")
                if finish and finish != "error":
                    for evt in _flush_tool_calls(acc):
                        yield evt
                    yield DoneEvent(reason=finish, usage=last_usage or data.get("usage") or {})
                    return
                if finish == "error":
                    raise ProviderError(
                        f"{self.name} ended the stream with an error.",
                        hint="Retry or pick another model with `/model`.",
                        debug=str(data)[:400],
                    )
            for evt in _flush_tool_calls(acc):
                yield evt
            yield DoneEvent(reason="stop", usage=last_usage)
        except requests.exceptions.RequestException as exc:
            raise NetworkError(
                f"Stream from {self.name} was interrupted.",
                hint="Check your network connection and retry.",
                debug=str(exc),
            ) from exc
        finally:
            resp.close()

    def _tool_call_event(self, tc: dict):
        from core.models import ToolCallEvent

        return ToolCallEvent(
            id=str(tc.get("id", "")),
            name=str(tc.get("function", {}).get("name", "")),
            arguments=_safe_json(tc.get("function", {}).get("arguments", "")),
        )

    def _payload(self, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        model = kwargs.get("model") or self.resolve_model()
        if not is_plausible_model_id(str(model)):
            from core.errors import ModelNotFoundError

            raise ModelNotFoundError(
                f"Configured model id {model!r} is invalid.",
                hint="Pick a real model with `/model` (example: openai/gpt-4o-mini).",
            )
        body: dict[str, Any] = {
            "model": str(model),
            "messages": [m.to_openai() for m in messages],
            "stream": True,
        }
        temp = kwargs.get("temperature", get("system.temperature", None))
        if temp is not None:
            body["temperature"] = float(temp)
        max_tokens = kwargs.get("max_tokens")
        if max_tokens is None:
            max_tokens = get("system.max_tokens", None)
        if max_tokens:
            body["max_tokens"] = int(max_tokens)
        tools = kwargs.get("tools")
        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice", "auto")
        if self._supports_stream_options():
            body["stream_options"] = {"include_usage": True}
        return body

    def _supports_stream_options(self) -> bool:
        """Some OpenAI-compat gateways reject stream_options."""
        return True

    def resolve_model(self) -> str:
        """Return the configured model id for this provider, or a default."""
        provider = get("provider", self.id)
        model = get("model", None)
        if model and provider == self.id and is_plausible_model_id(str(model)):
            return str(model)
        # Fall back: first available model (cached to avoid a network call).
        try:
            models = self.list_models()
            if models:
                return models[0].id
        except Exception:
            pass
        return self._default_model()

    def _default_model(self) -> str:
        raise NotImplementedError

    # ── Non-streaming convenience ─────────────────────────────────────────────

    def complete(self, messages: list[Message], **kwargs: Any) -> ChatResult:
        """Blocking convenience: collect a streaming chat into a result."""
        text: list[str] = []
        calls: list = []
        usage: dict = {}
        for evt in self.chat(messages, **kwargs):
            if isinstance(evt, ChunkEvent):
                text.append(evt.text)
            elif isinstance(evt, (DoneEvent,)) and hasattr(evt, "usage"):
                usage = evt.usage or {}
        result = ChatResult(text="".join(text), usage=usage, provider=self.id)
        return result


def _accumulate_tool_delta(acc: dict[int, dict[str, str]], calls: list) -> None:
    for tc in calls:
        if not isinstance(tc, dict):
            continue
        idx = int(tc.get("index") or 0)
        slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = str(tc["id"])
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] = slot["name"] or str(fn["name"])
        if fn.get("arguments"):
            slot["arguments"] += str(fn["arguments"])


def _flush_tool_calls(acc: dict[int, dict[str, str]]):
    from core.models import ToolCallEvent

    events = []
    for idx in sorted(acc):
        slot = acc[idx]
        if not slot.get("name"):
            continue
        events.append(
            ToolCallEvent(
                id=slot.get("id") or f"call-{idx}",
                name=slot["name"],
                arguments=_safe_json(slot.get("arguments") or ""),
            )
        )
    acc.clear()
    return events


def _safe_json(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
