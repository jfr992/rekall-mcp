"""Integration tests for graph rebuild behavior."""

from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph


def test_rebuild_uses_raw_content_for_auto_link(tmp_path):
    """Repr v2: stored dense vectors are encode(content), so rebuild's auto_link
    search must encode raw content — an embedding_text vector would be
    asymmetric with every migrated point and silently drop supersedes edges."""
    OLD_CONTENT = "polling every 30 seconds for catalog updates"
    NEW_CONTENT = "webhooks push from catalog service instead of polling"
    OLD_EMBED = "enriched: polling catalog sync embedding_text"
    NEW_EMBED = "enriched: webhooks catalog sync embedding_text"

    VECTORS: dict[str, list[float]] = {
        OLD_CONTENT: [0.1] * 384,
        NEW_CONTENT: [0.2] * 384,
        OLD_EMBED: [0.8] * 384,
        NEW_EMBED: [0.9] * 384,
    }

    embedder = MagicMock()
    embedder.encode.side_effect = lambda text: VECTORS[text]

    points = [
        {
            "memory_id": "old_decision",
            "type": "decision",
            "content": OLD_CONTENT,
            "embedding_text": OLD_EMBED,
            "project": "api",
        },
        {
            "memory_id": "new_decision",
            "type": "decision",
            "content": NEW_CONTENT,
            "embedding_text": NEW_EMBED,
            "project": "api",
        },
    ]

    store = MagicMock()
    store.scroll.return_value = points

    # search returns the old decision ONLY for the raw-content vector of
    # new_decision ([0.2]*384). The embedding_text vector ([0.9]*384) returns
    # empty, so passing embedding_text produces no supersedes edge.
    NEW_CONTENT_VEC = [0.2] * 384

    def _search(vector, **kwargs):
        if vector == NEW_CONTENT_VEC:
            return [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": OLD_CONTENT,
                    "score": 0.95,
                    "project": "api",
                }
            ]
        return []

    store.search.side_effect = _search

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.rebuild(store=store, embedder=embedder)

    out_edges = kg.get_edges("new_decision", direction="out")
    supersedes_targets = [e.target for e in out_edges if e.relation == "supersedes"]
    assert "old_decision" in supersedes_targets, (
        f"rebuild() did not create supersedes edge using raw content. "
        f"Edges found: {[(e.relation, e.target) for e in out_edges]}. "
        "Fix: auto_link must encode(content) — symmetric with repr v2 stored vectors."
    )


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
