from ui.glyphs import Glyphs
from ui.keys import Key
from ui.screens import HelpScreen, MessageScreen
from ui.theme import get_theme


def test_message_screen_scrolls_long_body():
    lines = [f"line-{i}" for i in range(60)]
    screen = MessageScreen("Commands", lines)
    theme = get_theme("ink")
    glyphs = Glyphs.detect(True)

    frame = screen.render(80, 20, theme, glyphs)
    assert frame.lines
    assert screen._max_off > 0

    before = screen.offset
    screen.on_key(Key("down"))
    assert screen.offset == before + 1

    screen.on_key(Key("page-down"))
    assert screen.offset > before + 1

    screen.on_key(Key("end"))
    assert screen.offset == screen._max_off

    screen.on_key(Key("home"))
    assert screen.offset == 0

    # j/k vim-style
    screen.on_key(Key("char", "j"))
    assert screen.offset == 1
    screen.on_key(Key("char", "k"))
    assert screen.offset == 0


def test_help_screen_delegates_scroll():
    screen = HelpScreen("session")
    theme = get_theme("ink")
    glyphs = Glyphs.detect(True)
    screen.render(80, 18, theme, glyphs)
    assert screen._inner._max_off >= 0
    screen.on_key(Key("down"))
    # either scrolled or content fit; must not crash
    screen.render(80, 18, theme, glyphs)
