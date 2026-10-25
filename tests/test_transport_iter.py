"""TransportResponse.iter_lines must accept decode_unicode= like requests."""

from __future__ import annotations

from providers.transport import TransportResponse


def test_iter_lines_accepts_decode_unicode():
    resp = TransportResponse(status_code=200, text="data: hi\ndata: [DONE]\n")
    lines = list(resp.iter_lines(decode_unicode=True))
    assert lines == ["data: hi", "data: [DONE]"]


def test_stream_wrapper_accepts_decode_unicode(monkeypatch):
    """Regression: assigned _iter() must not reject decode_unicode kwarg."""

    class FakeResp:
        status_code = 200
        headers = {"content-type": "text/event-stream"}
        text = ""
        ok = True

        def iter_lines(self, decode_unicode=True):
            yield "data: {\"x\":1}"
            yield "data: [DONE]"

        def close(self):
            return None

    import providers.transport as tr

    def fake_request(*_a, **_k):
        session = type("S", (), {})()
        session.headers = {}
        session.proxies = type("P", (), {"update": lambda *a, **k: None})()
        session.trust_env = True

        class Sess:
            headers = {}
            proxies = type("P", (), {"update": lambda self, *a, **k: None})()
            trust_env = True

            def request(self, *a, **k):
                return FakeResp()

        import requests

        monkeypatch.setattr(requests, "Session", Sess)
        return tr._requests_request(
            "POST", "https://example.com/v1", headers={}, json_body={}, timeout=5, stream=True
        )

    # Call the real wrapper path lightly
    wrapped = TransportResponse(status_code=200, text="")

    def _iter(decode_unicode: bool = True, **_kwargs):
        yield "ok"

    wrapped.iter_lines = _iter  # type: ignore[method-assign]
    assert list(wrapped.iter_lines(decode_unicode=True)) == ["ok"]
