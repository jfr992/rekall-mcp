from unittest.mock import MagicMock

import pytest
import yaml


def test_doctor_detects_yaml_qdrant_drift(tmp_path):
    from memory.doctor import run_memory_doctor

    project_dir = tmp_path / "byte-edge"
    project_dir.mkdir()
    (project_dir / "2026-07-03.yaml").write_text(
        yaml.dump(
            {
                "date": "2026-07-03",
                "learnings": [
                    {"id": "m_yaml_only", "content": "Only in YAML", "project": "byte-edge"}
                ],
            }
        )
    )

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [
                {"memory_id": "m_qdrant_only", "content": "Only in Qdrant", "project": "byte-edge"}
            ]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 0, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    report = run_memory_doctor(manager, project="byte-edge")

    assert report["status"] == "degraded"
    assert "m_yaml_only" in report["missing_from_qdrant"]
    assert "m_qdrant_only" in report["missing_from_yaml"]


def test_doctor_filters_legacy_flat_yaml_by_embedded_project(tmp_path):
    from memory.doctor import run_memory_doctor

    (tmp_path / "2026-07-03.yaml").write_text(
        yaml.dump(
            {
                "date": "2026-07-03",
                "learnings": [
                    {
                        "id": "m_byte_edge",
                        "content": "Byte-edge only memory",
                        "project": "byte-edge",
                    },
                    {
                        "id": "m_other_project",
                        "content": "Other project memory",
                        "project": "other-project",
                    },
                ],
            }
        )
    )

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [
                {
                    "memory_id": "m_byte_edge",
                    "content": "Byte-edge only memory",
                    "project": "byte-edge",
                    "agent": "codex",
                    "source_tool": "observe",
                    "cwd": "/tmp/byte-edge",
                }
            ]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 0, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    report = run_memory_doctor(manager, project="byte-edge")

    assert report["status"] == "healthy"
    assert report["yaml_count"] == 1
    assert report["missing_from_qdrant"] == []
    assert report["missing_from_yaml"] == []


def test_doctor_provenance_note_when_synced(tmp_path):
    """Synced corpus with no provenance must be healthy with missing_provenance note, not a finding."""
    from memory.doctor import run_memory_doctor

    # Write YAML so yaml_ids matches qdrant_ids — no sync mismatch
    memories = [{"id": "m1", "content": "No provenance", "project": "rekall-mcp"}]
    (tmp_path / "2026-07-01.yaml").write_text(yaml.dump({"date": "2026-07-01", "notes": memories}))

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [{"memory_id": "m1", "content": "No provenance", "project": "rekall-mcp"}]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 1, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    result = run_memory_doctor(manager)

    assert result["status"] == "healthy"
    assert "missing_provenance" in result["notes"]
    assert "missing_provenance" not in result["findings"]


def test_doctor_legacy_provenance_is_note_not_degraded(tmp_path):
    """Synced corpus (yaml+qdrant match) with no provenance must be healthy + note."""
    from memory.doctor import run_memory_doctor

    # Write YAML so yaml_ids matches qdrant_ids (no sync mismatch)
    memories = [{"id": f"m{i}", "content": "legacy", "project": "rekall-mcp"} for i in range(3)]
    (tmp_path / "2026-07-01.yaml").write_text(yaml.dump({"date": "2026-07-01", "notes": memories}))

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            # No agent/source_tool/cwd on any point
            return [
                {"memory_id": f"m{i}", "content": "legacy", "project": "rekall-mcp"}
                for i in range(3)
            ]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 3, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 3, "zero_vectors": 0},
        },
    )()

    result = run_memory_doctor(manager)

    assert result["status"] == "healthy"
    assert "missing_provenance" in result["notes"]
    assert "missing_provenance" not in result["findings"]


def test_doctor_zero_vectors_still_degrades(tmp_path):
    """Zero-vector finding still causes degraded status after provenance split."""
    from memory.doctor import run_memory_doctor

    memories = [{"id": "m1", "content": "bad vector", "project": "rekall-mcp"}]
    (tmp_path / "2026-07-01.yaml").write_text(yaml.dump({"date": "2026-07-01", "notes": memories}))

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [{"memory_id": "m1", "content": "bad vector", "project": "rekall-mcp"}]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 1, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 1},
        },
    )()

    result = run_memory_doctor(manager)

    assert result["status"] == "degraded"
    assert "zero_vectors" in result["findings"]


def test_doctor_counts_unknown_agent_as_missing(tmp_path):
    """agent='unknown' (ScopeDetector default) must increment missing_agent count."""
    from memory.doctor import run_memory_doctor

    memories = [{"id": "m1", "content": "saved with unknown agent", "project": "rekall-mcp"}]
    (tmp_path / "2026-07-01.yaml").write_text(yaml.dump({"date": "2026-07-01", "notes": memories}))

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [
                {
                    "memory_id": "m1",
                    "content": "saved with unknown agent",
                    "project": "rekall-mcp",
                    "agent": "unknown",
                    "source_tool": "save_memory",
                    "cwd": "/tmp/proj",
                }
            ]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 1, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    result = run_memory_doctor(manager)

    assert result["provenance"]["missing_agent"] == 1


def test_doctor_counts_empty_agent_as_missing(tmp_path):
    """agent='' (empty string) must increment missing_agent count."""
    from memory.doctor import run_memory_doctor

    memories = [{"id": "m1", "content": "saved with empty agent", "project": "rekall-mcp"}]
    (tmp_path / "2026-07-01.yaml").write_text(yaml.dump({"date": "2026-07-01", "notes": memories}))

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [
                {
                    "memory_id": "m1",
                    "content": "saved with empty agent",
                    "project": "rekall-mcp",
                    "agent": "",
                    "source_tool": "save_memory",
                    "cwd": "/tmp/proj",
                }
            ]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 1, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    result = run_memory_doctor(manager)

    assert result["provenance"]["missing_agent"] == 1


@pytest.mark.asyncio
async def test_memory_doctor_tool_preserves_unscoped_project(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.doctor.return_value = {
        "status": "healthy",
        "yaml_count": 0,
        "qdrant_count": 0,
        "findings": [],
    }

    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    await registered_tools["memory_doctor"]()

    manager.doctor.assert_called_once_with(project=None)
