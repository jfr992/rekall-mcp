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

# Legacy memory: all provenance null, no lifecycle_reason, healthy storage.
# Nothing here should render as "unknown" — absence is omitted, not displayed.
_LEGACY_RESULT = {
    "memory": {
        "memory_id": "2025-01-01_note_legacy1",
        "content": "A memory saved before provenance tracking existed",
        "type": "note",
        "project": "rekall-mcp",
    },
    "neighbors": [],
    "scope": {"project": "rekall-mcp", "agent": None, "repo_name": None},
    "relationships": [],
    "provenance": {
        "agent": None,
        "source_tool": None,
        "source_event": None,
        "timestamp": None,
        "session_id": None,
        "repo_name": None,
        "branch": None,
        "trust_boundary": None,
    },
    "lifecycle": {
        "tier": "semantic",
        "durability": 0.4,
        "retention_days": None,
        "lifecycle_reason": None,
    },
    "storage": {"qdrant": True, "yaml": True},
    "warnings": ["missing_provenance"],
}

# Degraded storage: not indexed in Qdrant. Storage line must render, labeled.
_DEGRADED_STORAGE_RESULT = {
    "memory": {
        "memory_id": "2026-07-01_note_degraded1",
        "content": "YAML-only memory",
        "type": "note",
        "project": "rekall-mcp",
    },
    "neighbors": [],
    "scope": {"project": "rekall-mcp", "agent": "claude-code", "repo_name": None},
    "relationships": [],
    "provenance": {
        "agent": "claude-code",
        "source_tool": "save_memory",
        "source_event": None,
        "timestamp": None,
        "session_id": None,
        "repo_name": None,
        "branch": None,
        "trust_boundary": None,
    },
    "lifecycle": {
        "tier": "working",
        "durability": 0.5,
        "retention_days": None,
        "lifecycle_reason": "default for note",
    },
    "storage": {"qdrant": False, "yaml": True},
    "warnings": ["missing_index"],
}

# Fresh memory: full provenance including agent/source_tool, healthy storage.
_FRESH_RESULT = {
    "memory": {
        "memory_id": "2026-07-15_decision_fresh1",
        "content": "Use Qdrant for the vector store",
        "type": "decision",
        "project": "rekall-mcp",
    },
    "neighbors": [],
    "scope": {"project": "rekall-mcp", "agent": "claude-code", "repo_name": "rekall-mcp"},
    "relationships": [],
    "provenance": {
        "agent": "claude-code",
        "source_tool": "save_memory",
        "source_event": "PostToolUse",
        "timestamp": "2026-07-15T10:00:00",
        "session_id": "sess-fresh",
        "repo_name": "rekall-mcp",
        "branch": "main",
        "trust_boundary": "public",
    },
    "lifecycle": {
        "tier": "working",
        "durability": 0.7,
        "retention_days": 90,
        "lifecycle_reason": "default for decision",
    },
    "storage": {"qdrant": True, "yaml": True},
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


def test_render_memory_detail_null_fields_omitted_not_unknown():
    """Null provenance/lifecycle fields are omitted entirely — never 'None', never 'unknown'.

    Slim pin (rev-2): absence is hidden from display, not shown as filler.
    """
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "None" not in text, "Python None must not appear"
    assert "unknown" not in text, "absent fields must be omitted, not rendered as 'unknown'"


def test_render_memory_detail_content_appears():
    """Content block appears in rendered text."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FULL_RESULT)
    assert "Use PostgreSQL for primary store" in text


def test_render_memory_detail_legacy_memory_has_no_unknown_strings():
    """Legacy memory (all-null provenance) renders no 'unknown' strings anywhere."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_LEGACY_RESULT)
    assert "unknown" not in text
    assert "None" not in text


def test_render_memory_detail_legacy_memory_omits_trust_boundary():
    """trust_boundary is never rendered, even as a labeled-absent line."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_LEGACY_RESULT)
    assert "trust" not in text.lower()


def test_render_memory_detail_legacy_memory_omits_lifecycle_reason():
    """lifecycle_reason is dropped from the rendered surface (still lives in the response dict)."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_LEGACY_RESULT)
    assert "reason" not in text.lower()


def test_render_memory_detail_legacy_memory_omits_storage_when_healthy():
    """Healthy storage (qdrant=True, yaml=True) renders no storage lines at all."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_LEGACY_RESULT)
    assert "storage" not in text.lower()
    assert "indexed" not in text.lower()
    assert "persisted" not in text.lower()


def test_render_memory_detail_degraded_storage_renders_qdrant_missing_line():
    """Degraded storage (qdrant=False) keeps a labeled storage line."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_DEGRADED_STORAGE_RESULT)
    assert "storage" in text.lower()
    assert "qdrant" in text.lower()


def test_render_memory_detail_fresh_memory_renders_agent_and_source_tool():
    """Fresh memory with real provenance renders agent/source_tool values."""
    from tools.builtin.memory import _render_memory_detail

    text = _render_memory_detail(_FRESH_RESULT)
    assert "claude-code" in text
    assert "save_memory" in text


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
