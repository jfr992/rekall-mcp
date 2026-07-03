"""Tests for memory_detail MCP tool — v2 contract and text rendering.

The tool must delegate to manager.get_memory_detail (not store.get_by_id directly)
and render compact structured text with direction labels and warnings.
"""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FULL_RESULT = {
    "memory": {
        "memory_id": "2026-07-01_decision_abc1",
        "content": "Use PostgreSQL for primary store",
        "type": "decision",
        "project": "rekall-mcp",
    },
    "neighbors": [],
    "scope": {"project": "rekall-mcp", "agent": None, "repo_name": None},
    "relationships": [
        {
            "source_id": "2026-07-01_decision_aaa1",
            "target_id": "2026-07-01_decision_abc1",
            "neighbor_id": "2026-07-01_decision_aaa1",
            "direction": "in",
            "relation": "supersedes",
            "weight": 0.8,
            "auto": True,
            "created": "2026-07-01",
            "memory": None,
        },
        {
            "source_id": "2026-07-01_decision_abc1",
            "target_id": "2026-07-01_fact_bbb2",
            "neighbor_id": "2026-07-01_fact_bbb2",
            "direction": "out",
            "relation": "supersedes",
            "weight": 0.7,
            "auto": True,
            "created": "2026-07-01",
            "memory": {
                "memory_id": "2026-07-01_fact_bbb2",
                "content": "Dependency",
                "type": "fact",
            },
        },
    ],
    "provenance": {
        "agent": "claude-code",
        "source_tool": None,
        "source_event": None,
        "timestamp": None,
        "session_id": None,
        "repo_name": None,
        "branch": None,
        "trust_boundary": None,
    },
    "lifecycle": {
        "tier": "working",
        "durability": 0.65,
        "retention_days": None,
        "lifecycle_reason": None,
    },
    "storage": {"qdrant": True, "yaml": False},
    "warnings": ["scope_mismatch"],
    "missing_neighbor_ids": ["2026-07-01_decision_aaa1"],
}

_NOT_FOUND_RESULT = {
    "memory": None,
    "neighbors": [],
    "scope": None,
    "relationships": [],
    "provenance": None,
    "lifecycle": None,
    "storage": {"qdrant": False, "yaml": False},
    "warnings": [],
}


# ---------------------------------------------------------------------------
# Tests for _render_memory_detail helper
# ---------------------------------------------------------------------------


def test_render_memory_detail_contains_direction_labels():
    """_render_memory_detail includes '<- superseded by' for in-edge and '-> supersedes' for out."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "<- superseded by" in text, "in-edge supersedes must render as '<- superseded by'"
    assert "-> supersedes" in text, "out-edge supersedes must render as '-> supersedes'"


def test_render_memory_detail_contains_warnings():
    """_render_memory_detail includes warning codes in output."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "scope_mismatch" in text, "warnings must appear in rendered output"


def test_render_memory_detail_contains_missing_neighbor_ids():
    """_render_memory_detail includes missing neighbor ids."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "2026-07-01_decision_aaa1" in text, "missing neighbor id must appear in output"


def test_render_memory_detail_null_fields_shown_as_unknown():
    """Null provenance/lifecycle fields render as 'unknown', not 'None'."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "None" not in text, "Python None must not appear; use 'unknown' instead"
    assert "unknown" in text, "null fields must render as 'unknown'"


def test_render_memory_detail_content_appears():
    """Content block appears in rendered text."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "Use PostgreSQL for primary store" in text


# ---------------------------------------------------------------------------
# Tests for the MCP tool delegating to manager.get_memory_detail
# ---------------------------------------------------------------------------


def _make_tool_provider_with_manager(manager):
    """Build a MemoryToolProvider wired to a mock manager (no MCP server needed)."""
    from tools.builtin.memory import MemoryToolProvider

    provider = MagicMock(spec=MemoryToolProvider)
    provider.manager = manager
    return provider


def test_mcp_tool_delegates_to_get_memory_detail():
    """memory_detail MCP tool must call manager.get_memory_detail, not store.get_by_id."""
    import asyncio

    from tools.builtin.memory import _make_memory_detail_fn

    manager = MagicMock()
    manager.get_memory_detail.return_value = _FULL_RESULT

    fn = _make_memory_detail_fn(manager)
    result = asyncio.run(fn("2026-07-01_decision_abc1"))

    manager.get_memory_detail.assert_called_once_with("2026-07-01_decision_abc1")
    assert "<- superseded by" in result
    assert "scope_mismatch" in result


def test_mcp_tool_not_found_contract():
    """memory_detail returns 'Memory not found: <id>' when memory is None."""
    import asyncio

    from tools.builtin.memory import _make_memory_detail_fn

    manager = MagicMock()
    manager.get_memory_detail.return_value = _NOT_FOUND_RESULT

    fn = _make_memory_detail_fn(manager)
    result = asyncio.run(fn("nonexistent_id_xxx"))

    assert result == "Memory not found: nonexistent_id_xxx"
