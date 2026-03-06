"""Tests for Agent Orchestra tool provider."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

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
            auto_execute=False,
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
            auto_execute=False,
        )
    )
    assert "Unknown agent" in result


def test_dispatch_task_auto_selects_agent():
    orchestra = AgentOrchestraTools()
    result = asyncio.run(
        orchestra._dispatch_task(
            task="Refactor the authentication middleware",
            auto_execute=False,
        )
    )
    assert "RUN-001" in result
    run = orchestra._runs["RUN-001"]
    assert run.agent in {"claude", "gemini", "codex"}


def test_dispatch_task_auto_executes_by_default():
    async def _exercise():
        orchestra = AgentOrchestraTools()
        with patch(
            "tools.builtin.orchestra.AgentOrchestraTools._execute_run",
            new=AsyncMock(return_value="ok"),
        ) as mock_execute:
            await orchestra._dispatch_task(task="Auto execute task", agent="claude")
            await asyncio.sleep(0)

        assert mock_execute.call_count == 1

    asyncio.run(_exercise())


def test_agent_status_shows_all_runs():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Task A",
            agent="claude",
            auto_execute=False,
        )
    )
    asyncio.run(
        orchestra._dispatch_task(
            task="Task B",
            agent="gemini",
            auto_execute=False,
        )
    )

    result = asyncio.run(orchestra._agent_status())
    assert "RUN-001" in result
    assert "RUN-002" in result
    assert "claude" in result
    assert "gemini" in result


def test_agent_status_filters_by_status():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Task A",
            agent="claude",
            auto_execute=False,
        )
    )
    asyncio.run(
        orchestra._dispatch_task(
            task="Task B",
            agent="gemini",
            auto_execute=False,
        )
    )
    orchestra._runs["RUN-001"].status = RunStatus.COMPLETED

    result = asyncio.run(orchestra._agent_status(status="pending"))
    assert "RUN-001" not in result
    assert "RUN-002" in result


def test_orchestrate_decomposes_and_dispatches():
    orchestra = AgentOrchestraTools()
    with patch(
        "tools.builtin.orchestra.AgentOrchestraTools._execute_run",
        new=AsyncMock(return_value="ok"),
    ):
        result = asyncio.run(
            orchestra._orchestrate(
                goal="Build a REST API with auth, tests, and docs",
                subtasks=[
                    {"task": "Design API architecture", "agent": "claude"},
                    {"task": "Write API tests", "agent": "codex"},
                    {"task": "Generate API documentation", "agent": "gemini"},
                ],
            )
        )
    assert len(orchestra._runs) == 3
    assert "RUN-001" in result
    assert "RUN-002" in result
    assert "RUN-003" in result


def test_review_result_shows_completed_output():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Write tests",
            agent="claude",
            auto_execute=False,
        )
    )
    run = orchestra._runs["RUN-001"]
    run.status = RunStatus.COMPLETED
    run.output = "def test_auth():\n    assert login('user', 'pass') == True"

    result = asyncio.run(orchestra._review_result("RUN-001"))
    assert "test_auth" in result
    assert "COMPLETED" in result or "completed" in result


def test_review_result_approve():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Write code",
            agent="codex",
            auto_execute=False,
        )
    )
    run = orchestra._runs["RUN-001"]
    run.status = RunStatus.REVIEW
    run.output = "function hello() { return 'world'; }"

    result = asyncio.run(orchestra._review_result("RUN-001", action="approve"))
    assert run.status == RunStatus.COMPLETED
    assert "approved" in result.lower()


def test_review_result_reject():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Write code",
            agent="codex",
            auto_execute=False,
        )
    )
    run = orchestra._runs["RUN-001"]
    run.status = RunStatus.REVIEW
    run.output = "bad code"

    result = asyncio.run(
        orchestra._review_result(
            "RUN-001", action="reject", feedback="Missing error handling"
        )
    )
    assert run.status == RunStatus.PENDING
    assert "Missing error handling" in result


def test_persist_run_creates_memory():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Fix auth bug",
            agent="claude",
            auto_execute=False,
        )
    )
    run = orchestra._runs["RUN-001"]
    run.status = RunStatus.COMPLETED
    run.output = "Fixed the JWT validation in auth.py"

    mock_observe = AsyncMock(return_value="Saved")
    orchestra._memory_observe = mock_observe

    asyncio.run(orchestra._persist_run("RUN-001"))
    mock_observe.assert_called_once()
    call_kwargs = mock_observe.call_args[1]
    assert "agent_run" in call_kwargs.get("memory_type", "")
    assert "claude" in call_kwargs.get("content", "")


def test_execute_run_calls_subprocess():
    orchestra = AgentOrchestraTools()
    asyncio.run(
        orchestra._dispatch_task(
            task="Write tests",
            agent="claude",
            working_dir="/tmp",
            auto_execute=False,
        )
    )
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
    asyncio.run(
        orchestra._dispatch_task(task="Do something", agent="gemini", auto_execute=False)
    )

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
            auto_execute=False,
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
