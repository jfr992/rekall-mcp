"""Tests for terminal manager MCP tool definitions."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import asyncio

from tools.builtin.terminal_manager import TerminalManager


def test_get_tools_returns_four_tools(tmp_path):
    manager = TerminalManager(db_path=tmp_path / "terminal.db")
    tools = manager.get_tools()
    names = [t.name for t in tools]
    assert "dispatch_agent" in names
    assert "list_agents" in names
    assert "agent_output" in names
    assert "kill_agent" in names
    assert len(tools) == 4


@patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
def test_dispatch_agent_tool(mock_exec, tmp_path):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_exec.return_value = mock_proc

    manager = TerminalManager(db_path=tmp_path / "terminal.db")
    tools = manager.get_tools()
    dispatch = next(t for t in tools if t.name == "dispatch_agent")
    result = asyncio.get_event_loop().run_until_complete(
        dispatch.handler(agent="codex", task="implement auth", workspace="/tmp")
    )
    assert "session_id" in result
    assert result["agent"] == "codex"
