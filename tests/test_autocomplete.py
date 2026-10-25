from cli.autocomplete import slash_query, suggest_commands


def test_slash_query():
    assert slash_query("/he") == "he"
    assert slash_query("/") == ""
    assert slash_query("/help ") is None
    assert slash_query("hello") is None


def test_suggest_prefix():
    hits = suggest_commands("hel")
    assert any(h.name == "help" for h in hits)
    assert any(h.name == "key" for h in suggest_commands("key"))
    assert any(h.name == "key" for h in suggest_commands("ke"))


def test_suggest_empty_shows_some():
    hits = suggest_commands("")
    assert len(hits) >= 1
    assert all(h.name for h in hits)
