"""Browser discovery + HTML result parsing (no live network required)."""

from tools import browser as br


def test_find_browser_on_this_system():
    # Soft assertion: machine may or may not have Chrome; function must not crash.
    path = br.find_browser()
    info = br.browser_info()
    assert "available" in info
    assert info["available"] is bool(path)


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


def test_unwrap_bing_tracking_url():
    raw = (
        "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly93d3cucHl0aG9uLm9yZy8&ntb=1"
    )
    assert br._unwrap_redirect(raw) == "https://www.python.org/"
