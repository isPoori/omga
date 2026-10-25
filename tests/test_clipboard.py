from ui.clipboard import copy_text


def test_copy_empty():
    ok, method = copy_text("   ")
    assert ok is False
    assert method == "empty"


def test_copy_nonempty_returns_bool():
    # May succeed via OSC52 even without a real clipboard daemon
    ok, method = copy_text("hello from omga test")
    assert isinstance(ok, bool)
    assert isinstance(method, str)
