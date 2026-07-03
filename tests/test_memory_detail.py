"""Unit tests for /api/memory/detail/{memory_id} contract v2.

Tests the new relationships / provenance / lifecycle / storage / warnings fields.
All tests monkeypatch _get_memory_manager so no real Qdrant is required.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.responses import JSONResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class PathParams:
    def __init__(self, values: dict):
        self._values = values

    def __getitem__(self, key: str):
        return self._values[key]


class QueryParams:
    def __init__(self, values: dict):
        self._values = values

    def get(self, key: str, default=None):
        return self._values.get(key, default)


def _make_request(memory_id: str, query: dict | None = None):
    return SimpleNamespace(
        path_params=PathParams({"memory_id": memory_id}),
        query_params=QueryParams(query or {}),
    )


def _payload(response: JSONResponse) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Fixture: a memory payload with full provenance + lifecycle
# ---------------------------------------------------------------------------

FULL_MEMORY = {
    "memory_id": "2026-07-01_decision_abc1",
    "content": "Use PostgreSQL for primary store",
    "type": "decision",
    "project": "rekall-mcp",
    # provenance
    "agent": "claude-code",
    "source_tool": "save_memory",
    "source_event": "PostToolUse",
    "timestamp": "2026-07-01T10:00:00",
    "session_id": "sess-xyz",
    "repo_name": "rekall-mcp",
    "repo_remote": "https://github.com/example/rekall-mcp",
    "branch": "main",
    "trust_boundary": "public",
    # lifecycle
    "tier": "working",
    "durability": 0.65,
    "retention_days": 90,
    "lifecycle_reason": "default for decision",
    "reinforcement_count": 0,
}

SPARSE_MEMORY = {
    "memory_id": "2026-07-01_note_def2",
    "content": "Some note without provenance",
    "type": "note",
    "project": "rekall-mcp",
    # no agent / source_tool / source_event
    # no durability / lifecycle_reason
}


# ---------------------------------------------------------------------------
# 1. Relationships — both incoming and outgoing edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_relationships_include_both_directions(monkeypatch):
    """Selected memory with incoming + outgoing edges must appear in relationships."""
    from server import api_memory_detail

    selected_id = FULL_MEMORY["memory_id"]
    node_a_id = "2026-07-01_decision_aaa1"  # supersedes → selected (incoming)
    node_b_id = "2026-07-01_fact_bbb2"  # selected → depends_on (outgoing)
    node_c_id = "2026-07-01_learning_ccc3"  # contradicts → selected (incoming)

    node_a = {
        "memory_id": node_a_id,
        "content": "Superseder",
        "type": "decision",
        "project": "rekall-mcp",
    }
    node_b = {
        "memory_id": node_b_id,
        "content": "Dependency",
        "type": "fact",
        "project": "rekall-mcp",
    }
    node_c = {
        "memory_id": node_c_id,
        "content": "Contradictor",
        "type": "learning",
        "project": "rekall-mcp",
    }

    expected_detail = {
        "memory": FULL_MEMORY,
        "neighbors": [
            {"relation": "depends_on", "memory": node_b},  # outgoing only
        ],
        "scope": {
            "project": "rekall-mcp",
            "agent": "claude-code",
            "repo_name": "rekall-mcp",
        },
        "relationships": [
            {
                "source_id": node_a_id,
                "target_id": selected_id,
                "neighbor_id": node_a_id,
                "direction": "in",
                "relation": "supersedes",
                "weight": 0.8,
                "auto": True,
                "created": "2026-07-01",
                "memory": node_a,
            },
            {
                "source_id": selected_id,
                "target_id": node_b_id,
                "neighbor_id": node_b_id,
                "direction": "out",
                "relation": "depends_on",
                "weight": 0.7,
                "auto": True,
                "created": "2026-07-01",
                "memory": node_b,
            },
            {
                "source_id": node_c_id,
                "target_id": selected_id,
                "neighbor_id": node_c_id,
                "direction": "in",
                "relation": "contradicts",
                "weight": 0.6,
                "auto": True,
                "created": "2026-07-01",
                "memory": node_c,
            },
        ],
        "provenance": {
            "agent": "claude-code",
            "source_tool": "save_memory",
            "source_event": "PostToolUse",
            "timestamp": "2026-07-01T10:00:00",
            "session_id": "sess-xyz",
            "repo_name": "rekall-mcp",
            "repo_remote": "https://github.com/example/rekall-mcp",
            "branch": "main",
            "trust_boundary": "public",
        },
        "lifecycle": {
            "tier": "working",
            "durability": 0.65,
            "retention_days": 90,
            "lifecycle_reason": "default for decision",
        },
        "storage": {"qdrant": True, "yaml": False},
        "warnings": [],
    }

    manager = MagicMock()
    manager.get_memory_detail.return_value = expected_detail
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_detail(_make_request(selected_id))
    assert isinstance(response, JSONResponse)

    body = _payload(response)
    # New fields must be present
    assert "relationships" in body, "relationships field missing from response"
    assert "provenance" in body, "provenance field missing from response"
    assert "lifecycle" in body, "lifecycle field missing from response"
    assert "storage" in body, "storage field missing from response"
    assert "warnings" in body, "warnings field missing from response"

    # relationships count: all 3 edges (2 incoming + 1 outgoing)
    assert len(body["relationships"]) == 3

    directions = {r["direction"] for r in body["relationships"]}
    assert "in" in directions, "no incoming relationships found"
    assert "out" in directions, "no outgoing relationships found"

    # neighbors compat alias: outgoing only
    assert "neighbors" in body, "neighbors compat alias missing"
    assert len(body["neighbors"]) == 1
    assert body["neighbors"][0]["relation"] == "depends_on"

    # manager called with memory_id, no current_project
    manager.get_memory_detail.assert_called_once_with(selected_id, current_project=None)


@pytest.mark.asyncio
async def test_detail_relationships_fields_per_edge(monkeypatch):
    """Each relationship entry must carry all required fields."""
    from server import api_memory_detail

    selected_id = FULL_MEMORY["memory_id"]
    neighbor_id = "2026-07-01_fact_bbb2"
    neighbor = {
        "memory_id": neighbor_id,
        "content": "Some fact",
        "type": "fact",
        "project": "rekall-mcp",
    }

    relationship = {
        "source_id": selected_id,
        "target_id": neighbor_id,
        "neighbor_id": neighbor_id,
        "direction": "out",
        "relation": "depends_on",
        "weight": 0.75,
        "auto": True,
        "created": "2026-07-01",
        "memory": neighbor,
    }
    result = {
        "memory": FULL_MEMORY,
        "neighbors": [{"relation": "depends_on", "memory": neighbor}],
        "scope": {"project": "rekall-mcp", "agent": "claude-code", "repo_name": "rekall-mcp"},
        "relationships": [relationship],
        "provenance": {},
        "lifecycle": {},
        "storage": {"qdrant": True, "yaml": False},
        "warnings": [],
    }

    manager = MagicMock()
    manager.get_memory_detail.return_value = result
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_detail(_make_request(selected_id))
    body = _payload(response)

    required_edge_keys = {
        "source_id",
        "target_id",
        "neighbor_id",
        "direction",
        "relation",
        "weight",
        "auto",
        "created",
        "memory",
    }
    assert required_edge_keys.issubset(body["relationships"][0].keys())


# ---------------------------------------------------------------------------
# 2. Provenance and lifecycle — nulls when absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_provenance_nulls_when_fields_absent(monkeypatch):
    """Provenance exposes null for any field not present in memory payload."""
    from server import api_memory_detail

    memory_id = SPARSE_MEMORY["memory_id"]
    result = {
        "memory": SPARSE_MEMORY,
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
            "repo_remote": None,
            "branch": None,
            "trust_boundary": None,
        },
        "lifecycle": {
            "tier": None,
            "durability": None,
            "retention_days": None,
            "lifecycle_reason": None,
        },
        "storage": {"qdrant": True, "yaml": False},
        "warnings": ["missing_provenance", "missing_lifecycle"],
    }

    manager = MagicMock()
    manager.get_memory_detail.return_value = result
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_detail(_make_request(memory_id))
    body = _payload(response)

    assert body["provenance"]["agent"] is None
    assert body["provenance"]["source_tool"] is None
    assert body["lifecycle"]["durability"] is None
    assert body["lifecycle"]["lifecycle_reason"] is None
    assert "missing_provenance" in body["warnings"]
    assert "missing_lifecycle" in body["warnings"]


# ---------------------------------------------------------------------------
# 3. Missing memory — backward compat contract unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_missing_memory_contract(monkeypatch):
    """Not-found memory must return memory=null, neighbors=[], scope=null."""
    from server import api_memory_detail

    not_found_result = {
        "memory": None,
        "neighbors": [],
        "scope": None,
        "relationships": [],
        "provenance": None,
        "lifecycle": None,
        "storage": {"qdrant": False, "yaml": False},
        "warnings": [],
    }

    manager = MagicMock()
    manager.get_memory_detail.return_value = not_found_result
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_detail(_make_request("nonexistent_id_xxx"))
    body = _payload(response)

    assert body["memory"] is None
    assert body["neighbors"] == []
    assert body["scope"] is None


# ---------------------------------------------------------------------------
# 4. Warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_scope_mismatch_warning_passed_to_manager(monkeypatch):
    """?current_project= must be forwarded to manager.get_memory_detail."""
    from server import api_memory_detail

    memory_id = FULL_MEMORY["memory_id"]
    manager = MagicMock()
    manager.get_memory_detail.return_value = {
        "memory": FULL_MEMORY,
        "neighbors": [],
        "scope": {"project": "rekall-mcp", "agent": None, "repo_name": None},
        "relationships": [],
        "provenance": {},
        "lifecycle": {},
        "storage": {"qdrant": True, "yaml": False},
        "warnings": ["scope_mismatch"],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_detail(
        _make_request(memory_id, query={"current_project": "other-project"})
    )
    body = _payload(response)

    # current_project forwarded to manager
    manager.get_memory_detail.assert_called_once_with(memory_id, current_project="other-project")
    assert "scope_mismatch" in body["warnings"]


@pytest.mark.asyncio
async def test_detail_missing_index_warning(monkeypatch):
    """YAML-only memory (not in Qdrant) produces missing_index warning."""
    from server import api_memory_detail

    memory_id = FULL_MEMORY["memory_id"]
    manager = MagicMock()
    manager.get_memory_detail.return_value = {
        "memory": FULL_MEMORY,
        "neighbors": [],
        "scope": {"project": "rekall-mcp", "agent": "claude-code", "repo_name": "rekall-mcp"},
        "relationships": [],
        "provenance": {"agent": "claude-code"},
        "lifecycle": {"tier": "working", "durability": 0.65},
        "storage": {"qdrant": False, "yaml": True},
        "warnings": ["missing_index"],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_detail(_make_request(memory_id))
    body = _payload(response)

    assert body["storage"]["qdrant"] is False
    assert body["storage"]["yaml"] is True
    assert "missing_index" in body["warnings"]


# ---------------------------------------------------------------------------
# 5. MemoryManager.get_memory_detail — unit tests with mocked store + graph
# ---------------------------------------------------------------------------


def _make_mock_graph(edges):
    """Return a mock KnowledgeGraph that yields the given edge list."""
    graph = MagicMock()
    graph.stats.return_value = {"nodes": len(edges)}
    graph.get_edges.return_value = edges
    return graph


def _make_mock_store(by_id_map: dict):
    """Return a mock VectorStore that resolves get_by_id from a dict."""
    store = MagicMock()
    store.get_by_id.side_effect = lambda mid: by_id_map.get(mid)
    return store


def test_manager_get_memory_detail_both_directions():
    """get_memory_detail returns relationships for both incoming and outgoing edges."""
    from memory.knowledge_graph import Edge
    from memory.manager import MemoryManager

    selected_id = "2026-07-01_decision_abc1"
    node_a_id = "2026-07-01_decision_aaa1"
    node_b_id = "2026-07-01_fact_bbb2"

    selected = {**FULL_MEMORY, "memory_id": selected_id}
    node_a = {"memory_id": node_a_id, "content": "A", "type": "decision", "project": "rekall-mcp"}
    node_b = {"memory_id": node_b_id, "content": "B", "type": "fact", "project": "rekall-mcp"}

    edges = [
        # node_a → selected (incoming supersedes)
        Edge(source=node_a_id, target=selected_id, relation="supersedes", weight=0.8),
        # selected → node_b (outgoing depends_on)
        Edge(source=selected_id, target=node_b_id, relation="depends_on", weight=0.7),
    ]

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({selected_id: selected, node_a_id: node_a, node_b_id: node_b})
    mgr.knowledge_graph = _make_mock_graph(edges)
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, selected_id)

    assert result["memory"] == selected
    assert result["storage"]["qdrant"] is True

    rels = result["relationships"]
    assert len(rels) == 2

    in_rels = [r for r in rels if r["direction"] == "in"]
    out_rels = [r for r in rels if r["direction"] == "out"]
    assert len(in_rels) == 1
    assert len(out_rels) == 1
    assert in_rels[0]["relation"] == "supersedes"
    assert in_rels[0]["neighbor_id"] == node_a_id
    assert out_rels[0]["relation"] == "depends_on"
    assert out_rels[0]["neighbor_id"] == node_b_id

    # neighbors compat: outgoing only
    assert len(result["neighbors"]) == 1
    assert result["neighbors"][0]["relation"] == "depends_on"

    # knowledge_graph.get_edges called with direction="both"
    mgr.knowledge_graph.get_edges.assert_called_once_with(selected_id, direction="both")


def test_manager_get_memory_detail_provenance_and_lifecycle():
    """get_memory_detail extracts provenance and lifecycle; nulls for missing fields."""
    from memory.manager import MemoryManager

    memory_id = SPARSE_MEMORY["memory_id"]
    sparse = {**SPARSE_MEMORY}

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: sparse})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id)

    prov = result["provenance"]
    assert prov["agent"] is None
    assert prov["source_tool"] is None
    assert prov["source_event"] is None

    lc = result["lifecycle"]
    assert lc["durability"] is None
    assert lc["lifecycle_reason"] is None

    assert "missing_provenance" in result["warnings"]
    assert "missing_lifecycle" in result["warnings"]


def test_manager_get_memory_detail_scope_mismatch_warning():
    """scope_mismatch warning when current_project differs from memory.project."""
    from memory.manager import MemoryManager

    memory_id = FULL_MEMORY["memory_id"]
    memory = {**FULL_MEMORY}

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id, current_project="different-project")
    assert "scope_mismatch" in result["warnings"]

    result_no_warn = MemoryManager.get_memory_detail(mgr, memory_id, current_project="rekall-mcp")
    assert "scope_mismatch" not in result_no_warn["warnings"]


def test_manager_get_memory_detail_yaml_fallback_missing_index():
    """YAML fallback sets storage.yaml=True, storage.qdrant=False, missing_index warning."""
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock

    import yaml

    from memory.manager import MemoryManager

    memory_id = "2026-07-01_note_yaml1"
    yaml_memory = {
        "memory_id": memory_id,
        "content": "YAML-only note",
        "type": "note",
        "project": "rekall-mcp",
        "agent": "claude-code",
        "source_tool": "save_memory",
        "durability": 0.5,
        "lifecycle_reason": "default for note",
    }

    mgr = MagicMock(spec=MemoryManager)
    # Qdrant returns nothing
    mgr.store = _make_mock_store({})
    mgr.knowledge_graph = _make_mock_graph([])
    # Route _find_in_yaml through the real implementation so it reads memory_dir
    mgr._find_in_yaml = lambda mid: MemoryManager._find_in_yaml(mgr, mid)

    # YAML rglob finds a file containing the memory
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "2026-07-01.yaml"
        yaml_path.write_text(
            yaml.dump({"date": "2026-07-01", "notes": [yaml_memory]}),
            encoding="utf-8",
        )
        mgr.memory_dir = MagicMock()
        mgr.memory_dir.rglob.return_value = [yaml_path]

        result = MemoryManager.get_memory_detail(mgr, memory_id)

    assert result["storage"]["qdrant"] is False
    assert result["storage"]["yaml"] is True
    assert "missing_index" in result["warnings"]
    assert result["memory"]["memory_id"] == memory_id


def test_manager_get_memory_detail_missing_neighbor_ids():
    """Edges pointing to unavailable memories populate missing_neighbor_ids."""
    from memory.knowledge_graph import Edge
    from memory.manager import MemoryManager

    selected_id = "2026-07-01_decision_abc1"
    ghost_id = "2026-07-01_fact_ghost99"

    selected = {**FULL_MEMORY, "memory_id": selected_id}

    edges = [Edge(source=selected_id, target=ghost_id, relation="depends_on", weight=0.5)]

    mgr = MagicMock(spec=MemoryManager)
    # ghost neighbor not in store
    mgr.store = _make_mock_store({selected_id: selected})
    mgr.knowledge_graph = _make_mock_graph(edges)
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, selected_id)

    assert "missing_neighbor_ids" in result
    assert ghost_id in result["missing_neighbor_ids"]
    # The relationship entry still exists but with memory=null
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["memory"] is None


# ---------------------------------------------------------------------------
# 7. Provenance — credential stripping and None preservation
# ---------------------------------------------------------------------------


def test_manager_provenance_strips_repo_remote_creds():
    """repo_remote in provenance must have user:token@ stripped."""
    from memory.manager import MemoryManager

    memory_id = "2026-07-01_decision_credtest"
    memory = {
        "memory_id": memory_id,
        "content": "test",
        "type": "decision",
        "project": "rekall-mcp",
        "repo_remote": "https://user:tok3n@github.com/x/y.git",
        "agent": "claude-code",
        "durability": 0.5,
        "lifecycle_reason": "test",
    }

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id)

    assert "tok3n" not in (result["provenance"]["repo_remote"] or "")
    assert result["provenance"]["repo_remote"] == "https://github.com/x/y.git"


def test_manager_provenance_repo_remote_none_stays_none():
    """repo_remote absent in memory must remain None, not become empty string."""
    from memory.manager import MemoryManager

    memory_id = "2026-07-01_decision_norepo"
    memory = {
        "memory_id": memory_id,
        "content": "test",
        "type": "decision",
        "project": "rekall-mcp",
        # repo_remote intentionally absent
        "agent": "claude-code",
        "durability": 0.5,
        "lifecycle_reason": "test",
    }

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id)

    assert result["provenance"]["repo_remote"] is None


# ---------------------------------------------------------------------------
# 8. Warnings — is-None discipline for missing_lifecycle
# ---------------------------------------------------------------------------


def test_manager_durability_zero_not_missing_lifecycle():
    """durability=0.0 is a valid value; missing_lifecycle must NOT fire."""
    from memory.manager import MemoryManager

    memory_id = "2026-07-01_note_dur0"
    memory = {
        "memory_id": memory_id,
        "content": "test",
        "type": "note",
        "project": "rekall-mcp",
        "agent": "claude-code",
        "durability": 0.0,
        # lifecycle_reason absent
    }

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id)

    assert "missing_lifecycle" not in result["warnings"]


def test_manager_lifecycle_both_none_warns():
    """When both durability and lifecycle_reason are absent, missing_lifecycle IS added."""
    from memory.manager import MemoryManager

    memory_id = "2026-07-01_note_nolc"
    memory = {
        "memory_id": memory_id,
        "content": "test",
        "type": "note",
        "project": "rekall-mcp",
        "agent": "claude-code",
        # no durability, no lifecycle_reason
    }

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id)

    assert "missing_lifecycle" in result["warnings"]


# ---------------------------------------------------------------------------
# Fix 1: _find_in_yaml key matching — production shape uses "id", not "memory_id"
# ---------------------------------------------------------------------------


def test_find_in_yaml_matches_production_id_key():
    """_find_in_yaml finds entries stored with 'id' key (production shape from _save_to_file)."""
    import tempfile
    from pathlib import Path

    import yaml

    from memory.manager import MemoryManager

    memory_id = "2026-07-01_decision_idkey1"
    # Production shape: _save_to_file stores "id" not "memory_id"
    yaml_entry = {
        "id": memory_id,
        "content": "production shape entry",
        "type": "decision",
        "project": "rekall-mcp",
    }

    mgr = MagicMock(spec=MemoryManager)

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "2026-07-01.yaml"
        yaml_path.write_text(
            yaml.dump({"date": "2026-07-01", "decisions": [yaml_entry]}),
            encoding="utf-8",
        )
        mgr.memory_dir = MagicMock()
        mgr.memory_dir.rglob.return_value = [yaml_path]

        found = MemoryManager._find_in_yaml(mgr, memory_id)

    assert found is not None, "_find_in_yaml must find entries stored with 'id' key"
    assert found.get("id") == memory_id or found.get("memory_id") == memory_id


def test_find_in_yaml_tolerates_legacy_memory_id_key():
    """_find_in_yaml also finds entries stored with legacy 'memory_id' key."""
    import tempfile
    from pathlib import Path

    import yaml

    from memory.manager import MemoryManager

    memory_id = "2026-07-01_note_legacykey1"
    # Legacy shape: stored with "memory_id" key
    yaml_entry = {
        "memory_id": memory_id,
        "content": "legacy shape entry",
        "type": "note",
        "project": "rekall-mcp",
    }

    mgr = MagicMock(spec=MemoryManager)

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "2026-07-01.yaml"
        yaml_path.write_text(
            yaml.dump({"date": "2026-07-01", "notes": [yaml_entry]}),
            encoding="utf-8",
        )
        mgr.memory_dir = MagicMock()
        mgr.memory_dir.rglob.return_value = [yaml_path]

        found = MemoryManager._find_in_yaml(mgr, memory_id)

    assert found is not None, "_find_in_yaml must still find entries with 'memory_id' key"


# ---------------------------------------------------------------------------
# Fix 2: storage.yaml must reflect YAML presence even when Qdrant hit
# ---------------------------------------------------------------------------


def test_manager_get_memory_detail_yaml_true_when_qdrant_hit_and_yaml_present():
    """storage.yaml=True when memory is found in both Qdrant and YAML."""
    import tempfile
    from pathlib import Path

    import yaml

    from memory.manager import MemoryManager

    memory_id = "2026-07-01_decision_both1"
    memory = {
        "id": memory_id,
        "content": "both stores present",
        "type": "decision",
        "project": "rekall-mcp",
        "agent": "claude-code",
        "durability": 0.7,
        "lifecycle_reason": "test",
    }

    mgr = MagicMock(spec=MemoryManager)
    # Qdrant has the memory
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr._find_in_yaml = lambda mid: MemoryManager._find_in_yaml(mgr, mid)

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "2026-07-01.yaml"
        yaml_path.write_text(
            yaml.dump({"date": "2026-07-01", "decisions": [memory]}),
            encoding="utf-8",
        )
        mgr.memory_dir = MagicMock()
        mgr.memory_dir.rglob.return_value = [yaml_path]

        result = MemoryManager.get_memory_detail(mgr, memory_id)

    # Both stores present — yaml must be True even though qdrant hit
    assert result["storage"]["qdrant"] is True, "qdrant must be True"
    assert result["storage"]["yaml"] is True, "yaml must be True when memory exists in YAML"
    assert "missing_index" not in result["warnings"], "no missing_index when qdrant also has it"


def test_manager_get_memory_detail_yaml_false_when_qdrant_hit_not_in_yaml():
    """storage.yaml=False when memory is in Qdrant but not in any YAML file."""
    from memory.manager import MemoryManager

    memory_id = "2026-07-01_decision_qdrantonly1"
    memory = {
        "id": memory_id,
        "content": "qdrant only",
        "type": "decision",
        "project": "rekall-mcp",
        "agent": "claude-code",
        "durability": 0.7,
        "lifecycle_reason": "test",
    }

    mgr = MagicMock(spec=MemoryManager)
    mgr.store = _make_mock_store({memory_id: memory})
    mgr.knowledge_graph = _make_mock_graph([])
    mgr._find_in_yaml = lambda mid: MemoryManager._find_in_yaml(mgr, mid)
    # No YAML files
    mgr.memory_dir = MagicMock()
    mgr.memory_dir.rglob.return_value = []

    result = MemoryManager.get_memory_detail(mgr, memory_id)

    assert result["storage"]["qdrant"] is True
    assert result["storage"]["yaml"] is False
