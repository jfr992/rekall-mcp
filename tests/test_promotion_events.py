"""memory_promoted events fire ONLY at the durable reinforcement write site.

The legacy shim (lifecycle.promote_memory) and the resume path mutate
in-memory dicts that are never persisted — they must stay silent. Backfill
summarizes in ONE lifecycle_backfilled event, never a per-memory flood.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _events(manager):
    path = manager.memory_dir / "_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def mocked_manager(tmp_path):
    from memory.manager import MemoryManager

    with (
        patch("memory.manager.VectorStore") as store_class,
        patch("memory.manager.Embedder") as embedder_class,
    ):
        store = MagicMock()
        embedder = MagicMock()
        embedder.encode.return_value = [0.1] * 384
        embedder.dimensions = 384
        store_class.return_value = store
        embedder_class.return_value = embedder

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        manager = MemoryManager(memory_dir=memory_dir, qdrant_url="http://localhost:6334")
        manager._store = store
        manager._embedder = embedder
        manager.knowledge_graph.stats = MagicMock(return_value={"nodes": 0, "edges": 0})
        manager.knowledge_graph.count_contradicts = MagicMock(return_value=0)
        yield manager, store


def _promotable_memory():
    """4 prior reinforcements + 8 days old: the next reinforcement crosses
    Rule 2 (x5, >=7d) and bumps working -> semantic."""
    return {
        "memory_id": "2026-07-09_note_abc123",
        "content": "the deploy needs the flag",
        "type": "note",
        "project": "proj-a",
        "tier": "working",
        "salience": 0.2,
        "reinforcement_count": 4,
        "date": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
    }


def test_reinforcement_tier_bump_emits_exactly_one_promoted_event(mocked_manager):
    manager, store = mocked_manager
    store.get_by_id.return_value = _promotable_memory()

    manager._reinforce_existing_memory("2026-07-09_note_abc123")

    store.update_payload.assert_called_once()
    promoted = [e for e in _events(manager) if e["event_type"] == "memory_promoted"]
    assert len(promoted) == 1
    assert promoted[0]["project"] == "proj-a"
    assert promoted[0]["payload"]["memory_id"] == "2026-07-09_note_abc123"
    assert promoted[0]["payload"]["from_tier"] == "working"
    assert promoted[0]["payload"]["to_tier"] == "semantic"


def test_reinforcement_without_tier_change_emits_nothing(mocked_manager):
    manager, store = mocked_manager
    memory = _promotable_memory()
    memory["reinforcement_count"] = 0  # next bump is x1 — Rule 2 stays cold
    store.get_by_id.return_value = memory

    manager._reinforce_existing_memory(memory["memory_id"])

    store.update_payload.assert_called_once()
    assert [e for e in _events(manager) if e["event_type"] == "memory_promoted"] == []


def test_reinforcement_tier_drop_emits_demoted_not_promoted(mocked_manager):
    """A contradicted semantic memory (classify() Rule 4) demotes one tier on
    reclassify. That's a memory_demoted event, never memory_promoted."""
    manager, store = mocked_manager
    memory = {
        "memory_id": "2026-07-09_fact_abc123",
        "content": "the deploy needs the flag",
        "type": "fact",
        "project": "proj-a",
        "tier": "semantic",
        "salience": 0.1,
        "reinforcement_count": 0,
        "date": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
    }
    store.get_by_id.return_value = memory
    manager.knowledge_graph.count_contradicts = MagicMock(return_value=2)

    manager._reinforce_existing_memory("2026-07-09_fact_abc123")

    store.update_payload.assert_called_once()
    events = _events(manager)
    assert [e["event_type"] for e in events] == ["memory_demoted"]
    assert events[0]["project"] == "proj-a"
    assert events[0]["payload"]["memory_id"] == "2026-07-09_fact_abc123"
    assert events[0]["payload"]["from_tier"] == "semantic"
    assert events[0]["payload"]["to_tier"] == "episodic"


def test_failed_persistence_emits_no_promoted_event(mocked_manager):
    """The event lands only AFTER the write did — a failed update stays silent."""
    manager, store = mocked_manager
    store.get_by_id.return_value = _promotable_memory()
    store.update_payload.side_effect = OSError("qdrant down")

    manager._reinforce_existing_memory("2026-07-09_note_abc123")

    assert [e for e in _events(manager) if e["event_type"] == "memory_promoted"] == []


def test_backfill_emits_one_summary_event_never_per_memory(mocked_manager):
    manager, store = mocked_manager
    today = datetime.now().strftime("%Y-%m-%d")
    store.scroll.return_value = [
        # note, no tier yet -> working (promoted from nothing counts as changed)
        {"memory_id": "m1", "type": "note", "date": today, "salience": 0.1},
        # decision, high salience -> semantic; started working -> promoted
        {"memory_id": "m2", "type": "decision", "date": today, "salience": 0.9, "tier": "working"},
        # already semantic decision -> unchanged
        {"memory_id": "m3", "type": "decision", "date": today, "salience": 0.9, "tier": "semantic"},
        # contradicted semantic fact -> demoted to episodic
        {"memory_id": "m4", "type": "fact", "date": today, "salience": 0.1, "tier": "semantic"},
    ]
    manager.knowledge_graph.stats = MagicMock(return_value={"nodes": 4, "edges": 2})
    manager.knowledge_graph.count_contradicts = MagicMock(
        side_effect=lambda memory_id: 2 if memory_id == "m4" else 0
    )

    manager.backfill_lifecycle(dry_run=False)

    events = _events(manager)
    assert [e["event_type"] for e in events] == ["lifecycle_backfilled"]
    summary = events[0]["payload"]
    assert summary["promoted"] == 2  # m1 (gained a tier) + m2
    assert summary["demoted"] == 1  # m4
    assert summary["unchanged"] == 1  # m3


def test_backfill_dry_run_emits_no_events(mocked_manager):
    manager, store = mocked_manager
    store.scroll.return_value = [
        {"memory_id": "m1", "type": "note", "date": "2026-07-01", "salience": 0.1},
    ]

    manager.backfill_lifecycle(dry_run=True)

    assert _events(manager) == []


def test_legacy_shim_and_resume_paths_never_emit_events():
    """lifecycle.promote_memory is a shim and resume's apply_memory_promotion
    mutates dicts that are never persisted (resume.py:85) — a memory_promoted
    event from either would be a lie. Pin: no event rail access at all."""
    import inspect

    from memory import intelligence, lifecycle, resume

    for module in (lifecycle, intelligence, resume):
        source = inspect.getsource(module)
        assert "record_event" not in source, f"{module.__name__} touches the event rail"
        assert "event_log" not in source, f"{module.__name__} touches the event log"
