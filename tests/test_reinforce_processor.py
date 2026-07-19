"""End-to-end reinforce pass: EventLog.read_from + checkpoint + lock +
apply_reinforcement + classify() reclassify + memory_promoted emission.
"""

from datetime import datetime
from unittest.mock import MagicMock

from memory.events import EventLog, MemoryEvent
from memory.reinforce import process_events


def _make_log(tmp_path):
    return EventLog(tmp_path / "_events.jsonl")


def _memory(memory_id, **overrides):
    base = {
        "memory_id": memory_id,
        "type": "note",
        "tier": "working",
        "date": "2026-06-01",
        "reinforcement_count": 0,
        "history": [],
        "salience": 0.0,
        "project": "proj-a",
    }
    base.update(overrides)
    return base


def _fake_store(memories):
    store = MagicMock()
    by_id = {m["memory_id"]: dict(m) for m in memories}
    store.get_by_id.side_effect = lambda mid: by_id.get(mid)

    def _update(mid, payload):
        by_id[mid].update(payload)

    store.update_payload.side_effect = _update
    store._by_id = by_id
    return store


def _fake_graph():
    graph = MagicMock()
    graph.count_contradicts.return_value = 0
    return graph


def test_process_events_applies_bare_recall_credit_and_persists_history(tmp_path):
    log = _make_log(tmp_path)
    log.append(
        MemoryEvent(
            event_type="memory_recalled",
            project="proj-a",
            agent="claude",
            source="recall",
            payload={
                "session_id": "sess-1",
                "memory_ids": ["m1"],
                "memories": [{"memory_id": "m1", "score": 0.9}],
            },
        )
    )
    log.append(
        MemoryEvent(
            event_type="session_summary",
            project="proj-a",
            agent="claude",
            source="observe_hook",
            payload={
                "session_id": "sess-1",
                "edits_after_recall": 0,
                "test_passes_after_recall": 0,
            },
        )
    )

    store = _fake_store([_memory("m1")])
    graph = _fake_graph()
    record_event = MagicMock()

    process_events(
        event_log=log,
        store=store,
        graph=graph,
        state_path=tmp_path / "_reinforce_state.json",
        lock_path=tmp_path / "_reinforce.lock",
        now=datetime(2026, 7, 18, 12, 0, 0),
        record_event=record_event,
    )

    updated = store._by_id["m1"]
    assert len(updated["history"]) == 1
    assert updated["history"][0]["kind"] == "bare"


def test_process_events_second_call_is_idempotent_no_new_history_entries(tmp_path):
    log = _make_log(tmp_path)
    log.append(
        MemoryEvent(
            event_type="memory_recalled",
            project="proj-a",
            agent="claude",
            source="recall",
            payload={
                "session_id": "sess-1",
                "memory_ids": ["m1"],
                "memories": [{"memory_id": "m1", "score": 0.9}],
            },
        )
    )
    log.append(
        MemoryEvent(
            event_type="session_summary",
            project="proj-a",
            agent="claude",
            source="observe_hook",
            payload={
                "session_id": "sess-1",
                "edits_after_recall": 0,
                "test_passes_after_recall": 0,
            },
        )
    )

    store = _fake_store([_memory("m1")])
    graph = _fake_graph()
    record_event = MagicMock()
    state_path = tmp_path / "_reinforce_state.json"
    lock_path = tmp_path / "_reinforce.lock"
    now = datetime(2026, 7, 18, 12, 0, 0)

    process_events(
        event_log=log,
        store=store,
        graph=graph,
        state_path=state_path,
        lock_path=lock_path,
        now=now,
        record_event=record_event,
    )
    process_events(
        event_log=log,
        store=store,
        graph=graph,
        state_path=state_path,
        lock_path=lock_path,
        now=now,
        record_event=record_event,
    )

    assert len(store._by_id["m1"]["history"]) == 1


def test_process_events_wrong_feedback_sets_disputed_flag(tmp_path):
    log = _make_log(tmp_path)
    log.append(
        MemoryEvent(
            event_type="memory_feedback",
            project="proj-a",
            agent="claude",
            source="feedback_endpoint",
            payload={"memory_id": "m1", "verdict": "wrong", "session_id": "sess-1"},
        )
    )

    store = _fake_store([_memory("m1")])
    graph = _fake_graph()

    process_events(
        event_log=log,
        store=store,
        graph=graph,
        state_path=tmp_path / "_reinforce_state.json",
        lock_path=tmp_path / "_reinforce.lock",
        now=datetime(2026, 7, 18, 12, 0, 0),
        record_event=MagicMock(),
    )

    assert store._by_id["m1"]["disputed"] is True


def test_process_events_truncated_log_halts_without_advancing_checkpoint(tmp_path):
    from memory.reinforce import ReinforceState, save_state

    log = _make_log(tmp_path)
    log.append(
        MemoryEvent(
            event_type="memory_feedback",
            project="proj-a",
            agent="claude",
            source="feedback_endpoint",
            payload={"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
        )
    )

    state_path = tmp_path / "_reinforce_state.json"
    # A cursor claiming an offset far past the actual (small) log file is
    # detected as stale by EventLog.read_from -> truncated=True.
    stale_cursor = "eyJvZmZzZXQiOiA5OTk5OTk5LCAic2lnIjogImRlYWRiZWVmMDAwMDoxMDAwMDAwIn0="
    save_state(state_path, ReinforceState(cursor=stale_cursor, processed_sessions=frozenset()))

    store = _fake_store([_memory("m1")])
    graph = _fake_graph()

    process_events(
        event_log=log,
        store=store,
        graph=graph,
        state_path=state_path,
        lock_path=tmp_path / "_reinforce.lock",
        now=datetime(2026, 7, 18, 12, 0, 0),
        record_event=MagicMock(),
    )

    store.get_by_id.assert_not_called()
    from memory.reinforce import load_state

    assert load_state(state_path).cursor == stale_cursor
