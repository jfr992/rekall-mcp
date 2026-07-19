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


def test_credit_from_feedback_wrong_grants_negative_credit_and_disputed_flag():
    from memory.reinforce import credit_from_feedback

    event = _feedback_event("wrong")

    result = credit_from_feedback(event)

    assert result is not None
    assert result.memory_id == "m1"
    assert result.weight == -1.0
    assert result.outcome_grade is False
    assert result.disputed is True


def test_credit_from_feedback_stale_yields_no_counter_credit():
    from memory.reinforce import credit_from_feedback

    event = _feedback_event("stale")

    assert credit_from_feedback(event) is None


def test_supersedes_candidate_from_feedback_stale():
    from memory.reinforce import supersedes_candidate_from_feedback

    event = _feedback_event("stale")

    candidate = supersedes_candidate_from_feedback(event)

    assert candidate is not None
    assert candidate.memory_id == "m1"
    assert candidate.event_id == event.event_id


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


def test_credit_from_session_grants_outcome_credit_to_top_scored_recall():
    from memory.reinforce import credit_from_session

    summary = _summary_event(edits=2)
    recalls = [_recall_event([{"memory_id": "m1", "score": 0.9}])]

    credits = credit_from_session(summary, recalls)

    assert len(credits) == 1
    assert credits[0].memory_id == "m1"
    assert credits[0].weight == 1.0
    assert credits[0].outcome_grade is True


def test_credit_from_session_no_outcome_grants_bare_credit_not_outcome():
    from memory.reinforce import credit_from_session

    summary = _summary_event(edits=0, test_passes=0)
    recalls = [_recall_event([{"memory_id": "m1", "score": 0.9}])]

    credits = credit_from_session(summary, recalls)

    assert len(credits) == 1
    assert credits[0].memory_id == "m1"
    assert credits[0].weight == 0.25
    assert credits[0].outcome_grade is False


def test_credit_from_session_out_of_margin_recall_gets_bare_not_outcome_credit():
    from memory.reinforce import credit_from_session

    summary = _summary_event(edits=2)
    recalls = [
        _recall_event([{"memory_id": "m1", "score": 0.9}], session_id="sess-1"),
        _recall_event([{"memory_id": "m2", "score": 0.62}], session_id="sess-1"),
    ]

    credits = credit_from_session(summary, recalls)

    by_id = {c.memory_id: c for c in credits}
    assert by_id["m1"].weight == 1.0
    assert by_id["m1"].outcome_grade is True
    assert by_id["m2"].weight == 0.25
    assert by_id["m2"].outcome_grade is False
