"""Tests for Agent Orchestra tool provider."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tools.builtin.orchestra import AgentOrchestraTools, AgentConfig, AgentRun, RunStatus


def test_default_agent_registry_has_three_agents():
    orchestra = AgentOrchestraTools()
    agents = orchestra.list_agents()
    assert len(agents) == 3
    names = {a.name for a in agents}
    assert names == {"claude", "gemini", "codex"}


def test_agent_config_has_required_fields():
    config = AgentConfig(
        name="claude",
        cli_command=["claude", "-p"],
        description="Claude Code - architecture and complex reasoning",
        strengths=["architecture", "debugging", "refactoring"],
    )
    assert config.name == "claude"
    assert config.cli_command == ["claude", "-p"]


def test_agent_run_tracks_status():
    run = AgentRun(
        run_id="run_001",
        agent="claude",
        task="Refactor auth module",
        status=RunStatus.PENDING,
    )
    assert run.status == RunStatus.PENDING
    assert run.agent == "claude"


def test_dispatch_task_creates_run():
    orchestra = AgentOrchestraTools()
    result = asyncio.run(
        orchestra._dispatch_task(
            task="Write unit tests for auth module",
            agent="claude",
            working_dir="/tmp/test-project",
        )
    )
    assert "RUN-001" in result
    assert "claude" in result
    assert len(orchestra._runs) == 1
    run = orchestra._runs["RUN-001"]
    assert run.status == RunStatus.PENDING
    assert run.task == "Write unit tests for auth module"
    assert run.working_dir == "/tmp/test-project"


def test_dispatch_task_rejects_unknown_agent():
    orchestra = AgentOrchestraTools()
    result = asyncio.run(
        orchestra._dispatch_task(
            task="Do something",
            agent="unknown_agent",
        )
    )
    assert "Unknown agent" in result


def test_dispatch_task_auto_selects_agent():
    orchestra = AgentOrchestraTools()
    result = asyncio.run(
        orchestra._dispatch_task(
            task="Refactor the authentication middleware",
        )
    )
    assert "RUN-001" in result
    run = orchestra._runs["RUN-001"]
    assert run.agent in {"claude", "gemini", "codex"}


def test_execute_run_calls_subprocess():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Write tests", agent="claude", working_dir="/tmp"))
    run = orchestra._runs["RUN-001"]

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"Task completed successfully", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = asyncio.run(orchestra._execute_run("RUN-001"))

    assert run.status == RunStatus.COMPLETED
    assert "completed successfully" in run.output
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    assert "claude" in call_args[0][0]


def test_execute_run_handles_failure():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Do something", agent="gemini"))

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b"Error: rate limited"))
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = asyncio.run(orchestra._execute_run("RUN-001"))

    run = orchestra._runs["RUN-001"]
    assert run.status == RunStatus.FAILED
    assert "rate limited" in run.error


def test_execute_run_injects_memento_context():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Fix auth bug",
            agent="claude",
            context="The auth module uses JWT tokens stored in Redis",
        )
    )

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"Fixed", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        asyncio_result = asyncio.run(orchestra._execute_run("RUN-001"))

    call_args = mock_exec.call_args
    prompt = " ".join(str(a) for a in call_args[0])
    assert "auth" in prompt.lower() or "Fix auth bug" in prompt
