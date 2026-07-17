"""GET /api/memory/stream — newest-first merged activity feed (U2.6 T1.3).

Kinds: saved (memory records), recalled/promoted (event tail), consolidated
(compaction summary records). Working-tier saved rows carry fades_in_hours
derived from retention_days + timestamp — display-only decay honesty.
"""

from datetime import datetime, timedelta

from memory.events import EventLog, MemoryEvent

NOW = datetime.now()


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _date(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _record(memory_id, project, *, tier="working", type="note", days_ago=0, **extra):
    return {
        "memory_id": memory_id,
        "project": project,
        "type": type,
        "tier": tier,
        "date": _date(days_ago),
        "timestamp": _at(days_ago),
        "content": f"content of {memory_id}",
        **extra,
    }


def _ev(event_type, project, payload, observed_at):
    return MemoryEvent(
        event_type=event_type,
        project=project,
        agent="claude-code",
        source="test",
        payload=payload,
        observed_at=observed_at,
    )


def _rest_client(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.event_log = EventLog(tmp_path / "_events.jsonl")
    manager.store.scroll_all.return_value = []
    manager.store.count.return_value = 0
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_stream_saved_rows_with_working_tier_fade(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.store.scroll_all.return_value = [
        _record("m-work", "proj-a", tier="working", retention_days=14, days_ago=1),
        _record("m-sem", "proj-a", tier="semantic", type="decision", days_ago=2),
    ]

    r = tc.get("/api/memory/stream")

    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    assert [row["kind"] for row in rows] == ["saved", "saved"]
    work, sem = rows
    assert work["at"] == _at(1)
    assert work["payload"]["memory_id"] == "m-work"
    assert work["payload"]["type"] == "note"
    assert work["payload"]["tier"] == "working"
    assert work["payload"]["project"] == "proj-a"
    assert work["payload"]["preview"] == "content of m-work"
    # 14d retention, saved 24h ago -> 13 days of fuse left
    assert work["payload"]["fades_in_hours"] == 13 * 24
    assert sem["payload"]["fades_in_hours"] is None  # only working-tier rows fade
    assert body["event_window"] == {"events": 0, "oldest_at": None}


def test_stream_recalled_rows_include_misses(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(
        _ev(
            "memory_recalled",
            "proj-a",
            {
                "query": "how to x",
                "memory_ids": ["m1", "m2"],
                "memories": [
                    {"memory_id": "m1", "score": 0.91},
                    {"memory_id": "m2", "score": 0.55},
                ],
                "session_id": None,
            },
            _at(1),
        )
    )
    log.append(
        _ev(
            "memory_recalled",
            "proj-a",
            {"query": "lost cause", "memory_ids": [], "memories": [], "session_id": None},
            _at(0.5),
        )
    )

    r = tc.get("/api/memory/stream")

    assert r.status_code == 200
    rows = r.json()["rows"]
    assert [row["kind"] for row in rows] == ["recalled", "recalled"]
    miss, hit = rows  # newest first
    assert miss["at"] == _at(0.5)
    assert miss["payload"] == {
        "query": "lost cause",
        "memory_ids": [],
        "top_score": None,
        "project": "proj-a",
    }
    assert hit["payload"] == {
        "query": "how to x",
        "memory_ids": ["m1", "m2"],
        "top_score": 0.91,
        "project": "proj-a",
    }


def test_stream_promoted_rows(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.event_log.append(
        _ev(
            "memory_promoted",
            "proj-a",
            {
                "memory_id": "m1",
                "from_tier": "working",
                "to_tier": "semantic",
                "memory_ids": ["m1"],
                "session_id": None,
            },
            _at(1),
        )
    )

    r = tc.get("/api/memory/stream")

    assert r.status_code == 200
    (row,) = r.json()["rows"]
    assert row["kind"] == "promoted"
    assert row["at"] == _at(1)
    assert row["payload"] == {
        "memory_id": "m1",
        "from_tier": "working",
        "to_tier": "semantic",
        "project": "proj-a",
    }


def test_stream_summary_records_become_consolidated_not_saved(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.store.scroll_all.return_value = [
        _record("m-sum", "proj-a", tier="episodic", type="summary", days_ago=1),
    ]

    r = tc.get("/api/memory/stream")

    assert r.status_code == 200
    (row,) = r.json()["rows"]  # exactly one row: no duplicate saved entry
    assert row["kind"] == "consolidated"
    assert row["at"] == _at(1)
    assert row["payload"] == {
        "memory_id": "m-sum",
        "preview": "content of m-sum",
        "project": "proj-a",
    }


def test_stream_project_scope_filters_records_and_events(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(
        _ev(
            "memory_recalled",
            "proj-a",
            {"query": "mine", "memory_ids": ["m1"], "memories": [], "session_id": None},
            _at(1),
        )
    )
    log.append(
        _ev(
            "memory_recalled",
            "proj-b",
            {"query": "theirs", "memory_ids": ["m2"], "memories": [], "session_id": None},
            _at(0.5),
        )
    )
    manager.store.scroll_all.return_value = [_record("r1", "proj-a", days_ago=2)]

    r = tc.get("/api/memory/stream", params={"project": "proj-a"})

    assert r.status_code == 200
    rows = r.json()["rows"]
    assert manager.store.scroll_all.call_args.kwargs.get("filters") == {"project": "proj-a"}
    assert [(row["kind"], row["payload"].get("query")) for row in rows] == [
        ("recalled", "mine"),
        ("saved", None),
    ]


def test_stream_merges_newest_first_and_honors_limit(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(
        _ev(
            "memory_recalled",
            "proj-a",
            {"query": "q", "memory_ids": ["m1"], "memories": [], "session_id": None},
            _at(2),
        )
    )
    log.append(
        _ev(
            "memory_promoted",
            "proj-a",
            {"memory_id": "m1", "from_tier": "working", "to_tier": "episodic",
             "memory_ids": ["m1"], "session_id": None},
            _at(1),
        )
    )
    manager.store.scroll_all.return_value = [
        _record("r-new", "proj-a", days_ago=0),
        _record("r-old", "proj-a", days_ago=3),
    ]

    r = tc.get("/api/memory/stream", params={"limit": 3})

    rows = r.json()["rows"]
    assert [row["kind"] for row in rows] == ["saved", "promoted", "recalled"]
    assert [row["at"] for row in rows] == [_at(0), _at(1), _at(2)]  # r-old cut by limit
