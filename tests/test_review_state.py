"""Review-state projection: rebuild/apply/write/staleness + POST /api/memory/review (U1 Task 4)."""

from memory import review_state


def _reviewed(mid: str, verdict: str = "keep", editor: str = "ui", at: str = "2026-07-14T10:00:00"):
    return {
        "event_type": "memory_reviewed",
        "project": "p",
        "agent": "unknown",
        "source": "review_endpoint",
        "observed_at": at,
        "payload": {"memory_id": mid, "verdict": verdict, "editor": editor},
    }


def test_apply_event_folds_review_verdicts():
    state = review_state.apply_event({}, _reviewed("m1", "keep"))
    state = review_state.apply_event(state, _reviewed("m1", "kill", at="2026-07-14T11:00:00"))

    entry = state["m1"]
    assert entry["last_verdict"] == "kill"
    assert entry["verdict_editor"] == "ui"
    assert entry["reviewed_at"] == "2026-07-14T11:00:00"
    assert entry["review_count"] == 2
