"""Dedupe path must reinforce the existing memory, not silently skip it."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.integration
def test_identical_content_different_projects_does_not_dedupe(memory_manager):
    """Repr v2 queries dedupe with raw content (cosine 1.0 for identical text);
    the project filter must keep cross-project saves from reinforcing."""
    mgr = memory_manager
    content = "Rotate the API gateway certificates every 90 days"

    id_a = mgr.save(content, type="fact", project="project-alpha")
    id_b = mgr.save(content, type="fact", project="project-beta")

    assert id_a != id_b, "identical content across projects must create two memories"
    payload_a = mgr.store.get_by_id(id_a)
    payload_b = mgr.store.get_by_id(id_b)
    assert payload_a["reinforcement_count"] == 0
    assert payload_b["reinforcement_count"] == 0


@pytest.fixture
def manager_with_fake_store(tmp_path):
    """Construct a MemoryManager with an in-memory fake store + mocked embedder."""
    from memory.manager import MemoryManager

    with (
        patch("memory.manager.VectorStore") as store_class,
        patch("memory.manager.Embedder") as embedder_class,
    ):
        store = MagicMock()
        embedder = MagicMock()
        store.count.return_value = 0
        embedder.encode.return_value = [0.1] * 384
        embedder.dimensions = 384
        store_class.return_value = store
        embedder_class.return_value = embedder

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        mgr = MemoryManager(memory_dir=memory_dir, qdrant_url="http://localhost:6333")
        mgr._store = store
        mgr._embedder = embedder
        yield mgr


def test_dedupe_reinforces_existing_memory(manager_with_fake_store):
    mgr = manager_with_fake_store
    store = mgr._store

    # First save creates the memory
    existing_payload = {
        "memory_id": "existing_id",
        "type": "note",
        "content": "test content",
        "date": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
        "reinforcement_count": 5,
        "tier": "working",
        "salience": 0.3,
    }
    # Simulate that _find_duplicate_memory_id returns an existing id, and
    # the store can fetch the payload for reinforcement.
    store.search.return_value = [
        {"memory_id": "existing_id", "score": 0.99, "content": "test content", "type": "note"}
    ]
    store.get_by_id.return_value = existing_payload

    memory_id = mgr.save(content="test content", type="note", project="test")

    assert memory_id == "existing_id"
    # The dedupe path must have called update_payload with reinforcement_count += 1
    assert store.update_payload.called
    args, kwargs = store.update_payload.call_args
    # Support both call signatures: update_payload(memory_id, payload) positional
    # or update_payload(memory_id=..., payload=...) keyword
    update_dict = None
    if len(args) >= 2:
        update_dict = args[1]
    else:
        update_dict = kwargs.get("payload") or kwargs.get("new_payload")
    assert update_dict is not None
    assert update_dict["reinforcement_count"] == 6
    # And reclassified: 6 reinforces + 8 days -> semantic
    assert update_dict["tier"] == "semantic"


def test_new_save_computes_tier_immediately(manager_with_fake_store):
    mgr = manager_with_fake_store
    store = mgr._store
    store.search.return_value = []  # no dedupe hit

    mgr.save(content="brand new note", type="note", project="test", salience=0.3)

    # store.save was called with a payload that contains tier + durability
    assert store.save.called
    payload = store.save.call_args.kwargs.get("payload") or store.save.call_args.args[2]
    assert "tier" in payload
    assert "durability" in payload
    assert payload["tier"] == "working"
    # New saves must always initialize reinforcement_count to 0
    assert "reinforcement_count" in payload
    assert payload["reinforcement_count"] == 0
    assert "durability" in payload
    assert "retention_days" in payload


def test_reinforce_failure_does_not_raise(manager_with_fake_store):
    """If reinforce_and_reclassify raises, the save must still return the existing id cleanly."""
    mgr = manager_with_fake_store
    store = mgr._store

    store.search.return_value = [
        {"memory_id": "existing_id", "score": 0.99, "content": "test", "type": "note"}
    ]
    # Return a malformed payload that will cause reinforce_and_reclassify to raise
    # (missing memory_id and date, which are handled, but we can force a raise by
    # monkey-patching the inner function)
    store.get_by_id.return_value = {
        "memory_id": "existing_id",
        "type": "note",
        "date": "2026-01-01",
        "reinforcement_count": 5,
        "tier": "working",
        "salience": 0.3,
    }

    # Since manager imports it inside _reinforce_existing_memory, patch via memory.intelligence
    from unittest.mock import patch

    with patch("memory.intelligence.reinforce_and_reclassify", side_effect=RuntimeError("boom")):
        # This MUST NOT raise
        memory_id = mgr.save(content="test", type="note", project="test")
        assert memory_id == "existing_id"

    # update_payload must NOT have been called because reinforce failed
    assert not store.update_payload.called


@pytest.mark.parametrize(
    "identifier,resolution",
    [
        ("PR #83", "#83 merged and deployed"),
        ("BE-684", "BE-684 closed"),
        ("1a2b3c4", "1a2b3c4 shipped"),
    ],
)
@pytest.mark.parametrize("score", [0.80, 0.90, 0.99])
def test_resolved_save_supersedes_without_demoting(
    manager_with_fake_store, identifier, resolution, score
):
    from memory.knowledge_graph import KnowledgeGraph

    mgr = manager_with_fake_store
    old = {
        "memory_id": "old",
        "content": f"{identifier} rollout pending",
        "type": "decision",
        "project": "test",
        "entities": [],
        "tier": "semantic",
        "reinforcement_count": 5,
    }
    mgr.store.search.side_effect = lambda **kw: (
        [old | {"score": score}] if score >= kw["score_threshold"] else []
    )
    mgr.knowledge_graph.add_node("old", topic="test", importance=0.85)

    new_id = mgr.save(resolution, type="decision", project="test")

    edges = mgr.knowledge_graph.get_edges(new_id, direction="out")
    assert [(edge.target, edge.relation) for edge in edges] == [("old", "supersedes")]
    assert edges[0].weight == score
    assert edges[0].band == "provisional", "resolution evidence must not authorize auto-prune"
    assert mgr.knowledge_graph.get_importance("old") == 0.85
    mgr.store.delete.assert_not_called()
    mgr.store.update_payload.assert_not_called()
    assert mgr._find_in_yaml(new_id) is not None
    reloaded = KnowledgeGraph(mgr.memory_dir / "_graph.json")
    assert reloaded.get_edges(new_id, direction="out") == edges
    search = next(
        c.kwargs for c in mgr.store.search.call_args_list if c.kwargs.get("score_threshold") == 0.80
    )
    assert search["filters"] == {"project": "test"}
    assert search.get("query_text") is None, "supersedes requires dense cosine, not hybrid score"


@pytest.mark.parametrize(
    "old_content,new_content,old_project,score",
    [
        ("PR #83 pending", "#83 merged", "test", 0.79),
        ("PR #83 pending", "#83 merged", "other", 0.80),
        ("PR #84 pending", "#83 merged", "test", 0.80),
        ("Helm pending", "Helm deployed", "test", 0.80),
        ("PR #83 pending", "#83 awaiting review", "test", 0.80),
        ("PR #83 pending", "#83 unmerged", "test", 0.80),
    ],
)
def test_save_resolution_edge_requires_all_gates(
    manager_with_fake_store, old_content, new_content, old_project, score
):
    mgr = manager_with_fake_store
    mgr.store.search.side_effect = lambda **kw: (
        [
            {
                "memory_id": "old",
                "content": old_content,
                "type": "note",
                "project": old_project,
                "score": score,
            }
        ]
        if score >= kw["score_threshold"]
        else []
    )

    new_id = mgr.save(new_content, type="fact", project="test")

    assert not any(
        edge.relation == "supersedes"
        for edge in mgr.knowledge_graph.get_edges(new_id, direction="out")
    )


def test_resolution_lookup_failure_does_not_lose_saved_memory(manager_with_fake_store, caplog):
    mgr = manager_with_fake_store

    def search(**kwargs):
        if kwargs["score_threshold"] == 0.80:
            raise RuntimeError("resolution lookup unavailable")
        return []

    mgr.store.search.side_effect = search
    new_id = mgr.save("PR #83 merged", type="fact", project="test")

    assert mgr._find_in_yaml(new_id) is not None
    mgr.store.save.assert_called_once()
    assert "resolution lookup unavailable" in caplog.text


def test_resolved_save_with_embedded_store_preserves_predecessor(tmp_path, monkeypatch):
    from math import sqrt

    from memory.manager import MemoryManager

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    old_content = "PR #83 held: billing broken; do not merge."
    new_content = "PR #83 merged and deployed."

    class Embedder:
        dimensions = 384

        def encode(self, text):
            cosine = 0.81 if text == new_content else 1.0
            return [cosine, sqrt(1.0 - cosine**2)] + [0.0] * 382

    manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "qdrant"))
    manager._embedder = Embedder()
    old_id = manager.save(old_content, type="decision", project="test")
    foreign_id = manager.save(old_content, type="decision", project="other")
    old_payload = manager.store.get_by_id(old_id)
    old_yaml = manager._find_in_yaml(old_id)
    importance = manager.knowledge_graph.get_importance(old_id)

    try:
        new_id = manager.save(new_content, type="fact", project="test")

        edges = manager.knowledge_graph.get_edges(new_id, direction="out")
        assert [(edge.target, edge.relation) for edge in edges] == [(old_id, "supersedes")]
        assert all(edge.target != foreign_id for edge in edges)
        assert edges[0].weight == pytest.approx(0.81)
        assert edges[0].band == "provisional"
        assert manager.store.get_by_id(old_id) == old_payload
        assert manager._find_in_yaml(old_id) == old_yaml
        assert manager.knowledge_graph.get_importance(old_id) == importance
        assert manager.get_project_capsule("test")["danger_zones"] == []
    finally:
        manager.store.client.close()
