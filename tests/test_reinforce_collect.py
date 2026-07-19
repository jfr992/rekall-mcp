"""Pure aggregation: fold a batch of events into per-memory credits, the set
of newly-processed sessions, and stale-supersedes candidates. No I/O.
"""

from memory.events import MemoryEvent
from memory.reinforce import collect_credits


def _recall_event(memories, session_id="sess-1"):
    return MemoryEvent(
        event_type="memory_recalled",
        project="proj-a",
        agent="claude",
        source="recall",
        payload={
            "query": "q",
            "session_id": session_id,
            "memory_ids": [m["memory_id"] for m in memories],
            "memories": memories,
        },
    )


def _summary_event(session_id="sess-1", edits=1, test_passes=0):
    return MemoryEvent(
        event_type="session_summary",
        project="proj-a",
        agent="claude",
        source="observe_hook",
        payload={
            "session_id": session_id,
            "edits_after_recall": edits,
            "test_passes_after_recall": test_passes,
        },
    )


def test_collect_credits_from_session_summary_and_its_recall():
    events = [
        _recall_event([{"memory_id": "m1", "score": 0.9}]),
        _summary_event(edits=2),
    ]

    result = collect_credits(events, processed_sessions=frozenset())

    assert len(result.credits) == 1
    assert result.credits[0].memory_id == "m1"
    assert result.credits[0].weight == 1.0
    assert result.newly_processed_sessions == {"sess-1"}


def test_collect_credits_skips_already_processed_session():
    events = [
        _recall_event([{"memory_id": "m1", "score": 0.9}]),
        _summary_event(edits=2),
    ]

    result = collect_credits(events, processed_sessions=frozenset({"sess-1"}))

    assert result.credits == []
    assert result.newly_processed_sessions == set()


def _feedback_event(verdict, memory_id="m1", session_id="sess-1"):
    return MemoryEvent(
        event_type="memory_feedback",
        project="proj-a",
        agent="claude",
        source="feedback_endpoint",
        payload={"memory_id": memory_id, "verdict": verdict, "session_id": session_id},
    )


def test_collect_credits_includes_feedback_and_supersedes_candidate():
    events = [
        _feedback_event("useful", memory_id="m1"),
        _feedback_event("stale", memory_id="m2"),
    ]

    result = collect_credits(events, processed_sessions=frozenset())

    assert len(result.credits) == 1
    assert result.credits[0].memory_id == "m1"
    assert result.credits[0].weight == 1.0
    assert len(result.supersedes_candidates) == 1
    assert result.supersedes_candidates[0].memory_id == "m2"


def test_collect_credits_carries_the_source_events_own_observed_at():
    event = _feedback_event("useful", memory_id="m1")

    result = collect_credits([event], processed_sessions=frozenset())

    assert result.credits[0].observed_at == event.observed_at


def test_collect_credits_from_session_summary_carries_summarys_observed_at():
    summary = _summary_event(edits=2)
    events = [_recall_event([{"memory_id": "m1", "score": 0.9}]), summary]

    result = collect_credits(events, processed_sessions=frozenset())

    assert result.credits[0].observed_at == summary.observed_at
