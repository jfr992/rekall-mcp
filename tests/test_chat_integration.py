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
