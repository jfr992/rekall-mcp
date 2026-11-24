"""manager.retag_memory updates YAML, vector payload, and graph together."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import yaml

from memory.manager import MemoryManager

MEMORY_ID = "2026-07-01_decision_abc12345"


def _mgr(tmp_path, payload):
    mgr = object.__new__(MemoryManager)
    mgr.memory_dir = tmp_path
    mgr._store = MagicMock()
    mgr._store.get_many.return_value = [dict(payload)] if payload else []
    mgr._store.get_by_id.return_value = dict(payload) if payload else None
    mgr._embedder = MagicMock()
    mgr._embedder.encode.return_value = [0.1] * 384
    mgr._knowledge_graph = MagicMock()
    mgr.record_event = MagicMock()
    mgr._assert_reindex_complete = lambda: None

    @contextmanager
    def _noop_track(_name):
        yield

    telemetry = MagicMock()
    telemetry.track.side_effect = _noop_track
    mgr._telemetry = telemetry
    return mgr


def _seed_yaml(tmp_path, project="my-app", type_key="decisions"):
    project_dir = tmp_path / project
    project_dir.mkdir(parents=True, exist_ok=True)
    yaml_file = project_dir / "2026-07-01.yaml"
    yaml_file.write_text(
        yaml.safe_dump(
            {
                "date": "2026-07-01",
                type_key: [
                    {
                        "id": MEMORY_ID,
                        "content": "rotate auth keys quarterly",
                        "project": project,
                        "timestamp": "2026-07-01T10:00:00",
                    }
                ],
            }
        )
    )
    return yaml_file


def _payload(project="my-app", typ="decision"):
    return {
        "memory_id": MEMORY_ID,
        "content": "rotate auth keys quarterly",
        "type": typ,
        "project": project,
        "date": "2026-07-01",
        "timestamp": "2026-07-01T10:00:00",
    }


def test_retag_project_moves_yaml_and_updates_store_and_graph(tmp_path):
    old_yaml = _seed_yaml(tmp_path, project="my-app")
    mgr = _mgr(tmp_path, _payload())

    result = mgr.retag_memory(MEMORY_ID, project="veril-clips")

    assert result["project"] == "veril-clips"
    assert result["memory_id"] == MEMORY_ID
    assert not old_yaml.exists() or "abc12345" not in old_yaml.read_text()
    new_yaml = tmp_path / "veril-clips" / "2026-07-01.yaml"
    data = yaml.safe_load(new_yaml.read_text())
    entry = data["decisions"][0]
    assert entry["id"] == MEMORY_ID
    assert entry["project"] == "veril-clips"
    mgr._store.update_payload.assert_called()
    updated = mgr._store.update_payload.call_args.args[1]
    assert updated["project"] == "veril-clips"
    mgr._knowledge_graph.add_node.assert_called()
    args, kwargs = mgr._knowledge_graph.add_node.call_args
    assert args[0] == MEMORY_ID
    assert kwargs.get("topic") == "veril-clips"
    assert mgr._knowledge_graph.save.called


def test_retag_memory_type_moves_yaml_section(tmp_path):
    old_yaml = _seed_yaml(tmp_path)
    mgr = _mgr(tmp_path, _payload())

    result = mgr.retag_memory(MEMORY_ID, memory_type="fact")

    assert result["type"] == "fact"
    data = yaml.safe_load(old_yaml.read_text())
    assert not data.get("decisions")
    assert data["facts"][0]["id"] == MEMORY_ID
    updated = mgr._store.update_payload.call_args.args[1]
    assert updated["type"] == "fact"


def test_retag_unknown_memory_returns_none(tmp_path):
    mgr = _mgr(tmp_path, None)
    assert mgr.retag_memory("2026-07-01_decision_missing", project="x") is None


def test_retag_rejects_invalid_memory_type(tmp_path):
    _seed_yaml(tmp_path)
    mgr = _mgr(tmp_path, _payload())
    try:
        mgr.retag_memory(MEMORY_ID, memory_type="project")
    except ValueError as exc:
        assert "type" in str(exc).lower() or "project" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError for invalid memory type")
    mgr._store.update_payload.assert_not_called()
