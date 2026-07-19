"""Pure credit-extraction functions: recall top-1 gate, session outcome grade,
and feedback verdicts. No I/O — see test_reinforce_processor.py for the
event-log-driven pass.
"""

from memory.events import MemoryEvent
from memory.reinforce import credit_from_recall


def _recall_event(memories, session_id="sess-1", query="q"):
    return MemoryEvent(
        event_type="memory_recalled",
        project="proj-a",
        agent="claude",
        source="recall",
        payload={
            "query": query,
            "session_id": session_id,
            "memory_ids": [m["memory_id"] for m in memories],
            "memories": memories,
        },
    )


def test_credit_from_recall_top1_above_floor_and_within_margin():
    event = _recall_event(
        [
            {"memory_id": "m1", "score": 0.75},
            {"memory_id": "m2", "score": 0.5},
        ]
    )

    candidate = credit_from_recall(event)

    assert candidate is not None
    assert candidate.memory_id == "m1"
    assert candidate.event_id == event.event_id
    assert candidate.session_id == "sess-1"


def test_credit_from_recall_below_score_floor_yields_none():
    event = _recall_event([{"memory_id": "m1", "score": 0.55}])

    assert credit_from_recall(event) is None


def test_credit_from_recall_no_memories_yields_none():
    event = _recall_event([])

    assert credit_from_recall(event) is None


def _feedback_event(verdict, memory_id="m1", session_id="sess-1"):
    return MemoryEvent(
        event_type="memory_feedback",
        project="proj-a",
        agent="claude",
        source="feedback_endpoint",
        payload={"memory_id": memory_id, "verdict": verdict, "session_id": session_id},
    )


def test_credit_from_feedback_useful_grants_outcome_credit():
    from memory.reinforce import credit_from_feedback

    event = _feedback_event("useful")

    result = credit_from_feedback(event)

    assert result is not None
    assert result.memory_id == "m1"
    assert result.weight == 1.0
    assert result.outcome_grade is True
