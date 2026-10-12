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


def test_ui_source_recall_emits_no_memory_recalled_event():
    from memory.manager import MemoryManager
    from test_event_contract import HITS, _mgr

    mgr = _mgr(HITS)
    MemoryManager.recall(mgr, "q", source="ui")
    mgr.record_event.assert_not_called()

    MemoryManager.recall(mgr, "q")
    assert mgr.record_event.call_args.kwargs["event_type"] == "memory_recalled"


def test_ui_source_recall_does_not_bump_graph_access():
    from memory.manager import MemoryManager
    from test_event_contract import HITS, _mgr

    mgr = _mgr(HITS)
    mgr._knowledge_graph.stats.return_value = {"nodes": 3, "edges": 2}
    mgr._knowledge_graph.get_neighbors.return_value = set()
    mgr._knowledge_graph.get_importance.return_value = 0.5

    MemoryManager.recall(mgr, "q", source="ui")
    mgr._knowledge_graph.record_access.assert_not_called()

    MemoryManager.recall(mgr, "q")
    mgr._knowledge_graph.record_access.assert_called()
