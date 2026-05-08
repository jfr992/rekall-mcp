"""Dedupe path must reinforce the existing memory, not silently skip it."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def manager_with_fake_store(tmp_path):
    """Construct a MemoryManager with an in-memory fake store + mocked embedder."""
    from memory.manager import MemoryManager

    with patch("memory.manager.VectorStore") as store_class, \
         patch("memory.manager.Embedder") as embedder_class:
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
