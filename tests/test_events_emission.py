"""Tests for manager.record_event — memory_ids in payload, never raises."""

import json


def test_record_event_appends_memory_ids_in_payload(tmp_path):
    from memory.events import EventLog
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._event_log = EventLog(tmp_path / "_events.jsonl")

    manager.record_event(
        event_type="memory_recalled",
        project="my-proj",
        memory_ids=["id-a", "id-b"],
        source="recall",
    )

    lines = (tmp_path / "_events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["event_type"] == "memory_recalled"
    assert saved["project"] == "my-proj"
    assert saved["source"] == "recall"
    assert saved["payload"]["memory_ids"] == ["id-a", "id-b"]


def test_record_event_swallows_event_log_exception(tmp_path, monkeypatch):
    from memory.events import EventLog
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    broken_log = EventLog(tmp_path / "_events.jsonl")

    def raise_on_append(event):
        raise OSError("disk full")

    monkeypatch.setattr(broken_log, "append", raise_on_append)
    manager._event_log = broken_log

    # Must not raise
    manager.record_event(
        event_type="memory_recalled",
        project="my-proj",
        memory_ids=["id-x"],
        source="recall",
    )
