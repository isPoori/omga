"""Tool registry wiring."""

from memory.store import MemoryStore
from skills.loader import load_skills
from tools.registry import ToolRegistry


def test_registry_includes_new_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("OMGA_HOME", str(tmp_path / "home"))
    store = MemoryStore(tmp_path / "s.sqlite")
    skills = load_skills()
    reg = ToolRegistry(
        tmp_path,
        store=store,
        skills=skills,
        make_child=lambda p: "ok",
        enable_delegate=True,
    )
    names = set(reg.names())
    for expected in (
        "read_file", "edit_file", "write_file", "search", "run_command",
        "web_search", "browse_page",
        "remember", "recall", "search_sessions", "load_skill", "list_skills",
        "create_skill", "poll_process", "delegate_task",
    ):
        assert expected in names, expected
