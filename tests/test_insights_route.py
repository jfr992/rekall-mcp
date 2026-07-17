"""GET /api/memory/insights — cockpit aggregates contract (U2.6 T1.2).

Honesty rules under test: avg_top_score_7d averages only recalls that carried
at least one numeric score (denominator returned); misses are memory_recalled
events with empty memory_ids; episodics_created_7d comes from record dates +
tier, never implied consolidation.
"""

from datetime import datetime, timedelta

from memory.events import EventLog, MemoryEvent

NOW = datetime.now()


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _date(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _recalled(project, memory_ids, observed_at, scores=None):
    return MemoryEvent(
        event_type="memory_recalled",
        project=project,
        agent="claude-code",
        source="test",
        payload={
            "query": "q",
            "memory_ids": memory_ids,
            "memories": [
                {"memory_id": m, "score": s}
                for m, s in zip(memory_ids, scores or [], strict=False)
            ],
            "session_id": None,
        },
        observed_at=observed_at,
    )


def _promoted(project, memory_id, observed_at):
    return MemoryEvent(
        event_type="memory_promoted",
        project=project,
        agent="claude-code",
        source="reinforcement",
        payload={
            "memory_id": memory_id,
            "from_tier": "working",
            "to_tier": "episodic",
            "memory_ids": [memory_id],
            "session_id": None,
        },
        observed_at=observed_at,
    )


def _record(memory_id, project, date, tier):
    return {"memory_id": memory_id, "project": project, "date": date, "tier": tier}


def _rest_client(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.event_log = EventLog(tmp_path / "_events.jsonl")
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_insights_all_scope_shape_and_honest_numbers(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_recalled("proj-a", ["m1", "m2"], _at(1), scores=[0.9, 0.5]))
    log.append(_recalled("proj-a", ["m3"], _at(2)))  # hit, but no numeric score
    log.append(_recalled("proj-b", [], _at(1)))  # miss: empty memory_ids
    log.append(_recalled("proj-a", ["m4"], _at(10), scores=[0.8]))  # outside 7d
    log.append(_promoted("proj-a", "m1", _at(3)))
    log.append(_promoted("proj-a", "m9", _at(9)))  # outside 7d

    records = [
        _record("r1", "proj-a", _date(0), "working"),
        _record("r2", "proj-a", _date(2), "episodic"),
        _record("r3", "proj-b", _date(30), "semantic"),
        _record("r4", "proj-b", _date(8), "episodic"),
    ]
    manager.store.scroll_all.return_value = records
    manager.store.count.return_value = 7

    r = tc.get("/api/memory/insights")

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7
    assert body["in_scope"] == 4
    assert body["weekly_delta"] == 2  # r1 + r2 created in the trailing 7 days
    assert len(body["per_week"]) == 10
    assert sum(w["count"] for w in body["per_week"]) == 4
    assert body["per_week"][-1]["week_start"] == (
        (NOW - timedelta(days=NOW.weekday())).strftime("%Y-%m-%d")
    )
    assert body["recalls_7d"] == 3
    assert body["recalls_with_hits_7d"] == 2
    assert body["misses_7d"] == 1
    assert body["avg_top_score_7d"] == 0.9  # only the recall with numeric scores
    assert body["avg_top_score_denominator"] == 1
    assert body["promotions_7d"] == 1
    assert body["episodics_created_7d"] == 1  # r2; r4 is older than 7d
    assert body["tier_counts"] == {"working": 1, "episodic": 2, "semantic": 1, "identity": 0}
    assert body["event_window"]["events"] == 6
    assert body["event_window"]["oldest_at"] == log.tail(6)[0].observed_at
    # all-scope: the store scroll ran unfiltered
    assert manager.store.scroll_all.call_args.kwargs.get("filters") is None


def test_insights_project_scope_filters_scroll_and_events(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_recalled("proj-a", ["m1"], _at(1), scores=[0.7]))
    log.append(_recalled("proj-b", ["m2"], _at(1), scores=[0.9]))
    log.append(_promoted("proj-b", "m2", _at(2)))

    manager.store.scroll_all.return_value = [_record("r1", "proj-a", _date(1), "working")]
    manager.store.count.return_value = 9

    r = tc.get("/api/memory/insights", params={"project": "proj-a"})

    assert r.status_code == 200
    body = r.json()
    assert manager.store.scroll_all.call_args.kwargs.get("filters") == {"project": "proj-a"}
    assert body["total"] == 9  # totals stay global; in_scope carries the scoped count
    assert body["in_scope"] == 1
    assert body["recalls_7d"] == 1
    assert body["avg_top_score_7d"] == 0.7  # proj-b's 0.9 must not bleed in
    assert body["promotions_7d"] == 0
    # the event window is the shared tail, not the scoped slice
    assert body["event_window"]["events"] == 3


def test_insights_empty_log_and_empty_store(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.store.scroll_all.return_value = []
    manager.store.count.return_value = 0

    r = tc.get("/api/memory/insights")

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["in_scope"] == 0
    assert body["weekly_delta"] == 0
    assert [w["count"] for w in body["per_week"]] == [0] * 10
    assert body["recalls_7d"] == 0
    assert body["avg_top_score_7d"] is None  # no denominator, no fake zero average
    assert body["avg_top_score_denominator"] == 0
    assert body["recalls_with_hits_7d"] == 0
    assert body["misses_7d"] == 0
    assert body["promotions_7d"] == 0
    assert body["episodics_created_7d"] == 0
    assert body["tier_counts"] == {"working": 0, "episodic": 0, "semantic": 0, "identity": 0}
    assert body["event_window"] == {"events": 0, "oldest_at": None}
