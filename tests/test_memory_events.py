import json


def test_event_log_appends_jsonl(tmp_path):
    from memory.events import EventLog, MemoryEvent

    log = EventLog(tmp_path / "_events.jsonl")
    event = MemoryEvent(
        event_type="memory_saved",
        project="byte-edge",
        agent="claude-code",
        source="stop_hook",
        payload={"memory_id": "2026-07-03_learning_abcd1234"},
    )

    log.append(event)

    lines = (tmp_path / "_events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["event_type"] == "memory_saved"
    assert saved["project"] == "byte-edge"
    assert saved["agent"] == "claude-code"
    assert saved["payload"]["memory_id"] == "2026-07-03_learning_abcd1234"
    assert saved["event_id"]
    assert saved["observed_at"]


def test_event_log_tail_returns_recent_events(tmp_path):
    from memory.events import EventLog, MemoryEvent

    log = EventLog(tmp_path / "_events.jsonl")
    for index in range(5):
        log.append(
            MemoryEvent(
                event_type="tool_result",
                project="rekall-mcp",
                agent="claude-code",
                source="post_tool",
                payload={"index": index},
            )
        )

    recent = log.tail(limit=2)

    assert [event.payload["index"] for event in recent] == [3, 4]


def test_manager_records_memory_saved_event(tmp_path, monkeypatch):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._store = type(
        "Store",
        (),
        {
            "search": lambda *args, **kwargs: [],
            "save": lambda *args, **kwargs: None,
        },
    )()
    manager._embedder = type("Embedder", (), {"encode": lambda self, text: [0.1] * 384})()
    manager._knowledge_graph = type(
        "Graph",
        (),
        {
            "add_node": lambda *args, **kwargs: None,
            "save": lambda *args, **kwargs: None,
        },
    )()
    monkeypatch.setattr(
        "memory.manager.auto_link",
        lambda **kwargs: type("R", (), {"edges_created": 0, "relations": {}})(),
    )

    memory_id = manager.save("Use capsules for startup", type="decision", project="rekall-mcp")

    assert memory_id.startswith("2026-")
    events = manager.event_log.tail(limit=1)
    assert events[0].event_type == "memory_saved"
    assert events[0].payload["memory_id"] == memory_id
