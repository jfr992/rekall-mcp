"""REST contract for the gated superseded-prune endpoint + legacy cleanup closure."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def server_client(monkeypatch):
    import server as srv

    fake = MagicMock()
    fake.store.get_many.return_value = []
    fake.knowledge_graph._graph.edges.return_value = []
    fake.record_event.return_value = None
    monkeypatch.setattr("memory.singleton._instance", fake)
    # raising=False: OK if not present yet (route not yet implemented)
    monkeypatch.setattr(srv, "_prune_daily_count", {}, raising=False)

    from server import mcp

    return TestClient(mcp.streamable_http_app())


def test_cleanup_prune_superseded_rejected():
    from memory.manager import MemoryManager

    mgr = object.__new__(MemoryManager)
    with pytest.raises(ValueError, match="prune/superseded"):
        MemoryManager.cleanup(mgr, prune_superseded=True)


def test_prune_superseded_wrong_confirm_date(server_client):
    r = server_client.post("/api/memory/prune/superseded", json={"confirm_date": "2020-01-01"})
    assert r.status_code == 400
    assert "confirm_date" in r.json()["error"]


def test_prune_superseded_daily_cap(server_client, monkeypatch):
    import server as srv
    from memory import prune_superseded as ps

    monkeypatch.setattr(srv, "_prune_daily_count", {srv._today_str(): ps.MAX_PER_DAY})
    r = server_client.post("/api/memory/prune/superseded", json={"confirm_date": srv._today_str()})
    assert r.status_code == 429


def test_prune_superseded_backup_failure_aborts(server_client, monkeypatch):
    import server as srv
    from memory.prune_superseded import Candidate

    one = [Candidate(memory_id="old-1", superseded_by="new-1")]
    monkeypatch.setattr("memory.prune_superseded.build_candidates", lambda *a, **kw: one)

    def boom(out_dir):
        from memory.cli import _BackupError

        raise _BackupError("disk full")

    monkeypatch.setattr(srv, "_prune_backup", boom)
    r = server_client.post("/api/memory/prune/superseded", json={"confirm_date": srv._today_str()})
    assert r.status_code == 500
    assert "backup" in r.json()["error"].lower()


def test_prune_superseded_dry_run(server_client, monkeypatch):
    import server as srv
    from memory.prune_superseded import Candidate

    candidates = [Candidate(memory_id="old-1", superseded_by="new-1")]
    monkeypatch.setattr("memory.prune_superseded.build_candidates", lambda *a, **kw: candidates)

    r = server_client.post(
        "/api/memory/prune/superseded",
        json={"confirm_date": srv._today_str(), "dry_run": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("dry_run") is True
    assert "old-1" in data.get("candidates", [])

    fake_mgr = __import__("memory.singleton", fromlist=["_instance"])._instance
    fake_mgr.delete.assert_not_called()


def test_prune_superseded_over_per_fire_cap(server_client, monkeypatch):
    import server as srv
    from memory.prune_superseded import MAX_PER_FIRE, Candidate

    many = [
        Candidate(memory_id=f"id-{i}", superseded_by=f"new-{i}") for i in range(MAX_PER_FIRE + 1)
    ]
    monkeypatch.setattr("memory.prune_superseded.build_candidates", lambda *a, **kw: many)

    r = server_client.post("/api/memory/prune/superseded", json={"confirm_date": srv._today_str()})
    assert r.status_code == 400
    data = r.json()
    assert "candidates" in data["error"].lower() or "cap" in data["error"].lower()

    # Contract: refusal must carry the candidate list so the operator can review
    assert "candidates" in data, "fire-cap refusal must include 'candidates' key"
    candidate_ids = data["candidates"]
    assert isinstance(candidate_ids, list), "'candidates' must be a list"
    assert len(candidate_ids) == MAX_PER_FIRE + 1, (
        f"expected {MAX_PER_FIRE + 1} candidates, got {len(candidate_ids)}"
    )
    expected_ids = {f"id-{i}" for i in range(MAX_PER_FIRE + 1)}
    assert set(candidate_ids) == expected_ids, "candidate IDs must match the seeded set"

    # Nothing should have been deleted
    fake_mgr = __import__("memory.singleton", fromlist=["_instance"])._instance
    fake_mgr.delete.assert_not_called()


def test_prune_superseded_success(server_client, monkeypatch):
    """old-1 deleted, old-2 partially fails (still in store after delete)."""
    from pathlib import Path

    import server as srv
    from memory.prune_superseded import Candidate

    candidates = [
        Candidate(memory_id="old-1", superseded_by="new-1"),
        Candidate(memory_id="old-2", superseded_by="new-2"),
    ]
    monkeypatch.setattr("memory.prune_superseded.build_candidates", lambda *a, **kw: candidates)

    fake_mgr = __import__("memory.singleton", fromlist=["_instance"])._instance
    # old-1: gone after delete; old-2: still present (partial failure)
    fake_mgr.store.get_many.side_effect = [[], [{"memory_id": "old-2"}]]
    monkeypatch.setattr(srv, "_prune_backup", lambda out_dir: [Path("/tmp/backup.tar.gz")])

    r = server_client.post("/api/memory/prune/superseded", json={"confirm_date": srv._today_str()})
    assert r.status_code == 200
    data = r.json()
    assert "old-1" in data["deleted"]
    assert "old-2" in data["partially_failed"]


def test_cleanup_prune_superseded_returns_400_via_rest(server_client):
    """cleanup endpoint with prune_superseded=True must surface ValueError as 400."""

    # The real manager raises ValueError; configure the mock to mirror that
    __import__(
        "memory.singleton", fromlist=["_instance"]
    )._instance.cleanup.side_effect = ValueError(
        "prune_superseded is gated: use POST /api/memory/prune/superseded"
    )
    r = server_client.post(
        "/api/memory/cleanup",
        json={"prune_superseded": True},
    )
    assert r.status_code == 400
    assert "prune" in r.json()["error"].lower()
