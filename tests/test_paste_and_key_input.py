from ui.keys import Key, decode_sequence
from ui.screens import InputScreen
from ui.widgets import Editor


def test_paste_end_is_not_esc():
    # Regression: ESC[201~ used to cancel InputScreen mid-paste
    assert decode_sequence("\x1b", "[201~").name != "esc"
    assert decode_sequence("\x1b", "[201~").name in ("paste-end", "unknown")


def test_unknown_csi_tilde_not_esc():
    assert decode_sequence("\x1b", "[999~").name != "esc"


def test_single_line_paste_strips_newlines():
    ed = Editor(single_line=True)
    ed.handle(Key("paste", "sk-or-abc\n\n"))
    assert ed.text == "sk-or-abc"
    assert "\n" not in ed.text


def test_single_line_paste_keeps_bearer_space():
    ed = Editor(single_line=True)
    ed.handle(Key("paste", "Bearer sk-or-abc\n"))
    assert ed.text == "Bearer sk-or-abc"


def test_input_screen_secret_uses_single_line():
    screen = InputScreen("Key", "API key", secret=True)
    assert screen.editor.single_line is True
    screen.editor.handle(Key("paste", "Bearer sk-test-key\n"))
    # After paste, value still in editor (not submitted)
    assert "sk-test-key" in screen.editor.text.replace(" ", "")
    action = screen.on_key(Key("enter"))
    assert action.kind == "pop"
    assert action.value == "sk-test-key"


def test_input_screen_ignores_paste_end():
    screen = InputScreen("Key", "API key", secret=True)
    screen.editor.handle(Key("paste", "sk-abc"))
    action = screen.on_key(Key("paste-end"))
    assert action.kind == "redraw"
    assert screen.editor.text == "sk-abc"
