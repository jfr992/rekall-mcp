"""Tests for agent config manager."""

from __future__ import annotations

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
    assert "TDD" in template
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

    manager2 = AgentConfigManager(config_dir=tmp_path)
    loaded = manager2.get_config("codex")
    assert loaded["mcpServers"]["memento"]["url"] == "http://custom:8001/mcp"


def test_unknown_agent_returns_none():
    """Unknown agent name returns None."""
    manager = AgentConfigManager()
    assert manager.get_config("nonexistent") is None
