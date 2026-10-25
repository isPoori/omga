"""Prompt editor cursor / hscroll behaviour."""

from ui.keys import Key
from ui.widgets import Editor


def test_visible_segment_tracks_cursor():
    ed = Editor()
    ed.set_text("hello world")
    ed.col = 5  # after "hello"
    visible, cur = ed.visible_segment(20)
    assert "hello" in visible
    assert cur == 5


def test_hscroll_keeps_cursor_in_field():
    ed = Editor()
    ed.set_text("x" * 80)
    ed.col = 80
    visible, cur = ed.visible_segment(20)
    assert len(visible) <= 20
    assert 0 <= cur <= 20


def test_ctrl_n_inserts_newline():
    ed = Editor()
    ed.set_text("ab")
    ed.col = 1
    assert ed.handle(Key("ctrl-n")) is None
    assert ed.lines == ["a", "b"]
    assert ed.row == 1
    assert ed.col == 0


def test_submit_on_enter():
    ed = Editor()
    ed.set_text("hi")
    assert ed.handle(Key("enter")) == "submit"
