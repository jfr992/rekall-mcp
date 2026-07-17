"""Shared bounded-tail event snapshot (U2.6 T1.1).

One cached read serves insights + stream + sessions. Cache key is the log's
(mtime_ns, size) — cheap stat, no time-seek (cursors are byte offsets).
"""

from memory.events import EventLog, MemoryEvent


def _ev(event_type="memory_recalled", project="proj-a", observed_at="2026-07-14T09:00:00"):
    return MemoryEvent(
        event_type=event_type,
        project=project,
        agent="claude-code",
        source="test",
        payload={"memory_ids": [], "session_id": None},
        observed_at=observed_at,
    )


def test_snapshot_cache_hit_on_unchanged_file(tmp_path, monkeypatch):
    from memory import insights

    log = EventLog(tmp_path / "_events.jsonl")
    log.append(_ev())

    reads = {"count": 0}
    original = EventLog.read_from

    def counting_read_from(self, cursor=None, limit=100):
        reads["count"] += 1
        return original(self, cursor, limit)

    monkeypatch.setattr(EventLog, "read_from", counting_read_from)

    first = insights.event_snapshot(log)
    second = insights.event_snapshot(log)

    assert reads["count"] == 1
    assert second is first
    assert len(first.events) == 1
    assert first.events[0].project == "proj-a"


def test_snapshot_invalidates_on_append(tmp_path):
    from memory import insights

    log = EventLog(tmp_path / "_events.jsonl")
    log.append(_ev(observed_at="2026-07-14T09:00:00"))
    first = insights.event_snapshot(log)

    log.append(_ev(observed_at="2026-07-14T09:05:00"))
    second = insights.event_snapshot(log)

    assert len(first.events) == 1
    assert len(second.events) == 2
    assert second.events[-1].observed_at == "2026-07-14T09:05:00"


def test_sessions_route_reads_through_snapshot(tmp_path, monkeypatch):
    """Two sessions GETs on an unchanged log = one underlying file read."""
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.event_log = EventLog(tmp_path / "_events.jsonl")
    manager.event_log.append(
        MemoryEvent(
            event_type="session_summary",
            project="proj-a",
            agent="claude-code",
            source="test",
            payload={"memory_ids": ["m1"], "session_id": "s1"},
            observed_at="2026-07-14T09:10:00",
        )
    )
    monkeypatch.setattr("memory.singleton._instance", manager)
    tc = TestClient(server.mcp.streamable_http_app())

    reads = {"count": 0}
    original = EventLog.read_from

    def counting_read_from(self, cursor=None, limit=100):
        reads["count"] += 1
        return original(self, cursor, limit)

    monkeypatch.setattr(EventLog, "read_from", counting_read_from)

    first = tc.get("/api/memory/sessions")
    second = tc.get("/api/memory/sessions")

    assert first.status_code == 200
    assert second.status_code == 200
    assert [s["session_id"] for s in second.json()["sessions"]] == ["s1"]
    assert reads["count"] == 1
