"""Browser discovery + policy gates (no Chromium spawn on default path)."""

from tools import browser as br


def test_find_browser_on_this_system():
    path = br.find_browser()
    info = br.browser_info(resolve_binary=True)
    assert "available" in info
    assert info["available"] is bool(path)


def test_http_mode_never_allows_chrome():
    orig = br._cfg_mode
    br._cfg_mode = lambda: "http"
    try:
        assert br._chrome_allowed(use_browser=False) is False
        assert br._chrome_allowed(use_browser=True) is False
    finally:
        br._cfg_mode = orig


def test_allow_mode_requires_explicit_flag():
    orig = br._cfg_mode
    br._cfg_mode = lambda: "allow"
    try:
        assert br._chrome_allowed(use_browser=False) is False
        assert br._chrome_allowed(use_browser=True) is True
    finally:
        br._cfg_mode = orig


def test_web_search_does_not_spawn_chrome():
    orig_mode = br._cfg_mode
    orig_chrome = br._chrome_dump_dom
    orig_http = br._http_get
    br._cfg_mode = lambda: "http"

    def boom(*_a, **_k):
        raise AssertionError("Chromium must not start on default web_search")

    br._chrome_dump_dom = boom
    br._http_get = lambda url, timeout=20: (
        '<li class="b_algo"><h2><a href="https://example.com/a">Example A</a></h2>'
        "<p>Snippet</p></li>"
    )
    try:
        out = br.web_search("example", max_results=3)
        assert out["fetch"] == "http"
        assert out["browser"] is None
        assert out["count"] >= 1
    finally:
        br._cfg_mode = orig_mode
        br._chrome_dump_dom = orig_chrome
        br._http_get = orig_http


def test_parse_ddg_html():
    html = """
    <html><body>
      <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">
        Example Docs
      </a>
      <a class="result__snippet">Official documentation for Example.</a>
      <a class="result__a" href="https://other.test/page">Other Page</a>
      <a class="result__snippet">Second hit.</a>
    </body></html>
    """
    results = br._parse_ddg_results(html, limit=5)
    assert len(results) >= 1
    assert results[0]["url"] == "https://example.com/docs"
    assert "Example" in results[0]["title"]


def test_extract_page_text_and_links():
    html = """
    <html><head><title>Hello</title>
    <script>evil()</script><style>.x{}</style></head>
    <body>
      <h1>Welcome</h1>
      <p>Body text here.</p>
      <a href="/about">About</a>
    </body></html>
    """
    out = br.extract_page(html, base_url="https://example.com/")
    assert out["title"] == "Hello"
    assert "Welcome" in out["text"]
    assert "evil" not in out["text"]
    assert any(l["href"] == "https://example.com/about" for l in out["links"])


def test_browser_tools_registered_schema():
    tools = br.browser_tools()
    names = {t.name for t in tools}
    assert names == {"web_search", "browse_page"}
    for t in tools:
        schema = t.to_openai()
        assert schema["type"] == "function"
        assert "parameters" in schema["function"]
        props = schema["function"]["parameters"]["properties"]
        assert "use_browser" in props


def test_unwrap_bing_tracking_url():
    raw = (
        "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly93d3cucHl0aG9uLm9yZy8&ntb=1"
    )
    assert br._unwrap_redirect(raw) == "https://www.python.org/"
