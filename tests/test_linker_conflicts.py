"""Tests for entity-band contradicts rule and LLM refinement (Task 3b)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph
from memory.linker import auto_link

TOOLS_SRC = (Path(__file__).parent.parent / "src" / "tools" / "builtin" / "memory.py").read_text()


def _mock_store(candidates: list[dict]) -> MagicMock:
    store = MagicMock()
    store.search.return_value = candidates
    return store


def _mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * 384
    return embedder


def test_entity_band_contradicts_with_shared_entity(tmp_path):
    """Same-type, sim=0.79, shared entity → auto_link creates 'contradicts' edge."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Switched from PostgreSQL to MongoDB for primary storage",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL for primary storage",
                    "score": 0.79,
                    "entities": ["PostgreSQL", "MongoDB"],
                },
            ]
        ),
    )

    assert result.relations.get("contradicts") == 1
    edges = kg.get_edges("new_decision", direction="out")
    assert any(edge.target == "old_decision" and edge.relation == "contradicts" for edge in edges)


def test_entity_band_no_overlap_stays_related_to(tmp_path):
    """Same-type, sim=0.79, zero entity overlap → stays 'related_to'."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Use S3 for file storage",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use Kafka for event streaming",
                    "score": 0.79,
                    "entities": ["Kafka"],  # no overlap with S3
                },
            ]
        ),
    )

    assert result.relations.get("contradicts", 0) == 0
    assert result.relations.get("related_to", 0) == 1


def test_sim_095_same_type_still_supersedes(tmp_path):
    """High similarity (0.95) same-type pair must still produce supersedes, not contradicts."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Use PostgreSQL 16 for primary storage",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL 15 for primary storage",
                    "score": 0.95,
                    "entities": ["PostgreSQL", "storage"],
                },
            ]
        ),
    )

    assert result.relations.get("supersedes") == 1
    assert result.relations.get("contradicts", 0) == 0


def test_recall_memories_docstring_trigger_shaped():
    """recall_memories docstring must contain trigger-shaped language."""
    assert "prior decisions" in TOOLS_SRC


def test_llm_refine_exception_fallback(tmp_path, monkeypatch):
    """When LLM client raises, entity-band contradicts is preserved."""
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.side_effect = RuntimeError("API unavailable")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Switched from PostgreSQL to MongoDB for primary storage",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL for primary storage",
                    "score": 0.79,
                    "entities": ["PostgreSQL", "MongoDB"],
                },
            ]
        ),
    )

    assert result.relations.get("contradicts") == 1


def test_llm_refine_key_absent_no_anthropic_call(tmp_path, monkeypatch):
    """With no ANTHROPIC_API_KEY the Anthropic client is never instantiated."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    mock_anthropic = MagicMock()
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Switched from PostgreSQL to MongoDB for primary storage",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL for primary storage",
                    "score": 0.79,
                    "entities": ["PostgreSQL", "MongoDB"],
                },
            ]
        ),
    )

    mock_anthropic.Anthropic.assert_not_called()
    assert result.relations.get("contradicts") == 1


def test_llm_refine_supersedes_override(tmp_path, monkeypatch):
    """LLM returning SUPERSEDES overrides the deterministic contradicts."""
    mock_response = SimpleNamespace(content=[SimpleNamespace(text="SUPERSEDES")])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Switched from PostgreSQL to MongoDB for primary storage",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL for primary storage",
                    "score": 0.79,
                    "entities": ["PostgreSQL", "MongoDB"],
                },
            ]
        ),
    )

    assert result.relations.get("supersedes") == 1
    assert result.relations.get("contradicts", 0) == 0
