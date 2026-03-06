"""Terminal manager — tmux session CRUD and MCP tool definitions."""
from __future__ import annotations

import asyncio
from typing import Any

from tools.builtin.agent_config import AgentConfigManager
from tools.builtin.terminal_store import TerminalStore


class TerminalManager:
    """Manages tmux-backed terminal sessions for the agent orchestra."""

    def __init__(self, db_path: str | None = None) -> None:
        self._store = TerminalStore(db_path=db_path)
        self._config = AgentConfigManager()
        self._id_counter = 0

    def _generate_id(self, session_type: str) -> str:
        self._id_counter += 1
        short = f"{self._id_counter:06d}"
        prefix = "orch" if session_type == "orchestrator" else "agent"
        return f"jarvis-{prefix}-{short}"

    def _build_cli_command(
        self, agent_name: str, workspace: str, task: str, mcp_url: str = ""
    ) -> str:
        if agent_name == "claude":
            if mcp_url:
                return f"claude --mcp-config '{mcp_url}'"
            return "claude"
        if agent_name == "codex":
            return f"codex --quiet"
        if agent_name == "gemini":
            return f"gemini"
        return f"{agent_name}"

    async def create_session(
        self,
        session_type: str,
        agent_name: str,
        workspace: str,
        task: str = "",
        mcp_url: str = "",
    ) -> dict[str, Any]:
        session_id = self._generate_id(session_type)
        cli_command = self._build_cli_command(agent_name, workspace, task, mcp_url)

        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_id,
            "-c",
            workspace,
            cli_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if proc.returncode is not None and proc.returncode != 0:
            raise RuntimeError("Failed to start tmux session")

        return self._store.create_session(
            session_id=session_id,
            session_type=session_type,
            agent_name=agent_name,
            task=task,
            workspace=workspace,
            cli_command=cli_command,
        )

    async def list_sessions(self) -> list[dict[str, Any]]:
        return self._store.list_sessions()

    async def capture_output(self, session_id: str, lines: int = 20) -> str:
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "capture-pane",
            "-t",
            session_id,
            "-p",
            "-S",
            f"-{lines}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip()

    async def kill_session(self, session_id: str) -> bool:
        await asyncio.create_subprocess_exec(
            "tmux",
            "kill-session",
            "-t",
            session_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return self._store.delete_session(session_id)

    async def sync_status(self) -> None:
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "list-sessions",
            "-F",
            "#{session_name}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        live_sessions = set(stdout.decode().strip().split("\n")) if stdout else set()

        for session in self._store.list_sessions():
            session_id = session["session_id"]
            if session_id not in live_sessions and session["status"] == "running":
                self._store.update_status(session_id, "dead")

    def get_tools(self):
        """Return MCP tool definitions for orchestrator dispatch."""
        from tools.base import ToolDefinition

        async def dispatch_agent(agent: str, task: str, workspace: str) -> dict:
            result = await self.create_session(
                session_type="agent-dispatched",
                agent_name=agent,
                workspace=workspace,
                task=task,
            )
            return {
                "session_id": result["session_id"],
                "agent": agent,
                "task": task,
                "status": "running",
            }

        async def list_agents() -> list[dict]:
            await self.sync_status()
            return await self.list_sessions()

        async def agent_output(session_id: str, lines: int = 20) -> dict:
            output = await self.capture_output(session_id, lines)
            return {"session_id": session_id, "output": output}

        async def kill_agent(session_id: str) -> dict:
            killed = await self.kill_session(session_id)
            return {"session_id": session_id, "killed": killed}

        return [
            ToolDefinition(
                name="dispatch_agent",
                description="Spawn a new agent terminal session with a task",
                handler=dispatch_agent,
            ),
            ToolDefinition(
                name="list_agents",
                description="List active terminal sessions and their status",
                handler=list_agents,
            ),
            ToolDefinition(
                name="agent_output",
                description="Capture last N lines from an agent's terminal",
                handler=agent_output,
            ),
            ToolDefinition(
                name="kill_agent",
                description="Terminate an agent terminal session",
                handler=kill_agent,
            ),
        ]
