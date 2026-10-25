"""Prompt builder + context files."""

from pathlib import Path

from agent.prompt import build_system_prompt
from context.files import load_context_files


def test_context_files(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Rules\nUse pytest.\n", encoding="utf-8")
    bundle = load_context_files(tmp_path)
    assert bundle.files
    block = bundle.prompt_block()
    assert "AGENTS.md" in block
    assert "pytest" in block


def test_build_system_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OMGA_HOME", str(tmp_path / "home"))
    (tmp_path / "AGENTS.md").write_text("Prefer small diffs.\n", encoding="utf-8")
    text = build_system_prompt(root=tmp_path, mode="agent")
    assert "You are OMGA" in text
    assert "Prefer small diffs" in text
    assert "Pouria Hosseini" in text
    assert "pouriahosseini.ir" in text
