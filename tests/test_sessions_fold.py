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
