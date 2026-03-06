"""End-to-end test for Agent Orchestra flow."""

from __future__ import annotations

import asyncio

from tools.builtin.orchestra import AgentOrchestraTools, RunStatus


def test_full_orchestration_flow():
    """Simulate: orchestrate -> execute -> review -> approve cycle."""
    orchestra = AgentOrchestraTools()
    # Step 1: Orchestrate a multi-agent goal without auto-starting subprocesses
    result = asyncio.run(
        orchestra._orchestrate(
            goal="Build authentication system",
            subtasks=[
                {"task": "Design auth architecture", "agent": "claude"},
                {"task": "Implement login endpoint", "agent": "codex"},
                {"task": "Write API docs", "agent": "gemini"},
            ],
            auto_execute=False,
        )
    )
    assert len(orchestra._runs) == 3

    # Step 2: Simulate execution completion
    for run_id, run in orchestra._runs.items():
        run.status = RunStatus.REVIEW
        run.output = f"Completed: {run.task}"

    # Step 3: Check status
    status = asyncio.run(orchestra._agent_status())
    assert status.count("[?]") == 3  # All in review

    # Step 4: Approve first two, reject third
    asyncio.run(orchestra._review_result("RUN-001", action="approve"))
    asyncio.run(orchestra._review_result("RUN-002", action="approve"))
    asyncio.run(
        orchestra._review_result(
            "RUN-003", action="reject", feedback="Missing examples"
        )
    )

    assert orchestra._runs["RUN-001"].status == RunStatus.COMPLETED
    assert orchestra._runs["RUN-002"].status == RunStatus.COMPLETED
    assert orchestra._runs["RUN-003"].status == RunStatus.PENDING

    # Step 5: Re-dispatch rejected task
    result = asyncio.run(
        orchestra._dispatch_task(
            task="Write API docs with examples", agent="gemini", auto_execute=False
        )
    )
    assert "RUN-004" in result
    assert len(orchestra._runs) == 4


def test_auto_agent_selection_matches_strengths():
    """Verify agent auto-selection picks the best match."""
    orchestra = AgentOrchestraTools()

    # Architecture task -> claude
    asyncio.run(
        orchestra._dispatch_task(
            task="Refactor the architecture of the auth module",
            auto_execute=False,
        )
    )
    # Documentation task -> gemini
    asyncio.run(
        orchestra._dispatch_task(
            task="Generate documentation for the API",
            auto_execute=False,
        )
    )
    # Implementation task -> codex
    asyncio.run(
        orchestra._dispatch_task(
            task="Implement the boilerplate CRUD tests",
            auto_execute=False,
        )
    )

    assert orchestra._runs["RUN-001"].agent == "claude"
    assert orchestra._runs["RUN-002"].agent == "gemini"
    assert orchestra._runs["RUN-003"].agent == "codex"
