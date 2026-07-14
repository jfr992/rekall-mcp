"""EventLog.read_from cursor pagination + GET /api/memory/events (U1 Task 4).

Cursor is opaque: {offset, sig} where sig = sha256(first_line)[:12] + ":" + size_at_issue.
Advances only past newline-terminated lines; sig mismatch/shrink → fresh tail + truncated.
"""

from memory.events import EventLog, MemoryEvent


def _event(i: int, project: str = "p") -> MemoryEvent:
    return MemoryEvent(
        event_type="memory_recalled",
        project=project,
        agent="claude-code",
        source="test",
        payload={"index": i},
    )


def _log(tmp_path) -> EventLog:
    return EventLog(tmp_path / "_events.jsonl")


def test_read_from_none_returns_tail_and_cursor(tmp_path):
    log = _log(tmp_path)
    for i in range(5):
        log.append(_event(i))

    events, cursor, truncated = log.read_from(None, limit=3)

    assert [e.payload["index"] for e in events] == [2, 3, 4]
    assert isinstance(cursor, str) and cursor
    assert truncated is False


def test_read_from_cursor_returns_only_new_events(tmp_path):
    log = _log(tmp_path)
    for i in range(3):
        log.append(_event(i))
    _, cursor, _ = log.read_from(None, limit=10)

    log.append(_event(3))
    log.append(_event(4))
    events, cursor2, truncated = log.read_from(cursor, limit=10)

    assert [e.payload["index"] for e in events] == [3, 4]
    assert truncated is False

    # nothing new → empty, no truncation
    events, _, truncated = log.read_from(cursor2, limit=10)
    assert events == []
    assert truncated is False


def test_read_from_does_not_advance_past_partial_line(tmp_path):
    """A concurrent append caught mid-write must not be consumed or skipped."""
    log = _log(tmp_path)
    log.append(_event(0))
    _, cursor, _ = log.read_from(None, limit=10)

    log.append(_event(1))
    full_line = (tmp_path / "_events.jsonl").read_text().splitlines()[-1]
    half = full_line[: len(full_line) // 2]
    with (tmp_path / "_events.jsonl").open("a") as f:
        f.write(half)  # no trailing newline — writer still in flight

    events, cursor2, truncated = log.read_from(cursor, limit=10)
    assert [e.payload["index"] for e in events] == [1]
    assert truncated is False

    # writer finishes the line — the same cursor picks it up intact
    with (tmp_path / "_events.jsonl").open("a") as f:
        f.write(full_line[len(full_line) // 2 :] + "\n")
    events, _, truncated = log.read_from(cursor2, limit=10)
    assert [e.payload["index"] for e in events] == [1]
    assert truncated is False


def test_read_from_detects_rewrite_returns_fresh_tail(tmp_path):
    """Restore/rewrite invalidates the sig → truncated=True + usable reset cursor."""
    log = _log(tmp_path)
    for i in range(3):
        log.append(_event(i))
    _, cursor, _ = log.read_from(None, limit=10)

    (tmp_path / "_events.jsonl").unlink()  # tarball restore rewrites the log
    for i in range(10, 14):
        log.append(_event(i))

    events, cursor2, truncated = log.read_from(cursor, limit=2)
    assert truncated is True
    assert [e.payload["index"] for e in events] == [12, 13]  # fresh bounded tail

    log.append(_event(14))
    events, _, truncated = log.read_from(cursor2, limit=10)
    assert [e.payload["index"] for e in events] == [14]
    assert truncated is False


def test_read_from_detects_shrunken_file(tmp_path):
    """Same first line but file shrank below size-at-issue → rewrite, not garbage."""
    log = _log(tmp_path)
    for i in range(4):
        log.append(_event(i))
    _, cursor, _ = log.read_from(None, limit=10)

    lines = (tmp_path / "_events.jsonl").read_text().splitlines(keepends=True)
    (tmp_path / "_events.jsonl").write_text("".join(lines[:2]))  # first line intact

    events, _, truncated = log.read_from(cursor, limit=10)
    assert truncated is True
    assert [e.payload["index"] for e in events] == [0, 1]


def test_read_from_is_o_new_bytes_at_10k_events(tmp_path, monkeypatch):
    """Cursor reads must not reparse the file — 43MB/min/tab at 10k events killed rev 1."""
    from pathlib import Path

    log = _log(tmp_path)
    with (tmp_path / "_events.jsonl").open("a") as f:
        for i in range(10_000):
            f.write(
                '{"agent": "a", "event_id": "%08d", "event_type": "memory_recalled", '
                '"observed_at": "2026-07-14T00:00:00", "payload": {"index": %d}, '
                '"project": "p", "source": "test"}\n' % (i, i)
            )
    _, cursor, _ = log.read_from(None, limit=10)

    size_at_cursor = (tmp_path / "_events.jsonl").stat().st_size
    for i in range(10_000, 10_005):
        log.append(_event(i))
    new_bytes = (tmp_path / "_events.jsonl").stat().st_size - size_at_cursor

    counted = {"bytes": 0}
    real_open, real_read_bytes = Path.open, Path.read_bytes

    class CountingFile:
        def __init__(self, fh):
            self._fh = fh

        def read(self, *a):
            data = self._fh.read(*a)
            counted["bytes"] += len(data)
            return data

        def readline(self, *a):
            data = self._fh.readline(*a)
            counted["bytes"] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._fh.__exit__(*a)

    def counting_open(self, *a, **kw):
        fh = real_open(self, *a, **kw)
        return CountingFile(fh) if self.name == "_events.jsonl" else fh

    def counting_read_bytes(self):
        data = real_read_bytes(self)
        counted["bytes"] += len(data)
        return data

    monkeypatch.setattr(Path, "open", counting_open)
    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

    events, _, truncated = log.read_from(cursor, limit=100)

    assert [e.payload["index"] for e in events] == list(range(10_000, 10_005))
    assert truncated is False
    total = (tmp_path / "_events.jsonl").stat().st_size
    assert counted["bytes"] <= new_bytes + 1024, (
        f"read {counted['bytes']}B for {new_bytes}B of new events (file is {total}B)"
    )


def _rest_client(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.event_log = _log(tmp_path)
    manager.memory_dir = tmp_path
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app())


def test_get_events_returns_events_cursor_truncated(monkeypatch, tmp_path):
    client = _rest_client(monkeypatch, tmp_path)
    log = _log(tmp_path)
    for i in range(3):
        log.append(_event(i))

    r = client.get("/api/memory/events", params={"limit": 2})

    assert r.status_code == 200
    body = r.json()
    assert [e["payload"]["index"] for e in body["events"]] == [1, 2]
    assert isinstance(body["cursor"], str) and body["cursor"]
    assert body["truncated"] is False
