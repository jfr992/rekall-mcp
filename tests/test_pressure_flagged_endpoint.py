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
