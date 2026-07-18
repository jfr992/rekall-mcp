"""fold_sessions: pure fold of U1 events into session objects (U2 Task 1).

Field truth (verified against src): session_summary recalled ids live under
payload.memory_ids (record_event merges them); memory_recalled events are
null-session today (manager hardcodes session_id=None); memory_surfaced
carries session_id when the capsule GET receives one.
"""

from memory.events import MemoryEvent


def _ev(event_type, project, payload, observed_at, source="test"):
    return MemoryEvent(
        event_type=event_type,
        project=project,
        agent="claude-code",
        source=source,
        payload=payload,
        observed_at=observed_at,
    )


def _surfaced(session_id, project, memory_ids, observed_at, tokens=40):
    return _ev(
        "memory_surfaced",
        project,
        {"memory_ids": memory_ids, "token_estimate": tokens, "session_id": session_id},
        observed_at,
    )


def _summary(session_id, project, memory_ids, observed_at):
    return _ev(
        "session_summary",
        project,
        {"memory_ids": memory_ids, "session_id": session_id},
        observed_at,
    )


def _recalled(project, memory_ids, observed_at, query="q", tokens=20, session_id=None):
    return _ev(
        "memory_recalled",
        project,
        {
            "query": query,
            "task_hint": None,
            "memories": [{"memory_id": m, "score": 0.9} for m in memory_ids],
            "token_estimate": tokens,
            "session_id": session_id,
            "capture_origin": None,
            "memory_ids": memory_ids,
        },
        observed_at,
    )


def test_fold_groups_summary_and_surfaced_by_session_id():
    from memory.sessions import fold_sessions

    events = [
        _surfaced("s1", "proj-a", ["m1", "m2"], "2026-07-14T09:00:00", tokens=40),
        _summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"),
        _summary("s1", "proj-a", ["m1"], "2026-07-14T09:20:00"),
        _summary("s2", "proj-a", ["m3"], "2026-07-14T09:30:00"),
    ]

    sessions = fold_sessions(events)

    by_id = {s["session_id"]: s for s in sessions}
    assert set(by_id) == {"s1", "s2"}
    s1 = by_id["s1"]
    assert s1["project"] == "proj-a"
    assert s1["started_at"] == "2026-07-14T09:00:00"
    assert s1["last_at"] == "2026-07-14T09:20:00"
    assert [i["memory_id"] for i in s1["injected"]] == ["m1", "m2"]
    assert s1["recalls"] == []
    assert s1["totals"] == {"recalls": 0, "injected": 2, "tokens": 40}


def test_null_session_recall_joins_via_memory_ids_intersection():
    from memory.sessions import fold_sessions

    events = [
        _summary("s1", "proj-a", ["m1", "m2"], "2026-07-14T09:30:00"),
        _recalled("proj-a", ["m2", "m9"], "2026-07-14T09:05:00", query="how to x", tokens=25),
    ]

    sessions = fold_sessions(events)

    (s1,) = [s for s in sessions if s["session_id"] == "s1"]
    assert len(s1["recalls"]) == 1
    recall = s1["recalls"][0]
    assert recall["query"] == "how to x"
    assert recall["memories"] == [
        {"memory_id": "m2", "score": 0.9},
        {"memory_id": "m9", "score": 0.9},
    ]
    assert recall["token_estimate"] == 25
    assert recall["observed_at"] == "2026-07-14T09:05:00"
    assert s1["totals"]["recalls"] == 1
    assert s1["totals"]["tokens"] == 25


def test_unscoped_recall_stamped_general_joins_via_intersection():
    """manager.recall stamps project or 'general' — an unscoped recall_memories
    call emits project='general' while the summary carries the real project.
    The intersection stays the strong condition; 'general' must not block it."""
    from memory.sessions import fold_sessions

    events = [
        _summary("s1", "proj-a", ["m1"], "2026-07-14T10:00:00"),
        _recalled("general", ["m1"], "2026-07-14T09:45:00", query="unscoped"),
    ]

    sessions = fold_sessions(events)

    by_id = {s["session_id"]: s for s in sessions}
    assert "unattributed:general" not in by_id
    assert len(by_id["s1"]["recalls"]) == 1
    assert by_id["s1"]["recalls"][0]["query"] == "unscoped"


def test_unscoped_recall_without_intersection_stays_unattributed():
    """Relaxing the project check must not weaken the join: an unscoped recall
    whose ids intersect no summary still lands in the honest bucket."""
    from memory.sessions import fold_sessions

    events = [
        _summary("s1", "proj-a", ["m1"], "2026-07-14T10:00:00"),
        _recalled("general", ["m9"], "2026-07-14T09:45:00"),
    ]

    sessions = fold_sessions(events)

    by_id = {s["session_id"]: s for s in sessions}
    assert by_id["s1"]["recalls"] == []
    assert by_id["unattributed:general"]["totals"]["recalls"] == 1


def test_scoped_recall_with_mismatched_project_stays_unattributed():
    """A project mismatch on a SCOPED recall is a real signal — intersecting
    ids alone must not attach it to another project's session."""
    from memory.sessions import fold_sessions

    events = [
        _summary("s1", "proj-a", ["m1"], "2026-07-14T10:00:00"),
        _recalled("proj-b", ["m1"], "2026-07-14T09:45:00"),
    ]

    sessions = fold_sessions(events)

    by_id = {s["session_id"]: s for s in sessions}
    assert by_id["s1"]["recalls"] == []
    assert by_id["unattributed:proj-b"]["totals"]["recalls"] == 1


def test_concurrent_same_project_sessions_do_not_cross_attribute():
    """Project+time alone would attach the recall to both windows; memory_ids
    intersection (SPEC 1a) must route it only to the session that recalled it."""
    from memory.sessions import fold_sessions

    events = [
        _summary("s1", "proj-a", ["m1"], "2026-07-14T10:00:00"),
        _summary("s2", "proj-a", ["m2"], "2026-07-14T10:00:30"),
        _recalled("proj-a", ["m2"], "2026-07-14T09:45:00"),
    ]

    sessions = fold_sessions(events)

    by_id = {s["session_id"]: s for s in sessions}
    assert by_id["s1"]["recalls"] == []
    assert len(by_id["s2"]["recalls"]) == 1
    assert by_id["s2"]["recalls"][0]["memories"][0]["memory_id"] == "m2"


def test_non_matching_recalls_land_in_per_project_unattributed_bucket():
    from memory.sessions import fold_sessions

    events = [
        _summary("s1", "proj-a", ["m1"], "2026-07-14T10:00:00"),
        # no id intersection with s1's summary → unattributed
        _recalled("proj-a", ["m7"], "2026-07-14T09:50:00", query="lost"),
        # different project, no session at all → its own bucket
        _recalled("proj-b", ["m8"], "2026-07-14T09:55:00"),
    ]

    sessions = fold_sessions(events)

    by_id = {s["session_id"]: s for s in sessions}
    assert set(by_id) == {"s1", "unattributed:proj-a", "unattributed:proj-b"}
    bucket_a = by_id["unattributed:proj-a"]
    assert bucket_a["project"] == "proj-a"
    assert bucket_a["recalls"][0]["query"] == "lost"
    assert bucket_a["totals"]["recalls"] == 1
    assert bucket_a["injected"] == []
    assert by_id["s1"]["recalls"] == []


# ---------------------------------------------------------------------------
# REST endpoints: GET /api/memory/sessions + GET /api/memory/sessions/{id}
# ---------------------------------------------------------------------------


def _rest_client(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server
    from memory.events import EventLog

    manager = MagicMock()
    manager.event_log = EventLog(tmp_path / "_events.jsonl")
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_get_sessions_list_shape_limit_and_window(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_surfaced("s1", "proj-a", ["m1"], "2026-07-14T09:00:00", tokens=10))
    log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))
    log.append(_summary("s2", "proj-a", ["m2"], "2026-07-14T09:20:00"))

    r = tc.get("/api/memory/sessions", params={"limit": 1})

    assert r.status_code == 200
    body = r.json()
    assert body["window"] == 5000
    assert len(body["sessions"]) == 1
    row = body["sessions"][0]
    assert row["session_id"] == "s2"  # newest activity first
    assert row["project"] == "proj-a"
    assert set(row) == {"session_id", "project", "started_at", "last_at", "totals"}
    assert row["totals"] == {"recalls": 0, "injected": 0, "tokens": 0}


def test_get_sessions_project_filter_returns_scoped_plus_unattributed(monkeypatch, tmp_path):
    """?project= filters AFTER folding (join needs all events) — the selected
    project's sessions plus its honest unattributed bucket, nothing else."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))
    log.append(_summary("s2", "proj-b", ["m2"], "2026-07-14T09:20:00"))
    # no id intersection with s1's summary → unattributed:proj-a
    log.append(_recalled("proj-a", ["m9"], "2026-07-14T09:30:00", query="lost"))

    r = tc.get("/api/memory/sessions", params={"project": "proj-a"})

    assert r.status_code == 200
    body = r.json()
    ids = {s["session_id"] for s in body["sessions"]}
    assert ids == {"s1", "unattributed:proj-a"}
    assert all(s["project"] == "proj-a" for s in body["sessions"])


def test_get_sessions_limit_applies_after_project_filter(monkeypatch, tmp_path):
    """Newer sessions from other projects must not starve the scoped list."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))
    log.append(_summary("s2", "proj-b", ["m2"], "2026-07-14T09:20:00"))  # newest

    r = tc.get("/api/memory/sessions", params={"project": "proj-a", "limit": 1})

    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s1"]


def test_get_sessions_project_all_returns_every_project(monkeypatch, tmp_path):
    """?project=all is the explicit 'all memories' scope — no filtering."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))
    log.append(_summary("s2", "proj-b", ["m2"], "2026-07-14T09:20:00"))

    r = tc.get("/api/memory/sessions", params={"project": "all"})

    assert r.status_code == 200
    assert {s["session_id"] for s in r.json()["sessions"]} == {"s1", "s2"}


def test_get_session_detail_returns_full_object(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_surfaced("s1", "proj-a", ["m1"], "2026-07-14T09:00:00", tokens=10))
    log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))
    log.append(_recalled("proj-a", ["m1"], "2026-07-14T09:05:00", query="why m1", tokens=5))

    r = tc.get("/api/memory/sessions/s1")

    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s1"
    assert body["injected"] == [{"memory_id": "m1", "token_estimate": None}]
    assert body["recalls"][0]["query"] == "why m1"
    assert body["recalls"][0]["memories"] == [{"memory_id": "m1", "score": 0.9}]
    assert body["totals"] == {"recalls": 1, "injected": 1, "tokens": 15}
    assert body["window"] == 5000


def test_get_session_detail_unknown_id_404(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.event_log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))

    r = tc.get("/api/memory/sessions/nope")

    assert r.status_code == 404
    assert r.json()["session_id"] == "nope"


def test_get_sessions_after_filters_older_days_inclusive(monkeypatch, tmp_path):
    """?after= keeps sessions whose last activity day is >= the bound."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s-old", "proj-a", ["m1"], "2026-07-10T09:00:00"))
    log.append(_summary("s-edge", "proj-a", ["m2"], "2026-07-12T09:00:00"))
    log.append(_summary("s-new", "proj-a", ["m3"], "2026-07-14T09:00:00"))

    r = tc.get("/api/memory/sessions", params={"after": "2026-07-12"})

    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s-new", "s-edge"]


def test_get_sessions_before_filters_newer_days_inclusive(monkeypatch, tmp_path):
    """?before= keeps sessions whose last activity day is <= the bound."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s-old", "proj-a", ["m1"], "2026-07-10T09:00:00"))
    log.append(_summary("s-edge", "proj-a", ["m2"], "2026-07-12T09:00:00"))
    log.append(_summary("s-new", "proj-a", ["m3"], "2026-07-14T09:00:00"))

    r = tc.get("/api/memory/sessions", params={"before": "2026-07-12"})

    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s-edge", "s-old"]


def test_get_sessions_after_and_before_bound_one_day(monkeypatch, tmp_path):
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s-old", "proj-a", ["m1"], "2026-07-10T09:00:00"))
    log.append(_summary("s-edge", "proj-a", ["m2"], "2026-07-12T09:00:00"))
    log.append(_summary("s-new", "proj-a", ["m3"], "2026-07-14T09:00:00"))

    r = tc.get("/api/memory/sessions", params={"after": "2026-07-12", "before": "2026-07-12"})

    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s-edge"]


def test_get_sessions_rejects_malformed_day_bounds(monkeypatch, tmp_path):
    tc, _ = _rest_client(monkeypatch, tmp_path)
    assert tc.get("/api/memory/sessions", params={"after": "yesterday"}).status_code == 400
    assert tc.get("/api/memory/sessions", params={"before": "2026/07/01"}).status_code == 400


def test_get_sessions_default_window_unchanged_without_day_params(monkeypatch, tmp_path):
    """No after/before → every folded session in the event window, as before."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    log = manager.event_log
    log.append(_summary("s-old", "proj-a", ["m1"], "2026-07-01T09:00:00"))
    log.append(_summary("s-new", "proj-a", ["m2"], "2026-07-14T09:00:00"))

    r = tc.get("/api/memory/sessions")

    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()["sessions"]] == ["s-new", "s-old"]


def test_get_sessions_event_window_marker_survives_range_filter(monkeypatch, tmp_path):
    """The response carries the stream-style event_window marker so the UI can
    say which sessions it cannot see, even when the range hides every row."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.event_log.append(_summary("s-old", "proj-a", ["m1"], "2026-07-01T09:00:00"))

    r = tc.get("/api/memory/sessions", params={"after": "2026-07-10"})

    assert r.status_code == 200
    body = r.json()
    assert body["sessions"] == []
    assert body["event_window"] == {"events": 1, "oldest_at": "2026-07-01T09:00:00"}


def test_sessions_list_get_emits_view_opened_counter(monkeypatch, tmp_path):
    """The U2 phase metric: % of sessions where the view was opened."""
    tc, manager = _rest_client(monkeypatch, tmp_path)
    manager.event_log.append(_summary("s1", "proj-a", ["m1"], "2026-07-14T09:10:00"))

    r = tc.get("/api/memory/sessions")

    assert r.status_code == 200
    manager.record_event.assert_called_once()
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "view_opened"
    assert kw["payload"]["view"] == "sessions"
