"""SQLite-backed terminal session metadata store."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class TerminalStore:
    """Stores terminal session metadata in SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".claude" / "memory" / "terminal.db"
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS terminal_sessions (
                    session_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    task TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    cli_command TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_session(
        self,
        session_id: str,
        session_type: str,
        agent_name: str,
        task: str = "",
        workspace: str = "",
        cli_command: str = "",
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO terminal_sessions "
                "(session_id, type, agent_name, task, workspace, status, cli_command, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                (session_id, session_type, agent_name, task, workspace, cli_command, now),
            )
        return {
            "session_id": session_id,
            "type": session_type,
            "agent_name": agent_name,
            "task": task,
            "workspace": workspace,
            "status": "running",
            "cli_command": cli_command,
            "created_at": now,
        }

    def list_sessions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM terminal_sessions ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM terminal_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_status(self, session_id: str, status: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE terminal_sessions SET status = ? WHERE session_id = ?",
                (status, session_id),
            )
        return cur.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM terminal_sessions WHERE session_id = ?",
                (session_id,),
            )
        return cur.rowcount > 0
