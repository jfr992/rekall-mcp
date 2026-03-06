"""Tests for chat orchestrator."""

from __future__ import annotations

import asyncio
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
    intents = orchestrator.parse_dispatch_intents("Here's my analysis of the architecture...")
    assert intents == []


def test_parse_dispatch_intents_with_dispatch_block():
    """Response with DISPATCH blocks yields parsed intents."""
    orchestrator = ChatOrchestrator()
    response = (
        "I'll break this down:\n\n"
        '<<DISPATCH agent="codex" task="Implement login endpoint">>\n'
        '<<DISPATCH agent="gemini" task="Research JWT patterns">>'
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

    with patch.object(
        orchestrator, "_call_claude_api", new=AsyncMock(return_value=mock_response)
    ):
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

    with patch.object(
        orchestrator, "_call_claude_api", new=AsyncMock(return_value=mock_response)
    ):
        with patch.object(
            orchestrator,
            "_execute_dispatch",
            new=AsyncMock(return_value={"run_id": "RUN-001", "agent": "gemini", "status": "pending", "task":"Research JWT"}),
        ):
            result = asyncio.run(
                orchestrator.handle_chat(
                    message="Research JWT auth",
                    workspace="/tmp",
                    history=[],
                )
            )

    assert "dispatches" in result
    assert len(result["dispatches"]) == 1
