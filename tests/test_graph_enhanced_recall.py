"""Integration tests for graph-enhanced recall."""

from datetime import datetime, timedelta

from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph
from memory.manager import MemoryManager


def _manager_with_graph(tmp_path, store: MagicMock, embedder: MagicMock, graph: KnowledgeGraph) -> MemoryManager:
    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = store
    manager._embedder = embedder
    manager._knowledge_graph = graph
    return manager


def _mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * 384
    return embedder


def test_recall_includes_graph_neighbors(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("decision_pg", memory_type="decision")
    kg.add_node("learning_pool", memory_type="learning")
    kg.add_edge("decision_pg", "learning_pool", "led_to", weight=0.8)

    store = MagicMock()
    store.search.side_effect = [
        [
            {
                "memory_id": "decision_pg",
                "score": 0.82,
                "content": "Use PostgreSQL",
                "date": "2026-02-01",
                "type": "decision",
                "project": "api",
            },
        ],
        [
            {
                "memory_id": "learning_pool",
                "score": 0.45,
                "content": "Connection pooling with pgbouncer",
                "date": "2026-02-02",
                "type": "learning",
                "project": "api",
            },
        ],
    ]

    manager = _manager_with_graph(tmp_path, store, _mock_embedder(), kg)
    results = manager.recall("connection pooling", limit=5)

    ids = {r["memory_id"] for r in results}
    assert ids == {"decision_pg", "learning_pool"}


def test_recall_falls_back_without_graph(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")

    store = MagicMock()
    store.search.return_value = [
        {
            "memory_id": "note_a",
            "score": 0.9,
            "content": "Single memory",
            "date": "2026-02-01",
            "type": "note",
            "project": "api",
        }
    ]

    manager = _manager_with_graph(tmp_path, store, _mock_embedder(), kg)
    result = manager.recall("test", limit=5)

    assert len(result) == 1
    assert result[0]["memory_id"] == "note_a"


def test_recall_deduplicates(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("a", memory_type="note")
    kg.add_node("b", memory_type="note")
    kg.add_edge("a", "b", "related_to", weight=0.8)

    store = MagicMock()
    store.search.side_effect = [
        [
            {
                "memory_id": "a",
                "score": 0.8,
                "content": "A",
                "date": "2026-02-01",
                "type": "note",
            },
            {
                "memory_id": "b",
                "score": 0.8,
                "content": "B",
                "date": "2026-02-01",
                "type": "note",
            },
        ]
    ]

    manager = _manager_with_graph(tmp_path, store, _mock_embedder(), kg)
    result = manager.recall("test", limit=5)

    memory_ids = [r["memory_id"] for r in result]
    assert memory_ids == ["a", "b"]


def test_importance_affects_ranking(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("high", memory_type="note")
    kg.add_node("low", memory_type="note")
    kg._graph.nodes["high"]["importance"] = 0.95
    kg._graph.nodes["low"]["importance"] = 0.35

    store = MagicMock()
    now = datetime.now().strftime("%Y-%m-%d")
    store.search.return_value = [
        {
            "memory_id": "low",
            "score": 0.8,
            "content": "low importance",
            "date": now,
            "type": "note",
        },
        {
            "memory_id": "high",
            "score": 0.8,
            "content": "high importance",
            "date": now,
            "type": "note",
        },
    ]

    manager = _manager_with_graph(tmp_path, store, _mock_embedder(), kg)
    result = manager.recall("test", limit=2)

    assert result[0]["memory_id"] == "high"


def test_recency_affects_ranking(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("recent", memory_type="note")
    kg.add_node("old", memory_type="note")

    store = MagicMock()
    now = datetime.now()
    store.search.return_value = [
        {
            "memory_id": "old",
            "score": 0.8,
            "content": "older memory",
            "date": (now - timedelta(days=180)).strftime("%Y-%m-%d"),
            "type": "note",
        },
        {
            "memory_id": "recent",
            "score": 0.8,
            "content": "recent memory",
            "date": now.strftime("%Y-%m-%d"),
            "type": "note",
        },
    ]

    manager = _manager_with_graph(tmp_path, store, _mock_embedder(), kg)
    result = manager.recall("test", limit=2)

    assert result[0]["memory_id"] == "recent"
