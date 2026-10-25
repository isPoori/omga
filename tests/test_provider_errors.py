from providers.errors import extract_error_detail, is_plausible_model_id, raise_for_provider_status
from core.errors import ModelNotFoundError, ProviderAuthError, ProviderBlockedError, ProviderError


class _FakeResp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.ok = 200 <= status < 300
        import json
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


def test_plausible_model_id():
    assert not is_plausible_model_id("i")
    assert not is_plausible_model_id("ab")
    assert not is_plausible_model_id("auto")
    assert is_plausible_model_id("openrouter/auto")
    assert is_plausible_model_id("openai/gpt-4o-mini")
    assert is_plausible_model_id("llama3.2")


def test_waf_403_is_blocked_not_auth():
    resp = _FakeResp(403, {"success": False, "error": "Access denied by security policy."})
    try:
        raise_for_provider_status(resp, provider_name="OpenRouter", docs_url="https://x")
        assert False, "expected raise"
    except ProviderBlockedError as exc:
        assert "security" in exc.message.lower() or "blocked" in exc.message.lower()
        assert "/proxy" in (exc.hint or "").lower()


def test_401_is_auth():
    resp = _FakeResp(401, {"error": {"message": "Invalid API key"}})
    try:
        raise_for_provider_status(resp, provider_name="OpenRouter")
        assert False
    except ProviderAuthError:
        pass


def test_bad_model_400():
    resp = _FakeResp(400, {"error": {"message": "Invalid model specified"}})
    try:
        raise_for_provider_status(resp, provider_name="OpenRouter")
        assert False
    except ModelNotFoundError:
        pass


def test_extract_flat_error():
    resp = _FakeResp(403, {"success": False, "error": "Access denied by security policy."})
    msg, payload = extract_error_detail(resp)
    assert "security policy" in msg.lower()
    assert payload.get("success") is False
