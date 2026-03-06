"""Chat orchestrator - Claude API backend for multi-agent dispatch."""

from __future__ import annotations

import re

from tools.builtin.agent_config import AgentConfigManager


DISPATCH_PATTERN = re.compile(
    r'<<DISPATCH\s+agent="(\w+)"\s+task="([^"]+)"(?:\s+context="([^"]*)")?\s*>>'
)


class ChatOrchestrator:
    """Orchestrates multi-agent workflows via Claude API."""

    def __init__(self) -> None:
        self._config = AgentConfigManager()
        self._client = None  # Lazy init

    def _get_client(self):
        """Lazy-init Anthropic client."""
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

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

    async def _call_claude_api(self, system: str, messages: list[dict]):
        """Call Claude API with conversation."""
        client = self._get_client()
        return client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            messages=messages,
        )

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

        return {
            "run_id": run_id,
            "agent": intent["agent"],
            "task": intent["task"],
            "status": "pending",
        }

    async def handle_chat(
        self,
        message: str,
        workspace: str,
        history: list[dict],
    ) -> dict:
        """Process a chat message through the orchestrator."""
        system = self.build_system_prompt(workspace)
        messages = history + [{"role": "user", "content": message}]

        response = await self._call_claude_api(system, messages)
        response_text = response.content[0].text

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
