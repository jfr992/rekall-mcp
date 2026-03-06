"""Agent Orchestra - Multi-AI CLI orchestration.

Dispatches tasks to Claude Code, Gemini CLI, and OpenAI Codex as subprocesses,
tracks runs, and provides review hooks for quality control.
"""

from __future__ import annotations

import asyncio
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
    context: str = ""
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

    def _next_run_id(self) -> str:
        self._run_counter += 1
        return f"RUN-{self._run_counter:03d}"

    def _select_agent(self, task: str) -> str:
        """Select best agent based on task content matching strengths."""
        task_lower = task.lower()
        best_agent = "claude"
        best_score = 0

        for agent in self._agents.values():
            score = sum(1 for strength in agent.strengths if strength in task_lower)
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
            context=context,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._runs[run_id] = run

        return (
            f"Dispatched **{run_id}** to **{selected}**\n"
            f"Task: {task}\n"
            f"Status: {run.status.value}"
        )

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
        if run.context:
            prompt = f"{prompt}\n\nContext: {run.context}"

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
