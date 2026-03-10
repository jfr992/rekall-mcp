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
        return f"memento-{prefix}-{short}"

    def _build_cli_command(
        self, agent_name: str, workspace: str, task: str, mcp_url: str = ""
    ) -> str:
        import json as _json
        from pathlib import Path as _Path

        # Source user profile for full env (API keys, AWS creds, etc.)
        # then unset CLAUDECODE to allow nested Claude sessions
        prefix = "source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; unset CLAUDECODE; "
        if agent_name == "claude":
            if mcp_url:
                # Write MCP config to a file (avoids shell quoting issues)
                mcp_config_path = _Path.home() / ".claude" / "memento-mcp.json"
                mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
                mcp_config_path.write_text(_json.dumps({
                    "mcpServers": {
                        "memento": {
                            "type": "http",
                            "url": mcp_url,
                        }
                    }
                }))
                cmd = f"claude --mcp-config {mcp_config_path}"
            else:
                cmd = "claude"
        elif agent_name == "codex":
            cmd = "codex"
        elif agent_name == "gemini":
            cmd = "gemini"
        else:
            cmd = agent_name
        return f"{prefix}{cmd}"

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

        work_dir = workspace or "/tmp"
        import os as _os
        env = _os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_id,
            "-c",
            work_dir,
            cli_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start tmux session: {stderr.decode()}")

        # Configure tmux for xterm.js embedding
        for opt_args in [
            # Ensure terminal type is set (launchd doesn't provide TERM)
            ["set-option", "-t", session_id, "default-terminal", "xterm-256color"],
            # Disable status bar — bleeds into xterm.js viewport
            ["set-option", "-t", session_id, "status", "off"],
            # Enable mouse support so scroll = tmux scrollback, not arrow keys
            ["set-option", "-t", session_id, "mouse", "on"],
        ]:
            await asyncio.create_subprocess_exec(
                "tmux", *opt_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        # Send the task as initial input to dispatched agents
        # (not orchestrator — that's an interactive session for the user)
        if task and session_type != "orchestrator":
            async def _send_task_when_ready():
                """Wait for the CLI to be ready, then send the task."""
                # Poll for readiness — CLI is ready when tmux pane has
                # content beyond the initial shell setup lines.
                # Try up to 30 seconds (60 x 0.5s) to accommodate slow
                # shell profile sourcing + CLI startup.
                for _ in range(60):
                    await asyncio.sleep(0.5)
                    probe = await asyncio.create_subprocess_exec(
                        "tmux", "capture-pane", "-t", session_id, "-p",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, _ = await probe.communicate()
                    pane_text = stdout.decode("utf-8", errors="replace").strip()
                    # CLI is ready when there's meaningful output (prompt, welcome)
                    if len(pane_text) > 10:
                        break
                else:
                    # Fallback — send anyway after timeout
                    pass
                # Extra settle time after prompt appears
                await asyncio.sleep(1)
                # Send text literally (-l prevents interpreting key names)
                await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", session_id, "-l", task,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # Small gap so the CLI registers the text before Enter
                await asyncio.sleep(0.5)
                await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", session_id, "Enter",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            asyncio.create_task(_send_task_when_ready())

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
        live_sessions = set(stdout.decode().strip().split("\n")) if stdout and stdout.strip() else set()

        for session in self._store.list_sessions():
            session_id = session["session_id"]
            if session_id not in live_sessions:
                # tmux session is gone — delete the DB record entirely
                # so it doesn't block orchestrator re-creation
                self._store.delete_session(session_id)
            elif session["status"] == "dead":
                # tmux session is alive but DB says dead — fix it
                self._store.update_status(session_id, "running")

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
