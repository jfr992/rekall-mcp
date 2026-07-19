"""Durable checkpoint for the reinforce processor: cursor + processed-session
set, persisted outside the event log so a truncated/rewritten log is
detected instead of blind-replayed. See PLAN.md (T2) Mechanism.
"""

from memory.reinforce import ReinforceState, load_state, save_state


def test_load_state_missing_file_returns_fresh_state(tmp_path):
    state_path = tmp_path / "_reinforce_state.json"

    state = load_state(state_path)

    assert state == ReinforceState(cursor=None, processed_sessions=frozenset())


def test_save_then_load_state_round_trips(tmp_path):
    state_path = tmp_path / "_reinforce_state.json"
    state = ReinforceState(cursor="abc123", processed_sessions=frozenset({"sess-1", "sess-2"}))

    save_state(state_path, state)
    loaded = load_state(state_path)

    assert loaded == state
