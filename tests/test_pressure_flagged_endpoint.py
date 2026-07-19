"""T5: /api/memory/pressure returns per-reason flagged lists incl. conflict ids."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def fake_manager(monkeypatch):
    fake = MagicMock()
    fake.store.scroll.return_value = [
        {"memory_id": "lv1", "tier": "working", "salience": 0.1, "content": "low value one"},
        {"memory_id": "ok1", "tier": "semantic", "salience": 0.9, "content": "fine"},
        {"memory_id": "cf1", "tier": "semantic", "salience": 0.9, "content": "conflicted"},
    ]
    fake.knowledge_graph.stats.return_value = {"nodes": 3, "edges": 1}
    fake.knowledge_graph.count_contradicts.side_effect = lambda mid: 2 if mid == "cf1" else 0
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.fixture
def client():
    from server import build_app

    return TestClient(build_app())


def test_pressure_flagged_lists_grouped_by_reason(client, fake_manager):
    r = client.get("/api/memory/pressure")
    assert r.status_code == 200
    flagged = r.json()["flagged"]
    assert [m["memory_id"] for m in flagged["low_value"]] == ["lv1"]
    assert flagged["stale_working"] == []
    assert [m["memory_id"] for m in flagged["conflict"]] == ["cf1"]
    assert flagged["contradiction_count"] == 1


def test_pressure_flagged_disputed_list_from_payload(monkeypatch):
    """T5: disputed=true memories surface as their own flagged.disputed list."""
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    fake = MagicMock()
    fake.store.scroll.return_value = [
        {"memory_id": "d1", "tier": "semantic", "salience": 0.9, "content": "disputed one", "disputed": True},
        {"memory_id": "ok1", "tier": "semantic", "salience": 0.9, "content": "fine"},
    ]
    fake.knowledge_graph.stats.return_value = {"nodes": 0, "edges": 0}
    fake.knowledge_graph.count_contradicts.return_value = 0
    fake.event_log.tail.return_value = []
    monkeypatch.setattr("memory.singleton._instance", fake)

    from server import build_app

    client = TestClient(build_app())
    r = client.get("/api/memory/pressure")
    assert r.status_code == 200
    flagged = r.json()["flagged"]
    assert [m["memory_id"] for m in flagged["disputed"]] == ["d1"]
    assert flagged["disputed_count"] == 1


def test_pressure_flagged_stale_candidates_from_event_log(monkeypatch):
    """T5: memory_supersedes_candidate events (T2's persisted record shape —
    {memory_id, reason}) surface as flagged.stale_candidates, deduped by
    memory_id (a stale verdict re-fired for the same memory shouldn't double up)."""
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    from memory.events import MemoryEvent

    fake = MagicMock()
    fake.store.scroll.return_value = [
        {"memory_id": "s1", "tier": "semantic", "salience": 0.9, "content": "stale one"},
        {"memory_id": "ok1", "tier": "semantic", "salience": 0.9, "content": "fine"},
    ]
    fake.store.get_many.return_value = [
        {"memory_id": "s1", "tier": "semantic", "salience": 0.9, "content": "stale one", "type": "fact", "date": "2026-07-01"},
    ]
    fake.knowledge_graph.stats.return_value = {"nodes": 0, "edges": 0}
    fake.knowledge_graph.count_contradicts.return_value = 0
    fake.event_log.tail.return_value = [
        MemoryEvent(
            event_type="memory_supersedes_candidate",
            project="general",
            agent="unknown",
            source="reinforcement",
            payload={"memory_id": "s1", "reason": "stale_feedback"},
        ),
        MemoryEvent(
            event_type="memory_supersedes_candidate",
            project="general",
            agent="unknown",
            source="reinforcement",
            payload={"memory_id": "s1", "reason": "stale_feedback"},
        ),
    ]
    monkeypatch.setattr("memory.singleton._instance", fake)

    from server import build_app

    client = TestClient(build_app())
    r = client.get("/api/memory/pressure")
    assert r.status_code == 200
    flagged = r.json()["flagged"]
    assert [m["memory_id"] for m in flagged["stale_candidates"]] == ["s1"]
    assert flagged["stale_candidates_count"] == 1
