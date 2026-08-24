"""Contract tests for the MCP client instructions."""

import importlib


def test_mcp_instructions_are_conservative_and_bounded() -> None:
    server = importlib.import_module("server")
    instructions = server.MCP_INSTRUCTIONS

    assert len(instructions) <= 1200
    first_window = instructions[:512]
    for name in ("agent_startup", "recall_memories", "observe", "untrusted"):
        assert name in first_window
    assert server.mcp.instructions == instructions
    assert "evidence" in instructions.lower()
    assert "instruction" in instructions.lower()
    assert "never" in instructions.lower() or "do not" in instructions.lower()
    assert server.mcp._mcp_server.instructions == instructions


def test_mcp_instructions_do_not_claim_native_memory_authority() -> None:
    server = importlib.import_module("server")
    instructions = server.MCP_INSTRUCTIONS.lower()

    assert "override" not in instructions
    assert "system prompt" not in instructions
    assert "untrusted" in instructions


def test_mcp_instructions_define_conservative_call_policy() -> None:
    server = importlib.import_module("server")
    instructions = server.MCP_INSTRUCTIONS.lower()

    assert "use agent_startup only when broad project continuity" in instructions
    assert "pass project explicitly" in instructions
    assert "use recall_memories only when history can change the work" in instructions
    assert "use observe only for explicit requests or durable evidence" in instructions
    assert "claude" not in instructions
    assert "codex" not in instructions
