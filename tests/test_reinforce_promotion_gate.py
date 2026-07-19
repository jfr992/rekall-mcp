"""Promotion gate: >=5 effective credits (classify() threshold) is necessary
but not sufficient. The reinforce pass additionally requires credits from
>=2 distinct sessions on >=2 distinct days, and >=1 outcome-grade event.
See PLAN.md (T2) Design > Damping & spacing > Promotion eligibility.
"""

from memory.reinforce import HistoryEntry, promotion_eligible


def _entry(event_id, kind, session_id, date):
    return HistoryEntry(event_id=event_id, kind=kind, ts=f"{date}T12:00:00", session_id=session_id)


def test_promotion_eligible_requires_two_sessions_two_days_and_outcome_grade():
    history = [
        _entry("e1", "outcome", "sess-1", "2026-07-01"),
        _entry("e2", "bare", "sess-2", "2026-07-05"),
    ]

    assert promotion_eligible(history) is True


def test_promotion_ineligible_with_single_session():
    history = [
        _entry("e1", "outcome", "sess-1", "2026-07-01"),
        _entry("e2", "bare", "sess-1", "2026-07-05"),
    ]

    assert promotion_eligible(history) is False


def test_promotion_ineligible_with_single_day():
    history = [
        _entry("e1", "outcome", "sess-1", "2026-07-01"),
        _entry("e2", "bare", "sess-2", "2026-07-01"),
    ]

    assert promotion_eligible(history) is False


def test_promotion_ineligible_without_outcome_grade_event():
    history = [
        _entry("e1", "bare", "sess-1", "2026-07-01"),
        _entry("e2", "bare", "sess-2", "2026-07-05"),
    ]

    assert promotion_eligible(history) is False


def test_promotion_eligible_with_useful_feedback_as_outcome_grade():
    history = [
        _entry("e1", "useful", "sess-1", "2026-07-01"),
        _entry("e2", "bare", "sess-2", "2026-07-05"),
    ]

    assert promotion_eligible(history) is True
