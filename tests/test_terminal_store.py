"""Tests for terminal session SQLite store."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.builtin.terminal_store import TerminalStore


@pytest.fixture
def store(tmp_path: Path):
    db = tmp_path / "terminal.db"
    return TerminalStore(db_path=db)


def test_create_session(store):
    session = store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main orchestrator",
        workspace="/tmp/test",
        cli_command="claude --mcp-config '{}'",
    )
    assert session["session_id"] == "jarvis-orch-abc123"
    assert session["type"] == "orchestrator"
    assert session["agent_name"] == "claude"
    assert session["status"] == "running"


def test_list_sessions(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    store.create_session(
        session_id="jarvis-agent-def456",
        session_type="agent-dispatched",
        agent_name="codex",
        task="implement auth",
        workspace="/tmp",
        cli_command="codex",
    )
    sessions = store.list_sessions()
    assert len(sessions) == 2


def test_get_session(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    session = store.get_session("jarvis-orch-abc123")
    assert session is not None
    assert session["agent_name"] == "claude"


def test_update_status(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    store.update_status("jarvis-orch-abc123", "dead")
    session = store.get_session("jarvis-orch-abc123")
    assert session["status"] == "dead"


def test_delete_session(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    assert store.delete_session("jarvis-orch-abc123") is True
    assert store.get_session("jarvis-orch-abc123") is None
