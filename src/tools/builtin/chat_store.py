"""SQLite-backed chat session persistence."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ChatStore:
    """Stores chat sessions and messages in SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".claude" / "memory" / "chat.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New Chat',
                    workspace TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    dispatches TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
            """)

    def create_session(self, workspace: str = "", title: str = "") -> dict:
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        title = title.strip() or "New Chat"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, workspace, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, workspace, now, now),
            )
        return {"id": session_id, "title": title, "workspace": workspace, "created_at": now}

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, workspace, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, title, workspace, created_at, updated_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0

    def add_message(self, session_id: str, role: str, content: str, dispatches: str = "[]") -> dict:
        import json

        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, dispatches, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, dispatches, now),
            )
            # Auto-title: use first user message (truncated)
            if role == "user":
                session = conn.execute(
                    "SELECT title FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if session and session["title"] == "New Chat":
                    title = content[:60] + ("..." if len(content) > 60 else "")
                    conn.execute(
                        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                        (title, now, session_id),
                    )
                else:
                    conn.execute(
                        "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
                    )
            else:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
                )
        return {"id": cur.lastrowid, "role": role, "content": content, "dispatches": json.loads(dispatches), "created_at": now}

    def get_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        import json

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, dispatches, created_at FROM messages WHERE session_id = ? ORDER BY id LIMIT ?",
                (session_id, limit),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["dispatches"] = json.loads(d["dispatches"]) if d["dispatches"] else []
            results.append(d)
        return results
