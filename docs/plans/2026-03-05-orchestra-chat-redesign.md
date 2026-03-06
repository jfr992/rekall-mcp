# Orchestra Chat Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the Agent Orchestra dashboard panel from a dispatch form into a master chat interface where the user talks to Claude (orchestrator), which decomposes goals and dispatches to role-specific AI agents sharing memory via memento MCP.

**Architecture:** Chat-centric center panel replaces brain graph. Claude API orchestrator backend interprets user messages and dispatches to sub-agents (Claude, Codex, Gemini) via CLI subprocesses. Each agent gets a role-specific context template. Memento MCP is the shared knowledge layer. Brain graph moves to a toggle modal overlay.

**Tech Stack:** Python/FastAPI (server), vanilla JS (dashboard), Claude API via `anthropic` SDK (orchestrator), CLI subprocesses (agent execution), memento MCP (shared memory)

---

## Task 1: Add Anthropic SDK Dependency

**Files:**
- Modify: `pyproject.toml:18-28`

**Step 1: Add `anthropic` to dependencies**

Add `anthropic>=0.40.0` to the `dependencies` list in `pyproject.toml`:

```toml
dependencies = [
    "mcp>=1.0.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "qdrant-client>=1.12.0",
    "sentence-transformers>=3.0.0",
    "networkx>=3.0.0",
    "click>=8.0.0",
    "pyyaml>=6.0.0",
    "anthropic>=0.40.0",
]
```

**Step 2: Rebuild dev container to verify dependency resolves**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && docker compose --profile dev build mcp-dev`
Expected: Build succeeds, `anthropic` installed.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat(orchestra): add anthropic SDK dependency for orchestrator backend"
```

---

## Task 2: Workspace Scanner Backend

**Files:**
- Create: `src/tools/builtin/workspaces.py`
- Create: `tests/test_workspaces.py`

**Step 1: Write failing tests for workspace scanner**

```python
# tests/test_workspaces.py
"""Tests for workspace scanner."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from tools.builtin.workspaces import WorkspaceScanner


def test_scan_finds_git_repos(tmp_path):
    """Scanner finds directories containing .git."""
    repo1 = tmp_path / "repo-a"
    repo1.mkdir()
    (repo1 / ".git").mkdir()

    repo2 = tmp_path / "repo-b"
    repo2.mkdir()
    (repo2 / ".git").mkdir()

    not_repo = tmp_path / "plain-dir"
    not_repo.mkdir()

    scanner = WorkspaceScanner(roots=[str(tmp_path)])
    workspaces = scanner.scan()

    paths = {w["path"] for w in workspaces}
    assert str(repo1) in paths
    assert str(repo2) in paths
    assert str(not_repo) not in paths


def test_scan_returns_name_and_path():
    """Each workspace has name and path keys."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()

        scanner = WorkspaceScanner(roots=[tmp])
        workspaces = scanner.scan()

        assert len(workspaces) == 1
        assert workspaces[0]["name"] == "my-project"
        assert workspaces[0]["path"] == str(repo)


def test_scan_skips_nonexistent_roots():
    """Scanner silently skips roots that don't exist."""
    scanner = WorkspaceScanner(roots=["/nonexistent/path/abc123"])
    workspaces = scanner.scan()
    assert workspaces == []


def test_scan_expands_tilde():
    """Scanner expands ~ in root paths."""
    scanner = WorkspaceScanner(roots=["~/Repos"])
    # Just verify it doesn't crash; actual repos depend on environment
    workspaces = scanner.scan()
    assert isinstance(workspaces, list)


def test_scan_depth_one_only(tmp_path):
    """Scanner only checks direct children, not nested repos."""
    nested = tmp_path / "parent" / "child"
    nested.mkdir(parents=True)
    (nested / ".git").mkdir()

    scanner = WorkspaceScanner(roots=[str(tmp_path)])
    workspaces = scanner.scan()

    # parent/ itself is not a git repo, child/ is nested too deep
    paths = {w["path"] for w in workspaces}
    assert str(nested) not in paths
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_workspaces.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.builtin.workspaces'`

**Step 3: Implement WorkspaceScanner**

```python
# src/tools/builtin/workspaces.py
"""Workspace scanner - discovers git repos from configured root directories."""

from __future__ import annotations

from pathlib import Path


class WorkspaceScanner:
    """Scans configured root directories for git repositories."""

    def __init__(self, roots: list[str] | None = None) -> None:
        self._roots = roots or []

    def scan(self) -> list[dict[str, str]]:
        """Scan all roots for directories containing .git. Returns list of {name, path}."""
        workspaces = []
        for root_str in self._roots:
            root = Path(root_str).expanduser()
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / ".git").exists():
                    workspaces.append({
                        "name": child.name,
                        "path": str(child),
                    })
        return workspaces
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_workspaces.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/tools/builtin/workspaces.py tests/test_workspaces.py
git commit -m "feat(workspaces): add workspace scanner for git repo discovery"
```

---

## Task 3: Workspace API Endpoint

**Files:**
- Modify: `src/server.py` (add route near line 615)
- Create: `tests/test_server_workspaces.py`

**Step 1: Write failing test for workspace endpoint**

```python
# tests/test_server_workspaces.py
"""Tests for workspace API endpoint."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_workspaces_endpoint_returns_list(tmp_path):
    """GET /api/workspaces returns discovered repos."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    with patch("server._get_workspace_roots", return_value=[str(tmp_path)]):
        from server import mcp

        # Use the test client approach matching existing tests
        # The endpoint should return a JSON list of workspaces
        pass  # Actual HTTP test depends on test client setup
```

Note: This test follows the pattern established in `tests/test_server_orchestra.py`. The actual test client approach should match the existing test infrastructure.

**Step 2: Add workspace endpoint to server.py**

Add after the orchestra endpoints (around line 660), before the dashboard route:

```python
def _get_workspace_roots() -> list[str]:
    """Load workspace roots from config or defaults."""
    import json
    config_path = Path.home() / ".memento" / "dashboard.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        return config.get("workspace_roots", [])
    return ["~/Repos", "~/scripts", "~/.config/superpowers/worktrees"]


@mcp.custom_route("/api/workspaces", methods=["GET"])
async def _handle_workspaces(request):
    """GET /api/workspaces - List available workspaces (git repos)."""
    from starlette.responses import JSONResponse
    from tools.builtin.workspaces import WorkspaceScanner

    roots = _get_workspace_roots()
    scanner = WorkspaceScanner(roots=roots)
    workspaces = scanner.scan()
    return JSONResponse({"workspaces": workspaces})
```

**Step 3: Run server and test endpoint manually**

Run: `curl http://localhost:8001/api/workspaces`
Expected: JSON with `{"workspaces": [{"name": "...", "path": "..."}, ...]}`

**Step 4: Commit**

```bash
git add src/server.py tests/test_server_workspaces.py
git commit -m "feat(workspaces): add GET /api/workspaces endpoint"
```

---

## Task 4: Agent Config Manager

**Files:**
- Create: `src/tools/builtin/agent_config.py`
- Create: `tests/test_agent_config.py`

**Step 1: Write failing tests for agent config manager**

```python
# tests/test_agent_config.py
"""Tests for agent config manager."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.builtin.agent_config import AgentConfigManager


def test_default_configs_exist():
    """Manager provides defaults for claude, codex, gemini."""
    manager = AgentConfigManager()
    configs = manager.get_all_configs()
    assert "claude" in configs
    assert "codex" in configs
    assert "gemini" in configs


def test_codex_config_has_memento_mcp():
    """Codex config includes memento MCP server."""
    manager = AgentConfigManager()
    config = manager.get_config("codex")
    assert "mcpServers" in config
    assert "memento" in config["mcpServers"]


def test_get_prompt_template_codex():
    """Codex prompt template includes TDD instructions."""
    manager = AgentConfigManager()
    template = manager.get_prompt_template("codex")
    assert "TDD" in template or "test" in template.lower()
    assert "{task_description}" in template
    assert "{workspace}" in template


def test_get_prompt_template_gemini():
    """Gemini prompt template includes research instructions."""
    manager = AgentConfigManager()
    template = manager.get_prompt_template("gemini")
    assert "research" in template.lower()
    assert "{task_description}" in template


def test_get_prompt_template_claude():
    """Claude orchestrator template includes agent list."""
    manager = AgentConfigManager()
    template = manager.get_prompt_template("claude")
    assert "codex" in template
    assert "gemini" in template


def test_save_and_load_config(tmp_path):
    """Saved configs persist to disk and can be reloaded."""
    manager = AgentConfigManager(config_dir=tmp_path)
    custom = {"mcpServers": {"memento": {"url": "http://custom:8001/mcp"}}}
    manager.save_config("codex", custom)

    # Reload from disk
    manager2 = AgentConfigManager(config_dir=tmp_path)
    loaded = manager2.get_config("codex")
    assert loaded["mcpServers"]["memento"]["url"] == "http://custom:8001/mcp"


def test_unknown_agent_returns_none():
    """Unknown agent name returns None."""
    manager = AgentConfigManager()
    assert manager.get_config("nonexistent") is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_agent_config.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement AgentConfigManager**

```python
# src/tools/builtin/agent_config.py
"""Agent configuration manager for multi-agent orchestration.

Manages MCP configs and prompt templates for each AI agent role.
"""

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
        '- Store key findings as memento memories (type: "fact" or "learning")\n'
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
        configs = {}
        for name in DEFAULT_CONFIGS:
            configs[name] = self.get_config(name) or DEFAULT_CONFIGS[name]
        return configs

    def get_config(self, agent: str) -> dict | None:
        """Get config for a specific agent. Disk file overrides default."""
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
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_agent_config.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/tools/builtin/agent_config.py tests/test_agent_config.py
git commit -m "feat(orchestra): add agent config manager with role-specific templates"
```

---

## Task 5: Chat Orchestrator Backend

**Files:**
- Create: `src/tools/builtin/chat_orchestrator.py`
- Create: `tests/test_chat_orchestrator.py`

**Step 1: Write failing tests for chat orchestrator**

```python
# tests/test_chat_orchestrator.py
"""Tests for chat orchestrator."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from tools.builtin.chat_orchestrator import ChatOrchestrator


def test_build_system_prompt_includes_workspace():
    """System prompt includes the active workspace path."""
    orchestrator = ChatOrchestrator()
    prompt = orchestrator.build_system_prompt("/home/user/project")
    assert "/home/user/project" in prompt


def test_build_system_prompt_includes_agent_roles():
    """System prompt describes available agents."""
    orchestrator = ChatOrchestrator()
    prompt = orchestrator.build_system_prompt("/tmp")
    assert "codex" in prompt
    assert "gemini" in prompt


def test_parse_dispatch_intents_no_dispatches():
    """Plain text response yields no dispatch intents."""
    orchestrator = ChatOrchestrator()
    intents = orchestrator.parse_dispatch_intents(
        "Here's my analysis of the architecture..."
    )
    assert intents == []


def test_parse_dispatch_intents_with_dispatch_block():
    """Response with DISPATCH blocks yields parsed intents."""
    orchestrator = ChatOrchestrator()
    response = (
        "I'll break this down:\n\n"
        '<<DISPATCH agent="codex" task="Implement login endpoint">>\n'
        '<<DISPATCH agent="gemini" task="Research JWT patterns">>\n'
    )
    intents = orchestrator.parse_dispatch_intents(response)
    assert len(intents) == 2
    assert intents[0]["agent"] == "codex"
    assert intents[0]["task"] == "Implement login endpoint"
    assert intents[1]["agent"] == "gemini"


def test_handle_chat_calls_claude_api():
    """handle_chat calls Claude API and returns response."""
    orchestrator = ChatOrchestrator()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="I'll help with that.")]

    with patch.object(orchestrator, "_call_claude_api", new=AsyncMock(return_value=mock_response)):
        result = asyncio.run(
            orchestrator.handle_chat(
                message="Build auth middleware",
                workspace="/tmp/project",
                history=[],
            )
        )

    assert "message" in result
    assert result["message"] == "I'll help with that."


def test_handle_chat_returns_dispatches():
    """handle_chat returns dispatch intents from response."""
    orchestrator = ChatOrchestrator()

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='Starting research.\n<<DISPATCH agent="gemini" task="Research JWT">>'
        )
    ]

    with patch.object(orchestrator, "_call_claude_api", new=AsyncMock(return_value=mock_response)):
        with patch.object(orchestrator, "_execute_dispatch", new=AsyncMock(return_value={"run_id": "RUN-001", "agent": "gemini", "status": "pending"})):
            result = asyncio.run(
                orchestrator.handle_chat(
                    message="Research JWT auth",
                    workspace="/tmp",
                    history=[],
                )
            )

    assert "dispatches" in result
    assert len(result["dispatches"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_chat_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement ChatOrchestrator**

```python
# src/tools/builtin/chat_orchestrator.py
"""Chat orchestrator - Claude API backend for multi-agent dispatch.

Uses Claude API to interpret user messages and dispatch to sub-agents.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

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
        from tools.builtin.orchestra import AgentOrchestraTools

        orchestra = _get_shared_orchestra()
        result = await orchestra._dispatch_task(
            task=intent["task"],
            agent=intent["agent"],
            working_dir=workspace,
            context=intent.get("context", ""),
        )
        # Extract run ID from result string
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
        """Process a chat message through the orchestrator.

        Returns dict with 'message' (str) and 'dispatches' (list).
        """
        system = self.build_system_prompt(workspace)
        messages = history + [{"role": "user", "content": message}]

        response = await self._call_claude_api(system, messages)
        response_text = response.content[0].text

        # Parse and execute any dispatch intents
        intents = self.parse_dispatch_intents(response_text)
        dispatches = []
        for intent in intents:
            dispatch_result = await self._execute_dispatch(intent, workspace)
            dispatches.append(dispatch_result)

        return {
            "message": response_text,
            "dispatches": dispatches,
        }


# Shared orchestra instance for dispatching
_shared_orchestra = None


def _get_shared_orchestra():
    """Get or create the shared orchestra instance."""
    global _shared_orchestra
    if _shared_orchestra is None:
        from tools.builtin.orchestra import AgentOrchestraTools
        _shared_orchestra = AgentOrchestraTools()
    return _shared_orchestra
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_chat_orchestrator.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/tools/builtin/chat_orchestrator.py tests/test_chat_orchestrator.py
git commit -m "feat(orchestra): add chat orchestrator with Claude API backend"
```

---

## Task 6: Chat API Endpoints

**Files:**
- Modify: `src/server.py` (add routes near line 660)

**Step 1: Write failing test for chat endpoint**

```python
# tests/test_server_chat.py
"""Tests for chat API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def test_chat_endpoint_requires_message():
    """POST /api/orchestra/chat requires message field."""
    # Test that missing 'message' returns 400 or error
    pass


def test_chat_history_endpoint_returns_list():
    """GET /api/orchestra/chat/history returns message list."""
    pass
```

Note: Full HTTP tests depend on test client infrastructure. Focus on integration testing via curl after implementation.

**Step 2: Add chat endpoints to server.py**

Add these routes after the existing orchestra endpoints (around line 660):

```python
# Chat history storage (in-memory, per design doc non-goal of no persistence in v1)
_chat_history: list[dict] = []


@mcp.custom_route("/api/orchestra/chat", methods=["POST"])
async def _handle_orchestra_chat(request):
    """POST /api/orchestra/chat - Send message to orchestrator."""
    from starlette.responses import JSONResponse
    from tools.builtin.chat_orchestrator import ChatOrchestrator

    body = await request.json()
    message = body.get("message", "")
    workspace = body.get("workspace", "")
    history = body.get("history", [])

    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    orchestrator = ChatOrchestrator()
    result = await orchestrator.handle_chat(
        message=message,
        workspace=workspace,
        history=history,
    )

    # Store in chat history
    _chat_history.append({"role": "user", "content": message})
    _chat_history.append({"role": "assistant", "content": result["message"]})

    return JSONResponse(result)


@mcp.custom_route("/api/orchestra/chat/history", methods=["GET"])
async def _handle_chat_history(request):
    """GET /api/orchestra/chat/history - Retrieve chat message history."""
    from starlette.responses import JSONResponse

    limit = int(request.query_params.get("limit", "100"))
    return JSONResponse({"messages": _chat_history[-limit:]})


@mcp.custom_route("/api/orchestra/runs/{run_id}/output", methods=["GET"])
async def _handle_run_output(request):
    """GET /api/orchestra/runs/{run_id}/output - Get run output."""
    from starlette.responses import JSONResponse

    orchestra = _get_orchestra()
    run_id = request.path_params["run_id"]

    if run_id not in orchestra._runs:
        return JSONResponse({"error": f"Unknown run: {run_id}"}, status_code=404)

    run = orchestra._runs[run_id]
    return JSONResponse({
        "run_id": run.run_id,
        "agent": run.agent,
        "task": run.task,
        "status": run.status.value,
        "output": run.output,
        "error": run.error,
    })
```

**Step 3: Test endpoints manually**

Run: `curl -X POST http://localhost:8001/api/orchestra/chat -H 'Content-Type: application/json' -d '{"message":"hello","workspace":"/tmp"}'`
Expected: JSON response with `message` and `dispatches` keys (may fail if no `ANTHROPIC_API_KEY` — that's expected in container)

Run: `curl http://localhost:8001/api/orchestra/chat/history`
Expected: `{"messages": [...]}`

**Step 4: Commit**

```bash
git add src/server.py tests/test_server_chat.py
git commit -m "feat(orchestra): add chat and run output API endpoints"
```

---

## Task 7: Config API Endpoints

**Files:**
- Modify: `src/server.py` (add routes)

**Step 1: Add config endpoints to server.py**

```python
@mcp.custom_route("/api/config", methods=["GET"])
async def _handle_get_config(request):
    """GET /api/config - Return current agent and MCP configs."""
    from starlette.responses import JSONResponse
    from tools.builtin.agent_config import AgentConfigManager

    manager = AgentConfigManager()
    return JSONResponse({
        "agents": manager.get_all_configs(),
        "workspace_roots": _get_workspace_roots(),
    })


@mcp.custom_route("/api/config", methods=["PUT"])
async def _handle_put_config(request):
    """PUT /api/config - Update agent configs."""
    from starlette.responses import JSONResponse
    from tools.builtin.agent_config import AgentConfigManager

    body = await request.json()
    manager = AgentConfigManager()

    if "agents" in body:
        for agent_name, config in body["agents"].items():
            manager.save_config(agent_name, config)

    return JSONResponse({"status": "updated"})
```

**Step 2: Test endpoints manually**

Run: `curl http://localhost:8001/api/config`
Expected: JSON with `agents` and `workspace_roots` keys

**Step 3: Commit**

```bash
git add src/server.py
git commit -m "feat(orchestra): add config GET/PUT API endpoints"
```

---

## Task 8: Docker Compose - Add Memento Volume Mount

**Files:**
- Modify: `docker-compose.yaml`

**Step 1: Add `~/.memento/` volume mount to mcp-dev service**

Add this line under the `mcp-dev` volumes section:

```yaml
    volumes:
      - ./src:/app/src
      - ${MEMORY_STORAGE_PATH:-~/.claude/memory}:/data/memory
      - ~/.memento:/root/.memento
```

Also add `ANTHROPIC_API_KEY` pass-through to mcp-dev environment:

```yaml
    environment:
      - QDRANT_URL=http://qdrant:6333
      - EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER:-sentence-transformers}
      - MCP_TRANSPORT=streamable-http
      - LOG_LEVEL=DEBUG
      - MEMORY_STORAGE_PATH=/data/memory
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
```

**Step 2: Rebuild and verify**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && docker compose --profile dev build mcp-dev`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add docker-compose.yaml
git commit -m "feat(docker): add memento volume mount and anthropic key passthrough"
```

---

## Task 9: Dashboard Layout Redesign - Center Column Chat

This is the largest task. It modifies the embedded HTML/CSS/JS in `server.py:668+`.

**Files:**
- Modify: `src/server.py` (dashboard HTML at line 668+)

**Step 1: Modify the CSS grid layout**

Replace the current 3-column grid (Tracker | Brain Graph | Briefing+Orchestra) with (Tracker | Chat | Briefing+Config):

Find the CSS rule for `.dashboard` (around line 718-720):
```css
/* OLD */
.dashboard{display:grid;grid-template-columns:320px 1fr 340px;...}

/* NEW */
.dashboard{display:grid;grid-template-columns:320px 1fr 340px;...}
```

The grid columns stay the same dimensions, but the center content changes.

**Step 2: Replace center column HTML**

Replace the brain graph `<canvas>` center column (around line 1095-1115) with the chat interface:

```html
<!-- CENTER: Orchestra Chat -->
<div class="center-column" style="display:flex;flex-direction:column;height:100%;overflow:hidden">
  <div class="chat-messages" id="chat-messages" style="flex:1;overflow-y:auto;padding:12px;">
    <div class="system-message">Welcome to Orchestra. Type a message to start.</div>
  </div>
  <div class="chat-input-bar" style="border-top:1px solid var(--border);padding:8px 12px;display:flex;gap:8px;">
    <textarea id="chat-input" rows="1" placeholder="Ask the orchestrator..." style="flex:1;resize:none;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:var(--mono);font-size:12px;padding:8px;"></textarea>
    <button id="chat-send" style="background:var(--cyan);color:var(--bg);border:none;border-radius:4px;padding:8px 16px;cursor:pointer;font-family:var(--mono);font-weight:700;">SEND</button>
  </div>
</div>
```

**Step 3: Add chat message CSS**

Add to the `<style>` block:

```css
.chat-messages{display:flex;flex-direction:column;gap:8px;}
.chat-msg{padding:8px 12px;border-radius:6px;max-width:85%;word-wrap:break-word;font-size:12px;line-height:1.5;}
.chat-msg.user{align-self:flex-end;background:var(--cyan-dim);border:1px solid rgba(0,212,170,0.3);color:var(--text-bright);}
.chat-msg.assistant{align-self:flex-start;background:var(--surface-2);border:1px solid var(--border);color:var(--text);}
.chat-msg.system-message{align-self:center;color:var(--text-dim);font-size:11px;font-style:italic;}
.agent-run-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:4px 0;}
.agent-run-card .run-header{display:flex;align-items:center;gap:8px;cursor:pointer;}
.agent-run-card .run-status{font-size:10px;padding:2px 6px;border-radius:3px;text-transform:uppercase;}
.agent-run-card .run-status.pending{background:var(--amber-dim);color:var(--amber);}
.agent-run-card .run-status.running{background:var(--cyan-dim);color:var(--cyan);}
.agent-run-card .run-status.completed{background:rgba(52,211,153,0.12);color:var(--green);}
.agent-run-card .run-status.failed{background:var(--red-dim);color:var(--red);}
.agent-run-card .run-status.review{background:rgba(167,139,250,0.12);color:var(--purple);}
.agent-run-card .run-output{display:none;margin-top:8px;padding:8px;background:var(--bg);border-radius:4px;font-size:11px;white-space:pre-wrap;max-height:200px;overflow-y:auto;}
.agent-run-card.expanded .run-output{display:block;}
.agent-run-card .run-actions{display:none;margin-top:8px;gap:8px;}
.agent-run-card.review .run-actions{display:flex;}
```

**Step 4: Add workspace selector to topbar**

In the topbar HTML (around line 1085), add a workspace dropdown after the logo:

```html
<div class="topbar" style="...">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="font-family:var(--display);font-weight:900;font-size:14px;color:var(--cyan);">MEMENTO // Command</span>
    <select id="workspace-select" style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:11px;padding:4px 8px;border-radius:4px;">
      <option value="">Select workspace...</option>
    </select>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    <button id="brain-toggle" style="background:var(--surface-2);border:1px solid var(--border);color:var(--text-dim);font-family:var(--mono);font-size:10px;padding:4px 10px;border-radius:4px;cursor:pointer;">[BRAIN]</button>
    <span id="clock" style="color:var(--text-dim);font-size:11px;"></span>
  </div>
</div>
```

**Step 5: Add brain graph modal overlay**

After the main dashboard div, add:

```html
<div id="brain-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;z-index:1000;">
  <div id="brain-backdrop" style="position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);"></div>
  <div style="position:relative;margin:40px auto;width:80%;height:80%;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;">
    <canvas id="brainCanvas" style="width:100%;height:100%;"></canvas>
  </div>
</div>
```

**Step 6: Commit layout changes**

```bash
git add src/server.py
git commit -m "feat(dashboard): redesign center column as chat interface with workspace selector"
```

---

## Task 10: Dashboard JavaScript - Chat Functionality

**Files:**
- Modify: `src/server.py` (JS section starting around line 1178)

**Step 1: Add chat JavaScript**

Replace the old orchestra dispatch JS with chat functionality:

```javascript
// --- WORKSPACE SELECTOR ---
async function loadWorkspaces() {
  try {
    const res = await fetch('/api/workspaces');
    const data = await res.json();
    const select = document.getElementById('workspace-select');
    select.innerHTML = '<option value="">Select workspace...</option>';
    data.workspaces.forEach(ws => {
      const opt = document.createElement('option');
      opt.value = ws.path;
      opt.textContent = ws.name;
      select.appendChild(opt);
    });
    // Restore last selected from localStorage
    const saved = localStorage.getItem('activeWorkspace');
    if (saved) select.value = saved;
  } catch (e) {
    console.error('Failed to load workspaces:', e);
  }
}

document.getElementById('workspace-select').addEventListener('change', function() {
  localStorage.setItem('activeWorkspace', this.value);
  appendSystemMessage('Workspace changed to: ' + this.value);
});

// --- CHAT ---
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');
let chatHistory = JSON.parse(localStorage.getItem('chatHistory') || '[]');

function appendMessage(role, content) {
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  div.textContent = content;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendSystemMessage(text) {
  const div = document.createElement('div');
  div.className = 'chat-msg system-message';
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendRunCard(dispatch) {
  const card = document.createElement('div');
  card.className = 'agent-run-card';
  card.id = 'run-' + dispatch.run_id;
  card.innerHTML =
    '<div class="run-header" onclick="toggleRunCard(this.parentElement)">' +
      '<span style="color:var(--cyan);font-weight:700;">' + dispatch.agent + '</span> ' +
      '<span class="run-status ' + dispatch.status + '">' + dispatch.status + '</span> ' +
      '<span style="color:var(--text-dim);font-size:11px;">' + dispatch.run_id + '</span>' +
    '</div>' +
    '<div style="font-size:11px;color:var(--text-dim);margin-top:4px;">' + dispatch.task + '</div>' +
    '<div class="run-output">Loading...</div>' +
    '<div class="run-actions">' +
      '<button onclick="reviewRun(\'' + dispatch.run_id + '\',\'approve\')">APPROVE</button>' +
      '<button onclick="reviewRun(\'' + dispatch.run_id + '\',\'reject\')">REJECT</button>' +
    '</div>';
  chatMessages.appendChild(card);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  // Start polling for status
  pollRunStatus(dispatch.run_id);
}

function toggleRunCard(card) {
  card.classList.toggle('expanded');
  if (card.classList.contains('expanded')) {
    loadRunOutput(card.id.replace('run-', ''));
  }
}

async function loadRunOutput(runId) {
  try {
    const res = await fetch('/api/orchestra/runs/' + runId + '/output');
    const data = await res.json();
    const card = document.getElementById('run-' + runId);
    if (card) {
      card.querySelector('.run-output').textContent = data.output || 'No output yet.';
    }
  } catch (e) {
    console.error('Failed to load run output:', e);
  }
}

async function pollRunStatus(runId) {
  const poll = setInterval(async () => {
    try {
      const res = await fetch('/api/orchestra/runs/' + runId + '/output');
      const data = await res.json();
      const card = document.getElementById('run-' + runId);
      if (!card) { clearInterval(poll); return; }
      const badge = card.querySelector('.run-status');
      badge.className = 'run-status ' + data.status;
      badge.textContent = data.status;
      if (data.status === 'review') card.classList.add('review');
      if (['completed', 'failed'].includes(data.status)) {
        clearInterval(poll);
        card.querySelector('.run-output').textContent = data.output || data.error || 'Done.';
      }
    } catch (e) { clearInterval(poll); }
  }, 3000);
}

async function reviewRun(runId, action) {
  try {
    await fetch('/api/orchestra/runs/' + runId + '/review', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: action}),
    });
    appendSystemMessage(runId + ' ' + action + 'd.');
  } catch (e) {
    appendSystemMessage('Failed to ' + action + ' ' + runId);
  }
}

async function sendChat() {
  const msg = chatInput.value.trim();
  if (!msg) return;

  const workspace = document.getElementById('workspace-select').value;
  chatInput.value = '';
  appendMessage('user', msg);

  chatHistory.push({role: 'user', content: msg});

  try {
    const res = await fetch('/api/orchestra/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: msg,
        workspace: workspace,
        history: chatHistory.slice(-20), // Send last 20 messages for context
      }),
    });
    const data = await res.json();

    if (data.error) {
      appendSystemMessage('Error: ' + data.error);
      return;
    }

    appendMessage('assistant', data.message);
    chatHistory.push({role: 'assistant', content: data.message});

    // Render dispatch cards
    if (data.dispatches && data.dispatches.length > 0) {
      data.dispatches.forEach(d => appendRunCard(d));
    }

    // Persist chat history to localStorage
    localStorage.setItem('chatHistory', JSON.stringify(chatHistory.slice(-100)));
  } catch (e) {
    appendSystemMessage('Failed to reach orchestrator: ' + e.message);
  }
}

chatSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

// Auto-expand textarea
chatInput.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// --- BRAIN GRAPH MODAL ---
document.getElementById('brain-toggle').addEventListener('click', function() {
  const modal = document.getElementById('brain-modal');
  modal.style.display = modal.style.display === 'none' ? 'block' : 'none';
  if (modal.style.display === 'block') initBrainGraph();
});

document.getElementById('brain-backdrop').addEventListener('click', function() {
  document.getElementById('brain-modal').style.display = 'none';
});

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.getElementById('brain-modal').style.display = 'none';
  }
});

// Restore chat history on load
chatHistory.forEach(msg => appendMessage(msg.role, msg.content));

// Load workspaces on init
loadWorkspaces();
```

**Step 2: Move brain graph JS into the modal init function**

Wrap the existing brain graph physics/rendering code (lines ~1448-1611) inside an `initBrainGraph()` function so it only runs when the modal opens.

**Step 3: Move orchestra section from right sidebar to remove old dispatch UI**

Remove the old "Agent Orchestra" briefing section (lines 1139-1146) and the old dispatch dialog (lines 1152-1176) from the HTML.

**Step 4: Add config section to right sidebar**

Replace the old orchestra section with:

```html
<div class="briefing-section">
  <div class="briefing-section-title">Config</div>
  <div id="config-panel" style="font-size:11px;">
    <div style="color:var(--text-dim);margin-bottom:6px;">MCPs</div>
    <div id="config-mcps">Loading...</div>
    <div style="color:var(--text-dim);margin:8px 0 6px;">Agent Configs</div>
    <div id="config-agents">Loading...</div>
  </div>
</div>
```

**Step 5: Add config panel JS**

```javascript
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const data = await res.json();

    // Render MCPs
    const mcpDiv = document.getElementById('config-mcps');
    mcpDiv.innerHTML = '';
    Object.entries(data.agents).forEach(([name, cfg]) => {
      if (cfg.mcpServers) {
        Object.keys(cfg.mcpServers).forEach(mcp => {
          mcpDiv.innerHTML += '<div style="margin:2px 0;">' + mcp + ' <span style="color:var(--green);">[active]</span></div>';
        });
      }
    });

    // Render agent configs
    const agentsDiv = document.getElementById('config-agents');
    agentsDiv.innerHTML = '';
    Object.entries(data.agents).forEach(([name, cfg]) => {
      const mcpCount = cfg.mcpServers ? Object.keys(cfg.mcpServers).length : 0;
      agentsDiv.innerHTML += '<div style="margin:2px 0;">' + name + ' <span style="color:var(--text-dim);">[' + mcpCount + ' MCP]</span></div>';
    });
  } catch (e) {
    console.error('Failed to load config:', e);
  }
}

loadConfig();
```

**Step 6: Test the full dashboard**

Open `http://localhost:8001/dashboard` in browser.
Expected:
- Workspace dropdown populated in topbar
- Chat interface in center column
- Brain graph accessible via [BRAIN] toggle
- Config panel in right sidebar
- Messages send and receive (if ANTHROPIC_API_KEY is set in container env)

**Step 7: Commit**

```bash
git add src/server.py
git commit -m "feat(dashboard): add chat JS, workspace selector, brain modal, config panel"
```

---

## Task 11: Run All Tests

**Files:** None (verification only)

**Step 1: Run the full test suite**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/ -v`
Expected: All existing tests + new tests pass

**Step 2: Fix any failures**

If any tests fail, fix the root cause before proceeding.

**Step 3: Run ruff linter**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m ruff check src/ tests/`
Expected: No errors (or only pre-existing ones)

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve test and lint issues from chat redesign"
```

---

## Task 12: Integration Test - Full Chat Flow

**Files:**
- Create: `tests/test_chat_integration.py`

**Step 1: Write integration test**

```python
# tests/test_chat_integration.py
"""Integration test for the full chat orchestration flow."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tools.builtin.chat_orchestrator import ChatOrchestrator


def test_full_chat_dispatch_cycle():
    """Simulate: user message -> orchestrator -> dispatch -> run card."""
    orchestrator = ChatOrchestrator()

    # Mock Claude API to return a response with dispatch intent
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=(
                "I'll research JWT patterns first.\n"
                '<<DISPATCH agent="gemini" task="Research JWT middleware patterns in Go">>'
            )
        )
    ]

    with patch.object(
        orchestrator, "_call_claude_api", new=AsyncMock(return_value=mock_response)
    ):
        with patch(
            "tools.builtin.chat_orchestrator._get_shared_orchestra"
        ) as mock_get_orch:
            mock_orchestra = MagicMock()
            mock_orchestra._dispatch_task = AsyncMock(
                return_value="Dispatched **RUN-001** to **gemini**\nTask: Research JWT\nStatus: pending"
            )
            mock_get_orch.return_value = mock_orchestra

            result = asyncio.run(
                orchestrator.handle_chat(
                    message="Build JWT auth middleware",
                    workspace="/home/user/project",
                    history=[],
                )
            )

    assert "message" in result
    assert "JWT" in result["message"]
    assert len(result["dispatches"]) == 1
    assert result["dispatches"][0]["agent"] == "gemini"
    assert result["dispatches"][0]["run_id"] == "RUN-001"
```

**Step 2: Run integration test**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_chat_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_chat_integration.py
git commit -m "test: add integration test for full chat dispatch cycle"
```

---

## Summary

| Task | Component | New Files | Tests |
|------|-----------|-----------|-------|
| 1 | Anthropic SDK dependency | - | - |
| 2 | Workspace scanner | `workspaces.py` | 5 |
| 3 | Workspace API endpoint | - | 1+ |
| 4 | Agent config manager | `agent_config.py` | 7 |
| 5 | Chat orchestrator | `chat_orchestrator.py` | 6 |
| 6 | Chat API endpoints | - | 2+ |
| 7 | Config API endpoints | - | manual |
| 8 | Docker volume mount | - | - |
| 9 | Dashboard layout redesign | - | visual |
| 10 | Dashboard chat JS | - | visual |
| 11 | Full test suite run | - | all |
| 12 | Integration test | `test_chat_integration.py` | 1 |

**Total new files:** 5 (3 source + 2 test + 1 integration test)
**Total new tests:** ~22
**Estimated commits:** 12
