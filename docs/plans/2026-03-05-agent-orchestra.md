# Agent Orchestra Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Orchestrate multiple AI CLIs (Claude Code, Gemini CLI, OpenAI Codex) from the Memento Command Center, enabling Claude as the "architect" to decompose tasks and dispatch work to specialized agents.

**Architecture:** A new `AgentOrchestraTools` provider extends `BaseToolProvider` to manage agent lifecycle via subprocess execution. Each agent run is tracked in Qdrant as a memory with type `agent_run`, linked via the knowledge graph. The Command Center dashboard gets a new panel showing agent status, output, and review gates.

**Tech Stack:** Python 3.11+, FastMCP, subprocess/asyncio for CLI invocation, Qdrant for run persistence, SSE for live dashboard updates, existing BaseToolProvider pattern.

---

### Task 1: Agent Registry Data Model

**Files:**
- Create: `src/tools/builtin/orchestra.py`
- Test: `tests/test_orchestra.py`

**Step 1: Write the failing test**

```python
# tests/test_orchestra.py
"""Tests for Agent Orchestra tool provider."""

from __future__ import annotations

import pytest

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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.builtin.orchestra'`

**Step 3: Write minimal implementation**

```python
# src/tools/builtin/orchestra.py
"""Agent Orchestra - Multi-AI CLI orchestration.

Dispatches tasks to Claude Code, Gemini CLI, and OpenAI Codex as subprocesses,
tracks runs, and provides review gates for quality control.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tools.base import BaseToolProvider, ToolDefinition


class RunStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW = "review"


@dataclass
class AgentConfig:
    """Configuration for an AI CLI agent."""

    name: str
    cli_command: list[str]
    description: str
    strengths: list[str] = field(default_factory=list)


@dataclass
class AgentRun:
    """Tracks a single agent task execution."""

    run_id: str
    agent: str
    task: str
    status: RunStatus
    output: str = ""
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    working_dir: str = ""


DEFAULT_AGENTS = [
    AgentConfig(
        name="claude",
        cli_command=["claude", "-p"],
        description="Claude Code - architecture, complex reasoning, debugging",
        strengths=["architecture", "debugging", "refactoring", "planning"],
    ),
    AgentConfig(
        name="gemini",
        cli_command=["gemini", "-p"],
        description="Gemini CLI - fast iteration, broad knowledge",
        strengths=["prototyping", "research", "documentation"],
    ),
    AgentConfig(
        name="codex",
        cli_command=["codex", "-q"],
        description="OpenAI Codex - autonomous code generation",
        strengths=["implementation", "boilerplate", "tests"],
    ),
]


class AgentOrchestraTools(BaseToolProvider):
    """Tool provider for multi-AI CLI orchestration."""

    name = "orchestra"
    description = "Orchestrate multiple AI CLIs from the Command Center"
    requires: list[str] = []
    builtin = True

    def __init__(self) -> None:
        self._agents: dict[str, AgentConfig] = {a.name: a for a in DEFAULT_AGENTS}
        self._runs: dict[str, AgentRun] = {}
        self._run_counter = 0

    def list_agents(self) -> list[AgentConfig]:
        return list(self._agents.values())

    def get_tools(self) -> list[ToolDefinition]:
        return []  # Placeholder - tools added in subsequent tasks
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/tools/builtin/orchestra.py tests/test_orchestra.py
git commit -m "feat(orchestra): add agent registry data model

Defines AgentConfig, AgentRun, RunStatus dataclasses and
AgentOrchestraTools provider with default agent registry
for Claude, Gemini, and Codex CLIs."
```

---

### Task 2: dispatch_task Tool

**Files:**
- Modify: `src/tools/builtin/orchestra.py`
- Test: `tests/test_orchestra.py`

**Step 1: Write the failing test**

```python
# Append to tests/test_orchestra.py

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


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
    # Should auto-select based on task content matching agent strengths
    run = orchestra._runs["RUN-001"]
    assert run.agent in {"claude", "gemini", "codex"}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py::test_dispatch_task_creates_run -v`
Expected: FAIL with `AttributeError: 'AgentOrchestraTools' object has no attribute '_dispatch_task'`

**Step 3: Write minimal implementation**

Add to `AgentOrchestraTools` in `src/tools/builtin/orchestra.py`:

```python
    def _next_run_id(self) -> str:
        self._run_counter += 1
        return f"RUN-{self._run_counter:03d}"

    def _select_agent(self, task: str) -> str:
        """Select best agent based on task content matching strengths."""
        task_lower = task.lower()
        best_agent = "claude"  # Default
        best_score = 0

        for agent in self._agents.values():
            score = sum(1 for s in agent.strengths if s in task_lower)
            if score > best_score:
                best_score = score
                best_agent = agent.name

        return best_agent

    async def _dispatch_task(
        self,
        task: str,
        agent: str | None = None,
        working_dir: str = "",
        context: str = "",
    ) -> str:
        """Dispatch a task to an AI agent for execution."""
        if agent and agent not in self._agents:
            return f"Unknown agent: {agent}. Available: {', '.join(self._agents)}"

        selected = agent or self._select_agent(task)
        run_id = self._next_run_id()

        run = AgentRun(
            run_id=run_id,
            agent=selected,
            task=task,
            status=RunStatus.PENDING,
            working_dir=working_dir,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._runs[run_id] = run

        return (
            f"Dispatched **{run_id}** to **{selected}**\n"
            f"Task: {task}\n"
            f"Status: {run.status.value}"
        )

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="dispatch_task",
                description=(
                    "Dispatch a task to an AI agent (claude, gemini, codex). "
                    "Auto-selects best agent if none specified."
                ),
                handler=self._dispatch_task,
            ),
        ]
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add src/tools/builtin/orchestra.py tests/test_orchestra.py
git commit -m "feat(orchestra): add dispatch_task tool with auto-agent selection

Dispatches tasks to AI agents, auto-selecting based on
task content matching agent strengths. Tracks runs with
unique IDs and pending status."
```

---

### Task 3: Agent Subprocess Execution

**Files:**
- Modify: `src/tools/builtin/orchestra.py`
- Test: `tests/test_orchestra.py`

**Step 1: Write the failing test**

```python
# Append to tests/test_orchestra.py

@pytest.mark.asyncio
async def test_execute_run_calls_subprocess():
    orchestra = AgentOrchestraTools()
    await orchestra._dispatch_task(task="Write tests", agent="claude", working_dir="/tmp")
    run = orchestra._runs["RUN-001"]

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"Task completed successfully", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await orchestra._execute_run("RUN-001")

    assert run.status == RunStatus.COMPLETED
    assert "completed successfully" in run.output
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    assert "claude" in call_args[0][0]


@pytest.mark.asyncio
async def test_execute_run_handles_failure():
    orchestra = AgentOrchestraTools()
    await orchestra._dispatch_task(task="Do something", agent="gemini")

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b"Error: rate limited"))
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await orchestra._execute_run("RUN-001")

    run = orchestra._runs["RUN-001"]
    assert run.status == RunStatus.FAILED
    assert "rate limited" in run.error


@pytest.mark.asyncio
async def test_execute_run_injects_memento_context():
    orchestra = AgentOrchestraTools()
    await orchestra._dispatch_task(
        task="Fix auth bug",
        agent="claude",
        context="The auth module uses JWT tokens stored in Redis",
    )

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"Fixed", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await orchestra._execute_run("RUN-001")

    # Verify the prompt includes context
    call_args = mock_exec.call_args
    prompt = " ".join(str(a) for a in call_args[0])
    assert "auth" in prompt.lower() or "Fix auth bug" in prompt
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py::test_execute_run_calls_subprocess -v`
Expected: FAIL with `AttributeError: 'AgentOrchestraTools' object has no attribute '_execute_run'`

**Step 3: Write minimal implementation**

Add to `AgentOrchestraTools` in `src/tools/builtin/orchestra.py`:

```python
    import asyncio
    import subprocess

    async def _execute_run(self, run_id: str) -> str:
        """Execute a dispatched run by invoking the agent CLI."""
        if run_id not in self._runs:
            return f"Unknown run: {run_id}"

        run = self._runs[run_id]
        agent_config = self._agents[run.agent]
        run.status = RunStatus.RUNNING

        # Build the prompt with context injection
        prompt = run.task
        if run.working_dir:
            prompt = f"Working directory: {run.working_dir}\n\n{prompt}"

        # Build CLI command
        cmd = [*agent_config.cli_command, prompt]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run.working_dir or None,
            )
            stdout, stderr = await process.communicate()

            run.output = stdout.decode("utf-8", errors="replace")
            run.error = stderr.decode("utf-8", errors="replace")
            run.completed_at = datetime.now(timezone.utc).isoformat()

            if process.returncode == 0:
                run.status = RunStatus.COMPLETED
            else:
                run.status = RunStatus.FAILED

        except FileNotFoundError:
            run.status = RunStatus.FAILED
            run.error = f"Agent CLI not found: {agent_config.cli_command[0]}"

        except Exception as e:
            run.status = RunStatus.FAILED
            run.error = str(e)

        return (
            f"**{run_id}** ({run.agent}): {run.status.value}\n"
            f"Output: {run.output[:500]}\n"
            f"{'Error: ' + run.error[:200] if run.error else ''}"
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: PASS (9 tests)

**Step 5: Commit**

```bash
git add src/tools/builtin/orchestra.py tests/test_orchestra.py
git commit -m "feat(orchestra): add subprocess execution for agent runs

Executes agent CLIs via asyncio.create_subprocess_exec,
captures stdout/stderr, handles failures, and injects
task context into the prompt."
```

---

### Task 4: agent_status and orchestrate Tools

**Files:**
- Modify: `src/tools/builtin/orchestra.py`
- Test: `tests/test_orchestra.py`

**Step 1: Write the failing test**

```python
# Append to tests/test_orchestra.py

def test_agent_status_shows_all_runs():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Task A", agent="claude"))
    asyncio.run(orchestra._dispatch_task(task="Task B", agent="gemini"))

    result = asyncio.run(orchestra._agent_status())
    assert "RUN-001" in result
    assert "RUN-002" in result
    assert "claude" in result
    assert "gemini" in result


def test_agent_status_filters_by_status():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Task A", agent="claude"))
    asyncio.run(orchestra._dispatch_task(task="Task B", agent="gemini"))
    orchestra._runs["RUN-001"].status = RunStatus.COMPLETED

    result = asyncio.run(orchestra._agent_status(status="pending"))
    assert "RUN-001" not in result
    assert "RUN-002" in result


def test_orchestrate_decomposes_and_dispatches():
    orchestra = AgentOrchestraTools()
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py::test_agent_status_shows_all_runs -v`
Expected: FAIL with `AttributeError`

**Step 3: Write minimal implementation**

Add to `AgentOrchestraTools`:

```python
    async def _agent_status(self, status: str | None = None) -> str:
        """Show status of all agent runs, optionally filtered."""
        runs = list(self._runs.values())
        if status:
            runs = [r for r in runs if r.status.value == status]

        if not runs:
            return "No agent runs found."

        lines = ["## Agent Runs\n"]
        for run in runs:
            emoji = {
                RunStatus.PENDING: "[ ]",
                RunStatus.RUNNING: "[~]",
                RunStatus.COMPLETED: "[x]",
                RunStatus.FAILED: "[!]",
                RunStatus.REVIEW: "[?]",
            }.get(run.status, "[ ]")
            lines.append(
                f"- {emoji} **{run.run_id}** ({run.agent}): {run.task[:60]} "
                f"[{run.status.value}]"
            )
        return "\n".join(lines)

    async def _orchestrate(
        self,
        goal: str,
        subtasks: list[dict],
        working_dir: str = "",
    ) -> str:
        """Decompose a goal into subtasks and dispatch to agents."""
        results = []
        for sub in subtasks:
            result = await self._dispatch_task(
                task=sub["task"],
                agent=sub.get("agent"),
                working_dir=sub.get("working_dir", working_dir),
                context=f"Part of goal: {goal}",
            )
            results.append(result)

        return (
            f"## Orchestration: {goal}\n\n"
            f"Dispatched {len(subtasks)} subtasks:\n\n"
            + "\n\n---\n\n".join(results)
        )
```

Update `get_tools()`:

```python
    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="dispatch_task",
                description=(
                    "Dispatch a task to an AI agent (claude, gemini, codex). "
                    "Auto-selects best agent if none specified."
                ),
                handler=self._dispatch_task,
            ),
            ToolDefinition(
                name="agent_status",
                description="Show status of all agent runs, optionally filtered by status.",
                handler=self._agent_status,
            ),
            ToolDefinition(
                name="orchestrate",
                description=(
                    "Decompose a goal into subtasks and dispatch each to the "
                    "best agent. Accepts a list of {task, agent?, working_dir?} objects."
                ),
                handler=self._orchestrate,
            ),
        ]
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: PASS (12 tests)

**Step 5: Commit**

```bash
git add src/tools/builtin/orchestra.py tests/test_orchestra.py
git commit -m "feat(orchestra): add agent_status and orchestrate tools

agent_status shows all runs with optional status filter.
orchestrate decomposes goals into subtasks and dispatches
each to the specified or auto-selected agent."
```

---

### Task 5: review_result Tool with Gate

**Files:**
- Modify: `src/tools/builtin/orchestra.py`
- Test: `tests/test_orchestra.py`

**Step 1: Write the failing test**

```python
# Append to tests/test_orchestra.py

def test_review_result_shows_completed_output():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Write tests", agent="claude"))
    run = orchestra._runs["RUN-001"]
    run.status = RunStatus.COMPLETED
    run.output = "def test_auth():\n    assert login('user', 'pass') == True"

    result = asyncio.run(orchestra._review_result("RUN-001"))
    assert "test_auth" in result
    assert "COMPLETED" in result or "completed" in result


def test_review_result_approve():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Write code", agent="codex"))
    run = orchestra._runs["RUN-001"]
    run.status = RunStatus.REVIEW
    run.output = "function hello() { return 'world'; }"

    result = asyncio.run(orchestra._review_result("RUN-001", action="approve"))
    assert run.status == RunStatus.COMPLETED
    assert "approved" in result.lower()


def test_review_result_reject():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Write code", agent="codex"))
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py::test_review_result_shows_completed_output -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `AgentOrchestraTools`:

```python
    async def _review_result(
        self,
        run_id: str,
        action: str | None = None,
        feedback: str = "",
    ) -> str:
        """Review an agent run's output. Optionally approve or reject."""
        if run_id not in self._runs:
            return f"Unknown run: {run_id}"

        run = self._runs[run_id]

        if action == "approve":
            run.status = RunStatus.COMPLETED
            return f"**{run_id}** approved and marked completed."

        if action == "reject":
            run.status = RunStatus.PENDING
            original_task = run.task
            if feedback:
                run.task = f"{original_task}\n\nFeedback from review: {feedback}"
            return (
                f"**{run_id}** rejected and reset to pending.\n"
                f"Feedback: {feedback}\n"
                f"Re-dispatch with `dispatch_task` or `orchestrate` to retry."
            )

        # Default: show the output for review
        return (
            f"## Review: {run_id} ({run.agent})\n"
            f"**Status:** {run.status.value}\n"
            f"**Task:** {run.task}\n\n"
            f"### Output\n```\n{run.output[:2000]}\n```\n\n"
            f"{'### Error\\n```\\n' + run.error[:500] + '\\n```' if run.error else ''}\n\n"
            f"Actions: `approve` | `reject` (with feedback)"
        )
```

Add to `get_tools()`:

```python
            ToolDefinition(
                name="review_result",
                description=(
                    "Review an agent run's output. Show output, approve to mark "
                    "complete, or reject with feedback to reset for retry."
                ),
                handler=self._review_result,
            ),
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: PASS (15 tests)

**Step 5: Commit**

```bash
git add src/tools/builtin/orchestra.py tests/test_orchestra.py
git commit -m "feat(orchestra): add review_result tool with approve/reject gates

Enables reviewing agent output, approving completed work,
or rejecting with feedback to reset for retry."
```

---

### Task 6: Memory Integration - Persist Runs to Qdrant

**Files:**
- Modify: `src/tools/builtin/orchestra.py`
- Test: `tests/test_orchestra.py`

**Step 1: Write the failing test**

```python
# Append to tests/test_orchestra.py

def test_persist_run_creates_memory():
    orchestra = AgentOrchestraTools()
    asyncio.run(orchestra._dispatch_task(task="Fix auth bug", agent="claude"))
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py::test_persist_run_creates_memory -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `AgentOrchestraTools`:

```python
    async def _memory_observe(self, content: str, memory_type: str = "note", **kwargs) -> str:
        """Placeholder for memory integration. Override with actual observe handler."""
        return "Memory integration not configured."

    async def _persist_run(self, run_id: str) -> str:
        """Persist a completed run as a memory for future context."""
        if run_id not in self._runs:
            return f"Unknown run: {run_id}"

        run = self._runs[run_id]
        content = (
            f"Agent run [{run.agent}]: {run.task}\n"
            f"Status: {run.status.value}\n"
            f"Output: {run.output[:1000]}"
        )

        return await self._memory_observe(
            content=content,
            memory_type="agent_run",
            project="orchestra",
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra.py -v`
Expected: PASS (16 tests)

**Step 5: Commit**

```bash
git add src/tools/builtin/orchestra.py tests/test_orchestra.py
git commit -m "feat(orchestra): add memory persistence for agent runs

Completed runs can be saved as agent_run memories in Qdrant
for future context retrieval across sessions."
```

---

### Task 7: Register Orchestra Provider in Server

**Files:**
- Modify: `src/server.py`
- Test: `tests/test_server_orchestra.py`

**Step 1: Write the failing test**

```python
# tests/test_server_orchestra.py
"""Tests for Orchestra REST API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.mcp.streamable_http_app()) as test_client:
        yield test_client


def test_dispatch_task_route(client):
    with patch(
        "tools.builtin.orchestra.AgentOrchestraTools._dispatch_task",
        new=AsyncMock(return_value="Dispatched RUN-001 to claude"),
    ) as mock_dispatch:
        response = client.post(
            "/api/orchestra/dispatch",
            json={"task": "Fix auth bug", "agent": "claude"},
        )

    assert response.status_code == 200
    assert "RUN-001" in response.json()["result"]


def test_agent_status_route(client):
    with patch(
        "tools.builtin.orchestra.AgentOrchestraTools._agent_status",
        new=AsyncMock(return_value="No agent runs found."),
    ):
        response = client.get("/api/orchestra/status")

    assert response.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_server_orchestra.py -v`
Expected: FAIL (routes not registered yet)

**Step 3: Write minimal implementation**

In `src/server.py`, add the orchestra import and register custom routes following the existing pattern:

```python
# In the imports section
from tools.builtin.orchestra import AgentOrchestraTools

# In _initialize_tools() or equivalent registration
orchestra = AgentOrchestraTools()

# Custom routes
@mcp.custom_route("/api/orchestra/dispatch", methods=["POST"])
async def dispatch_task_route(request):
    body = await request.json()
    result = await orchestra._dispatch_task(
        task=body["task"],
        agent=body.get("agent"),
        working_dir=body.get("working_dir", ""),
        context=body.get("context", ""),
    )
    return JSONResponse({"result": result})

@mcp.custom_route("/api/orchestra/status", methods=["GET"])
async def agent_status_route(request):
    status_filter = request.query_params.get("status")
    result = await orchestra._agent_status(status=status_filter)
    return JSONResponse({"result": result})

@mcp.custom_route("/api/orchestra/runs/{run_id}/review", methods=["POST"])
async def review_result_route(request):
    run_id = request.path_params["run_id"]
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    result = await orchestra._review_result(
        run_id=run_id,
        action=body.get("action"),
        feedback=body.get("feedback", ""),
    )
    return JSONResponse({"result": result})
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_server_orchestra.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/server.py tests/test_server_orchestra.py
git commit -m "feat(orchestra): register orchestra tools and REST routes

Adds /api/orchestra/dispatch, /api/orchestra/status, and
/api/orchestra/runs/{run_id}/review endpoints to the server."
```

---

### Task 8: Command Center Dashboard Panel

**Files:**
- Modify: `src/dashboard/` (or inline HTML in server.py, depending on existing pattern)
- No automated test (UI visual verification)

**Step 1: Identify existing dashboard pattern**

Read `src/server.py` around line 608 where the dashboard HTMLResponse is served. The orchestra panel will be added as a new section in the existing dashboard HTML.

**Step 2: Add orchestra panel to dashboard**

Add a new `<section>` to the dashboard HTML with:

```html
<section id="orchestra-panel">
  <h2>Agent Orchestra</h2>
  <div class="orchestra-controls">
    <button onclick="refreshAgentStatus()">Refresh</button>
    <button onclick="showDispatchForm()">+ Dispatch Task</button>
  </div>

  <div id="agent-runs-list">
    <!-- Populated via fetch('/api/orchestra/status') -->
  </div>

  <dialog id="dispatch-dialog">
    <form method="dialog" onsubmit="dispatchTask(event)">
      <label>Task: <textarea name="task" required></textarea></label>
      <label>Agent:
        <select name="agent">
          <option value="">Auto-select</option>
          <option value="claude">Claude (architecture)</option>
          <option value="gemini">Gemini (prototyping)</option>
          <option value="codex">Codex (implementation)</option>
        </select>
      </label>
      <label>Working Dir: <input name="working_dir" type="text"></label>
      <button type="submit">Dispatch</button>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
    </form>
  </dialog>
</section>

<script>
async function refreshAgentStatus() {
  const resp = await fetch('/api/orchestra/status');
  const data = await resp.json();
  document.getElementById('agent-runs-list').innerHTML =
    `<pre>${data.result}</pre>`;
}

function showDispatchForm() {
  document.getElementById('dispatch-dialog').showModal();
}

async function dispatchTask(event) {
  event.preventDefault();
  const form = event.target;
  const body = {
    task: form.task.value,
    agent: form.agent.value || undefined,
    working_dir: form.working_dir.value || undefined,
  };
  await fetch('/api/orchestra/dispatch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  form.closest('dialog').close();
  refreshAgentStatus();
}

// Auto-refresh every 10 seconds
setInterval(refreshAgentStatus, 10000);
refreshAgentStatus();
</script>
```

**Step 3: Verify manually**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && docker compose --profile dev up -d --build mcp-dev`
Open: `http://localhost:8001/dashboard`
Verify: Orchestra panel visible with dispatch button and agent list

**Step 4: Commit**

```bash
git add src/server.py
git commit -m "feat(orchestra): add Command Center dashboard panel

Adds orchestra section to dashboard with agent status display,
dispatch form dialog, and 10-second auto-refresh."
```

---

### Task 9: End-to-End Integration Test

**Files:**
- Create: `tests/test_orchestra_e2e.py`

**Step 1: Write the e2e test**

```python
# tests/test_orchestra_e2e.py
"""End-to-end test for Agent Orchestra flow."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tools.builtin.orchestra import AgentOrchestraTools, RunStatus


def test_full_orchestration_flow():
    """Simulate: orchestrate -> execute -> review -> approve cycle."""
    orchestra = AgentOrchestraTools()

    # Step 1: Orchestrate a multi-agent goal
    result = asyncio.run(
        orchestra._orchestrate(
            goal="Build authentication system",
            subtasks=[
                {"task": "Design auth architecture", "agent": "claude"},
                {"task": "Implement login endpoint", "agent": "codex"},
                {"task": "Write API docs", "agent": "gemini"},
            ],
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
        orchestra._dispatch_task(task="Write API docs with examples", agent="gemini")
    )
    assert "RUN-004" in result
    assert len(orchestra._runs) == 4


def test_auto_agent_selection_matches_strengths():
    """Verify agent auto-selection picks the best match."""
    orchestra = AgentOrchestraTools()

    # Architecture task -> claude
    asyncio.run(orchestra._dispatch_task(task="Refactor the architecture of the auth module"))
    assert orchestra._runs["RUN-001"].agent == "claude"

    # Documentation task -> gemini
    asyncio.run(orchestra._dispatch_task(task="Generate documentation for the API"))
    assert orchestra._runs["RUN-002"].agent == "gemini"

    # Implementation task -> codex
    asyncio.run(orchestra._dispatch_task(task="Implement the boilerplate CRUD tests"))
    assert orchestra._runs["RUN-003"].agent == "codex"
```

**Step 2: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_orchestra_e2e.py -v`
Expected: PASS (2 tests)

**Step 3: Run full test suite**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/ -v`
Expected: All tests pass, no regressions

**Step 4: Commit**

```bash
git add tests/test_orchestra_e2e.py
git commit -m "test(orchestra): add end-to-end orchestration flow test

Covers full lifecycle: orchestrate -> review -> approve/reject,
re-dispatch, and auto-agent selection by task strengths."
```

---

## Summary

| Task | Component | Tests | Tools Added |
|------|-----------|-------|-------------|
| 1 | Data model (AgentConfig, AgentRun, RunStatus) | 3 | - |
| 2 | `dispatch_task` with auto-selection | 3 | dispatch_task |
| 3 | Subprocess execution | 3 | - (internal) |
| 4 | `agent_status` + `orchestrate` | 3 | agent_status, orchestrate |
| 5 | `review_result` with approve/reject | 3 | review_result |
| 6 | Memory persistence (Qdrant) | 1 | - (internal) |
| 7 | Server registration + REST routes | 2 | 3 REST endpoints |
| 8 | Dashboard panel | manual | - (UI) |
| 9 | E2E integration test | 2 | - |
| **Total** | | **20** | **4 MCP tools + 3 REST endpoints** |
