"""Integration test for terminal session lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tools.builtin.terminal_manager import TerminalManager


@pytest.fixture
def manager(tmp_path):
    return TerminalManager(db_path=tmp_path / "terminal.db")


@pytest.mark.asyncio
@patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
async def test_full_lifecycle(mock_exec, manager):
    """Test CREATE -> LIST -> OUTPUT -> KILL lifecycle."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"test output\n", b""))
    mock_exec.return_value = mock_proc

    # CREATE
    session = await manager.create_session("orchestrator", "claude", "/tmp", "test")
    sid = session["session_id"]
    assert sid.startswith("jarvis-orch-")

    # LIST
    sessions = await manager.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == sid

    # OUTPUT
    output = await manager.capture_output(sid, 20)
    assert "test output" in output

    # KILL
    killed = await manager.kill_session(sid)
    assert killed is True

    # VERIFY GONE
    sessions = await manager.list_sessions()
    assert len(sessions) == 0


@pytest.mark.asyncio
@patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
async def test_dispatch_via_tools(mock_exec, manager):
    """Test dispatching via MCP tool interface."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_exec.return_value = mock_proc

    tools = manager.get_tools()
    dispatch = next(t for t in tools if t.name == "dispatch_agent")
    list_agents = next(t for t in tools if t.name == "list_agents")

    result = await dispatch.handler(
        agent="codex", task="implement auth", workspace="/tmp"
    )
    assert result["agent"] == "codex"
    assert result["status"] == "running"

    agents = await list_agents.handler()
    assert len(agents) == 1
    assert agents[0]["agent_name"] == "codex"
