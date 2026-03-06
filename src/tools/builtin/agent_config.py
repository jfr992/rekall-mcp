"""Agent configuration manager for multi-agent orchestration."""

from __future__ import annotations

import json
from pathlib import Path

MEMENTO_MCP = {
    "url": "http://localhost:8001/mcp",
    "transport": "streamable-http",
}

DEFAULT_CONFIGS: dict[str, dict] = {
    "claude": {
        "mcpServers": {
            "memento": MEMENTO_MCP,
        },
        "note": "Uses existing ~/.claude/settings.json with all plugins",
    },
    "codex": {
        "mcpServers": {
            "memento": MEMENTO_MCP,
        },
    },
    "gemini": {
        "mcpServers": {
            "memento": MEMENTO_MCP,
        },
    },
}

PROMPT_TEMPLATES: dict[str, str] = {
    "codex": (
        "You are implementing a specific task from a detailed plan.\n"
        "Working directory: {workspace}\n"
        "MCP servers: memento (for reading/writing project memory)\n\n"
        "## Task\n{task_description}\n\n"
        "## Plan Context\n{plan_steps}\n\n"
        "## Rules\n"
        "- Follow TDD: write failing test, implement, verify, commit\n"
        "- One step at a time\n"
        "- Commit after each passing test\n"
        "- Store implementation decisions in memento memory\n"
        "- Do NOT deviate from the plan\n"
    ),
    "gemini": (
        "You are researching a topic to inform an implementation decision.\n"
        "Working directory: {workspace}\n"
        "MCP servers: memento (for storing research findings)\n\n"
        "## Research Question\n{task_description}\n\n"
        "## Context\n{memory_context}\n\n"
        "## Rules\n"
        "- Be thorough and cite sources\n"
        "- Store key findings as memento memories (type: \"fact\" or \"learning\")\n"
        "- Summarize with actionable recommendations\n"
        "- Note any risks or trade-offs discovered\n"
    ),
    "claude": (
        "You are the orchestrator of a multi-agent development team.\n\n"
        "Available agents:\n"
        "- codex: Fast programmer. Give detailed, step-by-step implementation instructions.\n"
        "- gemini: Deep researcher. Use for docs, patterns, exploration.\n"
        "- claude: You. Handle architecture, decomposition, review.\n\n"
        "Active workspace: {workspace}\n\n"
        "When the user describes a goal:\n"
        "1. Decompose into subtasks\n"
        "2. Assign each to the best agent\n"
        "3. For codex tasks, write detailed plans (TDD, file paths, exact specs)\n"
        "4. For gemini tasks, frame clear research questions\n"
        "5. Review all outputs before presenting to user\n\n"
        "Available memories: {recent_memories}\n\n"
        "Respond conversationally. Show your dispatch plan before executing.\n"
    ),
}


class AgentConfigManager:
    """Manages MCP configs and prompt templates for AI agents."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or (Path.home() / ".memento" / "agent-configs")

    def get_all_configs(self) -> dict[str, dict]:
        """Return all agent configs (disk overrides defaults)."""
        configs: dict[str, dict] = {}
        for name in DEFAULT_CONFIGS:
            configs[name] = self.get_config(name) or DEFAULT_CONFIGS[name]
        return configs

    def get_config(self, agent: str) -> dict | None:
        """Get config for a specific agent."""
        config_file = self._config_dir / f"{agent}.json"
        if config_file.exists():
            with open(config_file) as f:
                return json.load(f)
        return DEFAULT_CONFIGS.get(agent)

    def save_config(self, agent: str, config: dict) -> None:
        """Save agent config to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        config_file = self._config_dir / f"{agent}.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

    def get_prompt_template(self, agent: str) -> str:
        """Get the role-specific prompt template for an agent."""
        return PROMPT_TEMPLATES.get(agent, "")
