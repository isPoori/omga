"""Skills loader tests."""

from skills.loader import create_skill, load_skills


def test_bundled_skills_load(tmp_path, monkeypatch):
    monkeypatch.setenv("OMGA_HOME", str(tmp_path / "home"))
    catalog = load_skills()
    names = {s.name for s in catalog.skills}
    assert "systematic-debugging" in names
    assert "test-driven-development" in names
    skill = catalog.by_name("systematic-debugging")
    assert skill is not None
    assert "Reproduce" in skill.body


def test_create_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("OMGA_HOME", str(tmp_path / "home"))
    from core import paths

    dest = tmp_path / "skills"
    monkeypatch.setattr(paths, "skills_dir", lambda: dest)
    skill = create_skill(
        "my-playbook",
        "A test skill",
        "# Steps\n\n1. Do the thing\n",
        tags=["test"],
    )
    assert skill.path.exists()
    assert skill.name == "my-playbook"
