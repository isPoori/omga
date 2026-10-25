from providers.proxyutil import DIRECT, normalize_proxy_url, resolve_proxy


def test_normalize_port_shorthand():
    assert normalize_proxy_url("7890") == "http://127.0.0.1:7890"
    assert normalize_proxy_url(":2080") == "http://127.0.0.1:2080"
    assert normalize_proxy_url("127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_normalize_socks_dns():
    assert normalize_proxy_url("socks5://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"


def test_normalize_clear_and_direct():
    assert normalize_proxy_url("clear") is None
    assert normalize_proxy_url("env") is None
    assert normalize_proxy_url("direct") == DIRECT
    assert normalize_proxy_url("off") == DIRECT
    assert normalize_proxy_url("none") == DIRECT
    assert normalize_proxy_url("disable") == DIRECT


def test_empty_config_uses_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.delenv("OMGA_HTTPS_PROXY", raising=False)
    monkeypatch.setattr(
        "config.store.get",
        lambda key, default=None: "" if key == "network.https_proxy" else default,
    )
    # Empty string in config now falls through to env (not force-direct)
    assert resolve_proxy() == "http://127.0.0.1:9999"


def test_direct_sentinel_ignores_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.delenv("OMGA_HTTPS_PROXY", raising=False)
    monkeypatch.setattr(
        "config.store.get",
        lambda key, default=None: DIRECT if key == "network.https_proxy" else default,
    )
    assert resolve_proxy() == DIRECT
