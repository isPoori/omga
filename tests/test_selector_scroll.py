"""Selector viewport must follow the highlight on ↓ / page / wheel."""

from ui.glyphs import Glyphs
from ui.keys import Key
from ui.widgets import Option, Selector


def _opts(n: int = 40) -> list[Option]:
    return [Option(f"Model {i}", f"id-{i}", group="All", meta=f"meta-{i}") for i in range(n)]


def test_down_scrolls_viewport():
    sel = Selector(_opts(), allow_search=True, compact=True)
    sel.set_viewport(5)
    assert sel.offset == 0
    for _ in range(6):
        sel.handle(Key("down"))
    # index 6 with viewport 5 → offset should be 2
    assert sel.index == 6
    assert sel.offset == 2


def test_no_wrap_at_ends():
    sel = Selector(_opts(5), allow_search=False)
    sel.set_viewport(5)
    sel.handle(Key("up"))
    assert sel.index == 0
    for _ in range(20):
        sel.handle(Key("down"))
    assert sel.index == 4


def test_search_filters_and_resets_offset():
    sel = Selector(_opts(), allow_search=True)
    sel.set_viewport(5)
    for _ in range(10):
        sel.handle(Key("down"))
    sel.handle(Key("char", char="3"))
    assert sel.offset == 0
    assert all("3" in o.label or "3" in str(o.value) for o in sel.visible)


def test_lines_keeps_selection_in_window():
    g = Glyphs.detect(True)
    sel = Selector(_opts(), allow_search=True, compact=True)
    for _ in range(15):
        sel.handle(Key("down"))
    rows = sel.lines(80, 6, g)
    # Highlight marker should appear in rendered rows
    text = "\n".join("".join(sp.text for sp in ln.spans) for ln in rows)
    assert "Model 15" in text or sel.visible[sel.index].label in text
