"""SQLite memory store tests."""

from memory.store import MemoryStore


def test_session_and_search(tmp_path):
    store = MemoryStore(tmp_path / "state.sqlite")
    sess = store.create_session(cwd="/proj", title="t1", model="m", provider="p")
    store.append_message(sess.id, role="user", content="fix the login bug in auth.py")
    store.append_message(sess.id, role="assistant", content="I patched the token refresh.")
    hits = store.search_messages("login auth", limit=5)
    assert hits
    assert any("login" in h["content"].lower() or "auth" in h["content"].lower() for h in hits)


def test_remember_recall(tmp_path):
    store = MemoryStore(tmp_path / "state.sqlite")
    mid = store.remember("User prefers concise diffs", kind="preference", tags="style", cwd="/p")
    assert mid
    hits = store.search_memories("concise", cwd="/p")
    assert any("concise" in h["content"] for h in hits)
    assert store.forget(mid)
