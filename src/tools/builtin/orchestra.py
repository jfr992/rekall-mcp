"""Agent Orchestra - Multi-AI CLI orchestration.

Dispatches tasks to Claude Code, Gemini CLI, and OpenAI Codex as subprocesses,
tracks runs, and provides review hooks for quality control.
"""

from __future__ import annotations

import asyncio
import enum
import os
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
        auto_execute: bool = True,
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

        if auto_execute:
            asyncio.create_task(self._execute_run(run_id))

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
        skip_keys = {"CLAUDECODE", "ANTHROPIC_API_KEY"}
        env = {k: v for k, v in os.environ.items() if k not in skip_keys}

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run.working_dir or None,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300,
            )

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
        except asyncio.TimeoutError:
            process.kill()
            run.status = RunStatus.FAILED
            run.error = "Agent run timed out after 300 seconds"
        except Exception as e:
            run.status = RunStatus.FAILED
            run.error = str(e)

        return (
            f"**{run_id}** ({run.agent}): {run.status.value}\n"
            f"Output: {run.output[:500]}\n"
            f"{'Error: ' + run.error[:200] if run.error else ''}"
        )

    async def _agent_status(self, status: str | None = None) -> str:
        """Show status of all agent runs, optionally filtered."""
        runs = list(self._runs.values())
        if status:
            runs = [r for r in runs if r.status.value == status]

        if not runs:
            return "No agent runs found."

        emoji = {
            RunStatus.PENDING: "[ ]",
            RunStatus.RUNNING: "[~]",
            RunStatus.COMPLETED: "[x]",
            RunStatus.FAILED: "[!]",
            RunStatus.REVIEW: "[?]",
        }
        lines = ["## Agent Runs"]
        for run in runs:
            lines.append(
                f"- {emoji.get(run.status, '[ ]')} **{run.run_id}** ({run.agent}): "
                f"{run.task[:60]} [{run.status.value}]"
            )
        return "\n".join(lines)

    async def _orchestrate(
        self,
        goal: str,
        subtasks: list[dict],
        working_dir: str = "",
        auto_execute: bool = True,
    ) -> str:
        """Decompose a goal into subtasks and dispatch to agents."""
        results = []
        for sub in subtasks:
            result = await self._dispatch_task(
                task=sub["task"],
                agent=sub.get("agent"),
                auto_execute=auto_execute,
                working_dir=sub.get("working_dir", working_dir),
                context=f"Part of goal: {goal}",
            )
            results.append(result)

        return (
            f"## Orchestration: {goal}\n\n"
            f"Dispatched {len(subtasks)} subtasks:\n\n"
            + "\n\n---\n\n".join(results)
        )

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
            if feedback:
                run.task = f"{run.task}\n\nFeedback from review: {feedback}"
            return (
                f"**{run_id}** rejected and reset to pending.\n"
                f"Feedback: {feedback}\n"
                f"Re-dispatch with `dispatch_task` or `orchestrate` to retry."
            )

        error_block = f"### Error\n```\n{run.error[:500]}\n```" if run.error else ""

        return (
            f"## Review: {run_id} ({run.agent})\n"
            f"**Status:** {run.status.value}\n"
            f"**Task:** {run.task}\n\n"
            f"### Output\n```\n{run.output[:2000]}\n```\n\n"
            f"{error_block}\n\n"
            f"Actions: `approve` | `reject` (with feedback)"
        )

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
            ToolDefinition(
                name="review_result",
                description=(
                    "Review an agent run's output. Show output, approve to mark "
                    "complete, or reject with feedback to reset for retry."
                ),
                handler=self._review_result,
            ),
        ]
