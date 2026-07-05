"""Integration tests for graph rebuild behavior."""

from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph


def test_rebuild_uses_embedding_text_for_auto_link(tmp_path):
    """rebuild() must pass embedding_text to auto_link so the search vector is
    symmetric with the save-time stored vector.

    The embedder returns distinct vectors for raw content vs enriched
    embedding_text.  store.search returns a high-similarity match ONLY when
    called with the embedding_text vector (as the save path does).  If rebuild
    passes raw content instead, no supersedes edge is created.
    """
    OLD_CONTENT = "polling every 30 seconds for catalog updates"
    NEW_CONTENT = "webhooks push from catalog service instead of polling"
    OLD_EMBED = "enriched: polling catalog sync embedding_text"
    NEW_EMBED = "enriched: webhooks catalog sync embedding_text"

    # Distinct vectors: content-encoded and embedding_text-encoded diverge.
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

    # search returns the old decision ONLY for the embedding_text vector of
    # new_decision ([0.9]*384).  Raw content vector ([0.2]*384) returns empty
    # so the bug (using content) produces no supersedes edge.
    NEW_EMBED_VEC = [0.9] * 384

    def _search(vector, **kwargs):
        if vector == NEW_EMBED_VEC:
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
        f"rebuild() did not create supersedes edge using embedding_text. "
        f"Edges found: {[(e.relation, e.target) for e in out_edges]}. "
        "Fix: pass embedding_text=point.get('embedding_text') to auto_link in rebuild()."
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
