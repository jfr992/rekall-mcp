"""Integration tests for graph rebuild behavior."""

from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph


def test_rebuild_graph_populates_nodes_and_edges(tmp_path):
    """rebuild() should construct nodes and at least one edge."""
    points = [
        {
            "memory_id": "decision_a",
            "type": "decision",
            "content": "Use PostgreSQL",
            "project": "api",
        },
        {
            "memory_id": "requirement_b",
            "type": "requirement",
            "content": "Must support ACID",
            "project": "api",
        },
        {
            "memory_id": "learning_c",
            "type": "learning",
            "content": "Tuning PostgreSQL connection pool",
            "project": "api",
        },
    ]

    store = MagicMock()
    store.scroll.return_value = points
    store.search.return_value = [
        {
            "memory_id": "decision_a",
            "type": "decision",
            "content": "Use PostgreSQL",
            "score": 0.96,
            "project": "api",
        },
        {
            "memory_id": "requirement_b",
            "type": "requirement",
            "content": "Must support ACID",
            "score": 0.88,
            "project": "api",
        },
        {
            "memory_id": "learning_c",
            "type": "learning",
            "content": "Tuning PostgreSQL connection pool",
            "score": 0.84,
            "project": "api",
        },
    ]

    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * 384

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    stats = kg.rebuild(store=store, embedder=embedder)

    assert stats["nodes"] == 3
    assert stats["edges"] >= 1
    assert (tmp_path / "_graph.json").exists()
