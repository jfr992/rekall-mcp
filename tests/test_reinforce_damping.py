"""Damping + spacing: nth-in-30d diminishing returns, 20-entry history cap.

See PLAN.md (T2) Design > Damping & spacing. Pure functions over a history
list — no I/O, no store access.
"""

from datetime import datetime

from memory.reinforce import HistoryEntry, apply_reinforcement


def test_apply_reinforcement_first_credit_is_undamped():
    now = datetime(2026, 7, 18, 12, 0, 0)

    result = apply_reinforcement(history=[], weight=1.0, event_id="e1", kind="outcome", now=now)

    assert result.delta == 1.0


def test_apply_reinforcement_second_credit_in_window_is_damped():
    now = datetime(2026, 7, 18, 12, 0, 0)
    history = [HistoryEntry(event_id="e1", kind="outcome", ts=now.isoformat())]

    result = apply_reinforcement(
        history=history, weight=1.0, event_id="e2", kind="outcome", now=now
    )

    assert result.delta == 1.0 / 1.5


def test_apply_reinforcement_ignores_entries_older_than_30_days():
    from datetime import timedelta

    now = datetime(2026, 7, 18, 12, 0, 0)
    old_ts = (now - timedelta(days=31)).isoformat()
    history = [HistoryEntry(event_id="e1", kind="outcome", ts=old_ts)]

    result = apply_reinforcement(
        history=history, weight=1.0, event_id="e2", kind="outcome", now=now
    )

    assert result.delta == 1.0


def test_apply_reinforcement_wrong_penalty_is_undamped():
    now = datetime(2026, 7, 18, 12, 0, 0)
    history = [
        HistoryEntry(event_id="e1", kind="outcome", ts=now.isoformat()),
        HistoryEntry(event_id="e2", kind="outcome", ts=now.isoformat()),
    ]

    result = apply_reinforcement(history=history, weight=-1.0, event_id="e3", kind="wrong", now=now)

    assert result.delta == -1.0


def test_apply_reinforcement_history_capped_at_20_entries():
    now = datetime(2026, 7, 18, 12, 0, 0)
    history = [
        HistoryEntry(event_id=f"e{i}", kind="outcome", ts=now.isoformat()) for i in range(20)
    ]

    result = apply_reinforcement(
        history=history, weight=1.0, event_id="e20", kind="outcome", now=now
    )

    assert len(result.history) == 20
    assert result.history[0].event_id == "e1"
    assert result.history[-1].event_id == "e20"
