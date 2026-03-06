"""Chat orchestrator - Claude CLI backend for multi-agent dispatch."""

from __future__ import annotations

import asyncio
import json
import re

from tools.builtin.agent_config import AgentConfigManager


DISPATCH_PATTERN = re.compile(
    r'<<DISPATCH\s+agent="(\w+)"\s+task="([^"]+)"(?:\s+context="([^"]*)")?\s*>>'
)


class ChatOrchestrator:
    """Orchestrates multi-agent workflows via Claude CLI."""

    def __init__(self) -> None:
        self._config = AgentConfigManager()

    def build_system_prompt(self, workspace: str, recent_memories: str = "") -> str:
        """Build the orchestrator system prompt with workspace context."""
        template = self._config.get_prompt_template("claude")
        return template.format(
            workspace=workspace,
            recent_memories=recent_memories or "No recent memories loaded.",
        )

    def parse_dispatch_intents(self, response_text: str) -> list[dict]:
        """Parse DISPATCH directives from orchestrator response."""
        intents = []
        for match in DISPATCH_PATTERN.finditer(response_text):
            intent = {
                "agent": match.group(1),
                "task": match.group(2),
            }
            if match.group(3):
                intent["context"] = match.group(3)
            intents.append(intent)
        return intents

    async def _call_claude_cli(self, system: str, messages: list[dict]) -> str:
        """Call Claude CLI in print mode with system prompt and conversation."""
        # Build the user prompt from the last message; history is context
        last_msg = messages[-1]["content"] if messages else ""

        # claude -p sends stdin as the prompt; use sonnet for fast orchestration
        # --strict-mcp-config with no --mcp-config disables all MCP servers
        cmd = [
            "claude", "-p",
            "--output-format", "text",
            "--model", "sonnet",
            "--strict-mcp-config",
        ]

        # Combine system + conversation context into the prompt
        prompt_parts = [f"<system>{system}</system>"]
        for msg in messages[:-1]:
            role = msg["role"]
            prompt_parts.append(f"<{role}>{msg['content']}</{role}>")
        prompt_parts.append(last_msg)
        full_prompt = "\n\n".join(prompt_parts)

        import os
        # Remove CLAUDECODE (prevents nested session error) and
        # ANTHROPIC_API_KEY (OAuth token doesn't work with -p; let CLI use Max auth)
        skip_keys = {"CLAUDECODE", "ANTHROPIC_API_KEY"}
        env = {k: v for k, v in os.environ.items() if k not in skip_keys}

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=full_prompt.encode()),
            timeout=120,
        )

        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            output = stdout.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Claude CLI failed (exit {process.returncode}): "
                f"stderr={error!r} stdout={output!r}"
            )

        return stdout.decode("utf-8", errors="replace").strip()

    async def _execute_dispatch(self, intent: dict, workspace: str) -> dict:
        """Execute a single dispatch via the orchestra tool provider."""
        orchestra = _get_shared_orchestra()
        result = await orchestra._dispatch_task(
            task=intent["task"],
            agent=intent["agent"],
            working_dir=workspace,
            context=intent.get("context", ""),
        )
        run_id = ""
        if "**" in result:
            parts = result.split("**")
            if len(parts) >= 2:
                run_id = parts[1]

        # Give the background task a moment to spawn the process and capture PID
        await asyncio.sleep(1)

        # Pull PID and CLI command from the run object
        pid = 0
        cli_command = ""
        if run_id and run_id in orchestra._runs:
            run = orchestra._runs[run_id]
            pid = run.pid
            cli_command = run.cli_command

        return {
            "run_id": run_id,
            "agent": intent["agent"],
            "task": intent["task"],
            "status": "pending",
            "pid": pid,
            "cli_command": cli_command,
        }

    async def _fetch_recent_memories(self, query: str) -> str:
        """Fetch recent memories from the memento REST API."""
        import json as _json
        import urllib.request

        def _fetch():
            payload = _json.dumps({
                "query": query,
                "limit": 5,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:8002/api/memory/recall",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
                memories = data.get("memories", [])
                if not memories:
                    return ""
                parts = []
                for m in memories[:5]:
                    content = m.get("content", "")
                    mem_type = m.get("type", "")
                    parts.append(f"[{mem_type}] {content}")
                return "\n".join(parts)

        try:
            return await asyncio.get_event_loop().run_in_executor(None, _fetch)
        except Exception:
            return ""

    async def handle_chat(
        self,
        message: str,
        workspace: str,
        history: list[dict],
    ) -> dict:
        """Process a chat message through the orchestrator."""
        memories = await self._fetch_recent_memories(message)
        system = self.build_system_prompt(workspace, recent_memories=memories)
        messages = history + [{"role": "user", "content": message}]

        response_text = await self._call_claude_cli(system, messages)

        intents = self.parse_dispatch_intents(response_text)
        dispatches = []
        for intent in intents:
            dispatch_result = await self._execute_dispatch(intent, workspace)
            dispatches.append(dispatch_result)

        return {"message": response_text, "dispatches": dispatches}


_shared_orchestra = None


def _get_shared_orchestra():
    """Get or create the shared orchestra instance."""
    global _shared_orchestra
    if _shared_orchestra is None:
        from tools.builtin.orchestra import AgentOrchestraTools

        _shared_orchestra = AgentOrchestraTools()
    return _shared_orchestra
