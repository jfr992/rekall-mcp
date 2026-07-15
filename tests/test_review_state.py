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


def _write_events(tmp_path, events):
    import json

    lines = "".join(json.dumps(e) + "\n" for e in events)
    (tmp_path / "_events.jsonl").write_text(lines)


def test_rebuild_scans_events_jsonl(tmp_path):
    _write_events(
        tmp_path,
        [
            _reviewed("m1", "keep"),
            {
                "event_type": "memory_updated",
                "observed_at": "2026-07-14T12:00:00",
                "payload": {"memory_id": "m2"},
            },
            {
                "event_type": "memory_pruned",
                "observed_at": "2026-07-14T13:00:00",
                "payload": {"memory_ids": ["m3", "m4"]},
            },
            {"event_type": "memory_recalled", "payload": {"memory_ids": ["m1"]}},  # ignored
        ],
    )

    state = review_state.rebuild(tmp_path)

    assert state["m1"]["last_verdict"] == "keep"
    assert state["m2"]["updated_at"] == "2026-07-14T12:00:00"
    assert state["m3"]["pruned_at"] == "2026-07-14T13:00:00"
    assert state["m4"]["pruned_at"] == "2026-07-14T13:00:00"
    assert set(state) == {"m1", "m2", "m3", "m4"}


def test_write_then_load_roundtrip_atomic(tmp_path):
    _write_events(tmp_path, [_reviewed("m1", "keep")])
    state = review_state.rebuild(tmp_path)

    review_state.write(tmp_path, state)

    assert (tmp_path / "_review_state.json").exists()
    assert not list(tmp_path.glob("*.tmp"))  # tmp+os.replace leaves no droppings
    assert review_state.load(tmp_path) == state


def test_load_rebuilds_when_older_than_events_file(tmp_path):
    """Tarball restore: a restored projection older than the log must self-heal."""
    import json
    import os

    _write_events(tmp_path, [_reviewed("m1", "keep")])
    review_state.write(tmp_path, review_state.rebuild(tmp_path))

    with (tmp_path / "_events.jsonl").open("a") as f:
        f.write(json.dumps(_reviewed("m1", "kill", at="2026-07-14T11:00:00")) + "\n")
    stale = (tmp_path / "_events.jsonl").stat().st_mtime - 60
    os.utime(tmp_path / "_review_state.json", (stale, stale))

    state = review_state.load(tmp_path)

    assert state["m1"]["last_verdict"] == "kill"
    assert state["m1"]["review_count"] == 2
    # and the rebuilt projection was persisted (fresh mtime)
    assert (tmp_path / "_review_state.json").stat().st_mtime >= (
        tmp_path / "_events.jsonl"
    ).stat().st_mtime


def test_load_rebuilds_when_missing_or_unparseable(tmp_path):
    _write_events(tmp_path, [_reviewed("m1", "keep")])

    # missing → rebuild
    assert review_state.load(tmp_path)["m1"]["last_verdict"] == "keep"

    # unparseable → rebuild, not crash (touch events older so mtime check passes)
    (tmp_path / "_review_state.json").write_text("{corrupt")
    assert review_state.load(tmp_path)["m1"]["last_verdict"] == "keep"


# ---------------------------------------------------------------------------
# POST /api/memory/review
# ---------------------------------------------------------------------------


def _review_client(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server
    from memory.events import EventLog

    manager = MagicMock()
    manager.memory_dir = tmp_path
    manager.event_log = EventLog(tmp_path / "_events.jsonl")
    manager.store.get_many.return_value = [{"memory_id": "m1", "project": "my-app"}]
    manager.delete.return_value = True
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_review_keep_records_event_only(monkeypatch, tmp_path):
    client, manager = _review_client(monkeypatch, tmp_path)

    r = client.post(
        "/api/memory/review", json={"memory_id": "m1", "verdict": "keep", "editor": "ui"}
    )

    assert r.status_code == 200
    manager.delete.assert_not_called()
    events = manager.event_log.tail(limit=1)
    assert events[0].event_type == "memory_reviewed"
    assert events[0].project == "my-app"
    assert events[0].payload["verdict"] == "keep"
    assert events[0].payload["editor"] == "ui"
    # server-only writer: the projection is refreshed in the same request
    assert review_state.load(tmp_path)["m1"]["last_verdict"] == "keep"


def test_review_kill_deletes_then_records(monkeypatch, tmp_path):
    client, manager = _review_client(monkeypatch, tmp_path)
    events_path = tmp_path / "_events.jsonl"

    def _delete(memory_id):
        # mutate-then-record: at delete time the review event must not exist yet
        assert not events_path.exists() or "memory_reviewed" not in events_path.read_text()
        return True

    manager.delete.side_effect = _delete

    r = client.post(
        "/api/memory/review", json={"memory_id": "m1", "verdict": "kill", "editor": "agent"}
    )

    assert r.status_code == 200
    assert r.json()["deleted"] is True
    manager.delete.assert_called_once_with("m1")
    events = manager.event_log.tail(limit=1)
    assert events[0].payload["verdict"] == "kill"
    assert events[0].payload["editor"] == "agent"


def test_review_kill_not_found_returns_404_no_event(monkeypatch, tmp_path):
    client, manager = _review_client(monkeypatch, tmp_path)
    manager.delete.return_value = False

    r = client.post(
        "/api/memory/review", json={"memory_id": "m1", "verdict": "kill", "editor": "ui"}
    )

    assert r.status_code == 404
    assert not (tmp_path / "_events.jsonl").exists()


def test_review_fix_returns_501_with_honest_message(monkeypatch, tmp_path):
    client, manager = _review_client(monkeypatch, tmp_path)

    r = client.post(
        "/api/memory/review", json={"memory_id": "m1", "verdict": "fix", "editor": "ui"}
    )

    assert r.status_code == 501
    assert "U3" in r.json()["error"]
    manager.delete.assert_not_called()
    assert not (tmp_path / "_events.jsonl").exists()


def test_review_rejects_bad_verdict_and_editor(monkeypatch, tmp_path):
    client, _ = _review_client(monkeypatch, tmp_path)

    assert (
        client.post(
            "/api/memory/review", json={"memory_id": "m1", "verdict": "yeet", "editor": "ui"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/memory/review", json={"memory_id": "m1", "verdict": "keep", "editor": "cli"}
        ).status_code
        == 400
    )
    assert (
        client.post("/api/memory/review", json={"verdict": "keep", "editor": "ui"}).status_code
        == 400
    )


def test_review_failed_event_write_logs_loudly_not_silently(monkeypatch, tmp_path, caplog):
    """kill mutates first — if the event write then fails, say so at ERROR level."""
    import logging

    client, manager = _review_client(monkeypatch, tmp_path)
    manager.event_log.append = lambda event: (_ for _ in ()).throw(OSError("disk full"))

    with caplog.at_level(logging.ERROR):
        r = client.post(
            "/api/memory/review", json={"memory_id": "m1", "verdict": "kill", "editor": "ui"}
        )

    assert r.status_code == 200  # the mutation stands
    assert r.json()["event_recorded"] is False
    assert "memory_reviewed event write FAILED" in caplog.text
