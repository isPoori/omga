"""
SQLite session + memory store with FTS5 full-text search.

Inspired by Hermes session storage: durable conversations, lineage across
compressions, and searchable recall so the agent grows with the user.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from core.paths import state_db


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    cwd           TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    parent_id     TEXT,
    summary       TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    name       TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    created_at REAL NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS memories (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'note',
    content    TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '',
    cwd        TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'agent',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    importance INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_cwd ON memories(cwd);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
"""

_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    role,
    session_id UNINDEXED,
    content='messages',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    tags,
    kind UNINDEXED,
    content='memories',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content, role, session_id)
  VALUES (new.id, new.content, new.role, new.session_id);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id)
  VALUES ('delete', old.id, old.content, old.role, old.session_id);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id)
  VALUES ('delete', old.id, old.content, old.role, old.session_id);
  INSERT INTO messages_fts(rowid, content, role, session_id)
  VALUES (new.id, new.content, new.role, new.session_id);
END;

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content, tags, kind)
  VALUES (new.rowid, new.content, new.tags, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, tags, kind)
  VALUES ('delete', old.rowid, old.content, old.tags, old.kind);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, tags, kind)
  VALUES ('delete', old.rowid, old.content, old.tags, old.kind);
  INSERT INTO memories_fts(rowid, content, tags, kind)
  VALUES (new.rowid, new.content, new.tags, new.kind);
END;
"""


@dataclass
class SessionRecord:
    id: str
    created_at: float
    updated_at: float
    cwd: str = ""
    title: str = ""
    model: str = ""
    provider: str = ""
    parent_id: str | None = None
    summary: str = ""
    message_count: int = 0


class MemoryStore:
    """Thread-safe SQLite facade for sessions and long-term memories."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else state_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                try:
                    conn.executescript(_FTS)
                except sqlite3.OperationalError:
                    # FTS5 unavailable — search falls back to LIKE.
                    pass
                conn.commit()
            finally:
                conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ── Sessions ──────────────────────────────────────────────────────────────

    def create_session(
        self,
        *,
        cwd: str = "",
        title: str = "",
        model: str = "",
        provider: str = "",
        parent_id: str | None = None,
    ) -> SessionRecord:
        sid = uuid.uuid4().hex
        now = time.time()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (id, created_at, updated_at, cwd, title, model, provider, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, now, now, cwd, title, model, provider, parent_id),
            )
        return SessionRecord(
            id=sid, created_at=now, updated_at=now, cwd=cwd, title=title,
            model=model, provider=provider, parent_id=parent_id,
        )

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_session(row) if row else None

    def touch_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if summary is not None:
            fields.append("summary = ?")
            values.append(summary)
        if model is not None:
            fields.append("model = ?")
            values.append(model)
        if provider is not None:
            fields.append("provider = ?")
            values.append(provider)
        values.append(session_id)
        with self._tx() as conn:
            conn.execute(
                f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?",
                values,
            )

    def list_sessions(self, *, cwd: str | None = None, limit: int = 20) -> list[SessionRecord]:
        with self._tx() as conn:
            if cwd:
                rows = conn.execute(
                    """SELECT * FROM sessions WHERE cwd = ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (cwd, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_row_session(r) for r in rows]

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict] | None = None,
    ) -> int:
        now = time.time()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["next_seq"]) if row else 0
            conn.execute(
                """INSERT INTO messages
                   (session_id, seq, role, content, name, tool_call_id, tool_calls, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, seq, role, content or "", name, tool_call_id,
                    json.dumps(tool_calls) if tool_calls else None, now,
                ),
            )
            conn.execute(
                """UPDATE sessions SET updated_at = ?,
                   message_count = (SELECT COUNT(*) FROM messages WHERE session_id = ?)
                   WHERE id = ?""",
                (now, session_id, session_id),
            )
        return seq

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._tx() as conn:
            rows = conn.execute(
                """SELECT role, content, name, tool_call_id, tool_calls
                   FROM messages WHERE session_id = ? ORDER BY seq ASC""",
                (session_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {
                "role": r["role"],
                "content": r["content"] or "",
            }
            if r["name"]:
                item["name"] = r["name"]
            if r["tool_call_id"]:
                item["tool_call_id"] = r["tool_call_id"]
            if r["tool_calls"]:
                try:
                    item["tool_calls"] = json.loads(r["tool_calls"])
                except json.JSONDecodeError:
                    pass
            out.append(item)
        return out

    def search_messages(self, query: str, *, limit: int = 20, cwd: str | None = None) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return []
        with self._tx() as conn:
            fts_ok = _has_table(conn, "messages_fts")
            if fts_ok:
                try:
                    if cwd:
                        rows = conn.execute(
                            """SELECT m.role, m.content, m.session_id, s.cwd, s.title, s.updated_at
                               FROM messages_fts f
                               JOIN messages m ON m.id = f.rowid
                               JOIN sessions s ON s.id = m.session_id
                               WHERE messages_fts MATCH ? AND s.cwd = ?
                               ORDER BY rank LIMIT ?""",
                            (_fts_query(q), cwd, limit),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """SELECT m.role, m.content, m.session_id, s.cwd, s.title, s.updated_at
                               FROM messages_fts f
                               JOIN messages m ON m.id = f.rowid
                               JOIN sessions s ON s.id = m.session_id
                               WHERE messages_fts MATCH ?
                               ORDER BY rank LIMIT ?""",
                            (_fts_query(q), limit),
                        ).fetchall()
                    return [_hit(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
            like = f"%{q}%"
            if cwd:
                rows = conn.execute(
                    """SELECT m.role, m.content, m.session_id, s.cwd, s.title, s.updated_at
                       FROM messages m JOIN sessions s ON s.id = m.session_id
                       WHERE m.content LIKE ? AND s.cwd = ?
                       ORDER BY m.created_at DESC LIMIT ?""",
                    (like, cwd, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT m.role, m.content, m.session_id, s.cwd, s.title, s.updated_at
                       FROM messages m JOIN sessions s ON s.id = m.session_id
                       WHERE m.content LIKE ?
                       ORDER BY m.created_at DESC LIMIT ?""",
                    (like, limit),
                ).fetchall()
        return [_hit(r) for r in rows]

    # ── Memories ──────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        tags: str = "",
        cwd: str = "",
        source: str = "agent",
        importance: int = 1,
    ) -> str:
        mid = uuid.uuid4().hex[:16]
        now = time.time()
        content = (content or "").strip()
        if not content:
            raise ValueError("Memory content cannot be empty.")
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO memories
                   (id, kind, content, tags, cwd, source, created_at, updated_at, importance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, kind, content, tags, cwd, source, now, now, max(1, min(5, importance))),
            )
        return mid

    def forget(self, memory_id: str) -> bool:
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cur.rowcount > 0

    def list_memories(
        self,
        *,
        kind: str | None = None,
        cwd: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        clauses: list[str] = []
        values: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            values.append(kind)
        if cwd is not None:
            clauses.append("(cwd = ? OR cwd = '')")
            values.append(cwd)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        values.append(limit)
        with self._tx() as conn:
            rows = conn.execute(
                f"""SELECT id, kind, content, tags, cwd, source, created_at, importance
                    FROM memories {where}
                    ORDER BY importance DESC, updated_at DESC LIMIT ?""",
                values,
            ).fetchall()
        return [dict(r) for r in rows]

    def search_memories(self, query: str, *, limit: int = 15, cwd: str | None = None) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return self.list_memories(cwd=cwd, limit=limit)
        with self._tx() as conn:
            fts_ok = _has_table(conn, "memories_fts")
            if fts_ok:
                try:
                    rows = conn.execute(
                        """SELECT m.id, m.kind, m.content, m.tags, m.cwd, m.source,
                                  m.created_at, m.importance
                           FROM memories_fts f
                           JOIN memories m ON m.rowid = f.rowid
                           WHERE memories_fts MATCH ?
                           ORDER BY rank LIMIT ?""",
                        (_fts_query(q), limit),
                    ).fetchall()
                    hits = [dict(r) for r in rows]
                    if cwd:
                        hits = [h for h in hits if not h["cwd"] or h["cwd"] == cwd]
                    return hits[:limit]
                except sqlite3.OperationalError:
                    pass
            like = f"%{q}%"
            rows = conn.execute(
                """SELECT id, kind, content, tags, cwd, source, created_at, importance
                   FROM memories WHERE content LIKE ? OR tags LIKE ?
                   ORDER BY importance DESC LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        hits = [dict(r) for r in rows]
        if cwd:
            hits = [h for h in hits if not h["cwd"] or h["cwd"] == cwd]
        return hits[:limit]


def _row_session(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        cwd=row["cwd"] or "",
        title=row["title"] or "",
        model=row["model"] or "",
        provider=row["provider"] or "",
        parent_id=row["parent_id"],
        summary=row["summary"] or "",
        message_count=int(row["message_count"] or 0),
    )


def _hit(row: sqlite3.Row) -> dict:
    text = row["content"] or ""
    if len(text) > 400:
        text = text[:400] + "…"
    return {
        "role": row["role"],
        "content": text,
        "session_id": row["session_id"],
        "cwd": row["cwd"],
        "title": row["title"],
        "updated_at": row["updated_at"],
    }


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _fts_query(raw: str) -> str:
    """Escape user text into a safe FTS5 MATCH query (AND of tokens)."""
    tokens = []
    for tok in raw.replace('"', " ").split():
        tok = "".join(c for c in tok if c.isalnum() or c in "_-./")
        if tok:
            tokens.append(f'"{tok}"*')
    return " AND ".join(tokens) if tokens else '""'
