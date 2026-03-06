"""Tests for terminal manager tmux operations."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tools.builtin.terminal_manager import TerminalManager


@pytest.fixture
def manager(tmp_path):
    return TerminalManager(db_path=tmp_path / "terminal.db")


class TestCreateSession:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_create_orchestrator_session(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.create_session(
                session_type="orchestrator",
                agent_name="claude",
                workspace="/tmp/test",
                task="main orchestrator",
            )
        )

        assert result["type"] == "orchestrator"
        assert result["session_id"].startswith("jarvis-orch-")
        assert result["status"] == "running"

    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_create_agent_session(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.create_session(
                session_type="agent-dispatched",
                agent_name="codex",
                workspace="/tmp/test",
                task="implement auth TDD",
            )
        )

        assert result["type"] == "agent-dispatched"
        assert result["session_id"].startswith("jarvis-agent-")


class TestListSessions:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_list_returns_all(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            manager.create_session("orchestrator", "claude", "/tmp", "main")
        )
        loop.run_until_complete(
            manager.create_session("agent-dispatched", "codex", "/tmp", "auth")
        )

        result = loop.run_until_complete(manager.list_sessions())
        assert len(result) == 2


class TestCaptureOutput:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_capture_pane_output(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b"line1\nline2\nline3\n", b"")
        )
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.capture_output("jarvis-agent-abc123", lines=20)
        )
        assert "line1" in result
        assert "line3" in result


class TestKillSession:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_kill_removes_from_store(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.create_session("orchestrator", "claude", "/tmp", "main")
        )
        session_id = result["session_id"]

        killed = asyncio.get_event_loop().run_until_complete(
            manager.kill_session(session_id)
        )
        assert killed is True

        sessions = asyncio.get_event_loop().run_until_complete(manager.list_sessions())
        assert len(sessions) == 0
