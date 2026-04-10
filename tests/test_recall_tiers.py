from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph
from memory.manager import MemoryManager


def _manager(tmp_path, store, embedder, graph):
    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = store
    manager._embedder = embedder
    manager._knowledge_graph = graph
    return manager


def test_recall_includes_tier_and_identity_bias(tmp_path):
    graph = KnowledgeGraph(tmp_path / "_graph.json")
    graph.add_node("pref", memory_type="preference")
    graph.add_node("note", memory_type="note")

    store = MagicMock()
    store.search.return_value = [
        {
            "memory_id": "note",
            "score": 0.9,
            "content": "Working on auth refactor",
            "date": "2026-04-10",
            "type": "note",
            "project": "brain",
            "tier": "working",
        },
        {
            "memory_id": "pref",
            "score": 0.88,
            "content": "JR prefers direct concise answers",
            "date": "2026-04-10",
            "type": "preference",
            "project": "brain",
            "tier": "identity",
        },
    ]

    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * 384

    manager = _manager(tmp_path, store, embedder, graph)
    results = manager.recall("how should I answer", limit=2)

    assert results[0]["memory_id"] == "pref"
    assert results[0]["tier"] == "identity"
