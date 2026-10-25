from config.store import clean_api_key


def test_clean_strips_whitespace_and_bearer():
    assert clean_api_key("  sk-abc  ") == "sk-abc"
    assert clean_api_key("Bearer sk-abc") == "sk-abc"
    assert clean_api_key('"sk-abc"') == "sk-abc"
    assert clean_api_key("'sk-abc'") == "sk-abc"
    assert clean_api_key("sk-\nabc def") == "sk-abcdef"
    assert clean_api_key("") == ""
    assert clean_api_key("   ") == ""
