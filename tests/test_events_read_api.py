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
