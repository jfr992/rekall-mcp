from memory.pressure import identify_pressure, render_pressure_report


def test_identify_pressure_finds_low_value_and_stale_working():
    memories = [
        {
            "memory_id": "a",
            "tier": "working",
            "retention_days": 14,
            "salience": 0.2,
            "date": "2026-03-01",
            "content": "opened file x",
            "type": "note",
        },
        {
            "memory_id": "b",
            "tier": "semantic",
            "retention_days": 365,
            "salience": 0.9,
            "date": "2026-04-10",
            "content": "Use PostgreSQL",
            "type": "decision",
        },
    ]

    pressure = identify_pressure(memories, today="2026-04-10")
    assert pressure["low_value_count"] == 1
    assert pressure["stale_working_count"] == 1
    assert len(pressure["candidates"]) == 1


def test_render_pressure_report_has_header():
    report = render_pressure_report(
        {"low_value_count": 1, "stale_working_count": 1, "candidates": []}
    )
    assert "Memory Pressure Report" in report


def test_identify_pressure_returns_labeled_lists():
    """T5: per-reason lists so the UI can group flags (was one merged blob)."""
    from memory.pressure import identify_pressure

    memories = [
        {"memory_id": "lv1", "tier": "working", "salience": 0.1, "content": "low"},
        {
            "memory_id": "st1",
            "tier": "working",
            "salience": 0.9,
            "retention_days": 1,
            "date": "2020-01-01",
            "content": "stale",
        },
    ]
    p = identify_pressure(memories)
    assert [m["memory_id"] for m in p["low_value"]] == ["lv1"]
    assert [m["memory_id"] for m in p["stale_working"]] == ["st1"]


def test_identify_pressure_surfaces_disputed_memories():
    """T5: disputed=true (set by reinforce.py on a `wrong` verdict) is its own
    flagged reason, distinct from low_value/stale_working."""
    from memory.pressure import identify_pressure

    memories = [
        {
            "memory_id": "d1",
            "tier": "semantic",
            "salience": 0.9,
            "content": "disputed",
            "disputed": True,
        },
        {
            "memory_id": "ok1",
            "tier": "semantic",
            "salience": 0.9,
            "content": "fine",
            "disputed": False,
        },
        {"memory_id": "ok2", "tier": "semantic", "salience": 0.9, "content": "no flag at all"},
    ]
    p = identify_pressure(memories)
    assert [m["memory_id"] for m in p["disputed"]] == ["d1"]
    assert p["disputed_count"] == 1


def test_stale_candidate_memory_ids_dedupes_repeated_events_in_first_seen_order():
    """T5: memory_supersedes_candidate events (T2's payload shape:
    {memory_id, reason}) collapse repeats for the same memory_id — a stale
    verdict re-fired for the same memory shouldn't double up in the list."""
    from memory.events import MemoryEvent
    from memory.pressure import stale_candidate_memory_ids

    events = [
        MemoryEvent(
            event_type="memory_supersedes_candidate",
            project="general",
            agent="unknown",
            source="reinforcement",
            payload={"memory_id": "s1", "reason": "stale_feedback"},
        ),
        MemoryEvent(
            event_type="memory_recalled",
            project="general",
            agent="unknown",
            source="client",
            payload={"memory_id": "irrelevant"},
        ),
        MemoryEvent(
            event_type="memory_supersedes_candidate",
            project="general",
            agent="unknown",
            source="reinforcement",
            payload={"memory_id": "s2", "reason": "stale_feedback"},
        ),
        MemoryEvent(
            event_type="memory_supersedes_candidate",
            project="general",
            agent="unknown",
            source="reinforcement",
            payload={"memory_id": "s1", "reason": "stale_feedback"},
        ),
    ]

    assert stale_candidate_memory_ids(events) == ["s1", "s2"]
