"""update_memory_content: append-only mutate, id-stable, real re-embed (spec 2026-07-08)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import yaml

from memory.manager import MemoryManager

MEMORY_ID = "2026-07-01_decision_abc12345"


def _mgr(tmp_path, payload):
    mgr = object.__new__(MemoryManager)
    mgr.memory_dir = tmp_path
    mgr._store = MagicMock()
    mgr._store.get_many.return_value = [payload] if payload else []
    mgr._embedder = MagicMock()
    mgr._embedder.encode.return_value = [0.1] * 384
    mgr._knowledge_graph = MagicMock()
    mgr.record_event = MagicMock()

    @contextmanager
    def _noop_track(_name):
        yield

    telemetry = MagicMock()
    telemetry.track.side_effect = _noop_track
    mgr._telemetry = telemetry
    return mgr


def _seed_yaml(tmp_path):
    project_dir = tmp_path / "my-app"
    project_dir.mkdir(parents=True)
    yaml_file = project_dir / "2026-07-01.yaml"
    yaml_file.write_text(
        yaml.safe_dump(
            {
                "date": "2026-07-01",
                "decisions": [
                    {
                        "id": MEMORY_ID,
                        "content": "rotate auth keys quarterly",
                        "project": "my-app",
                        "timestamp": "2026-07-01T10:00:00",
                    }
                ],
            }
        )
    )
    return yaml_file


def _payload():
    return {
        "memory_id": MEMORY_ID,
        "content": "rotate auth keys quarterly",
        "type": "decision",
        "project": "my-app",
        "date": "2026-07-01",
        "timestamp": "2026-07-01T10:00:00",
    }


def test_update_appends_content_mutates_yaml_and_reembeds(tmp_path):
    yaml_file = _seed_yaml(tmp_path)
    mgr = _mgr(tmp_path, _payload())

    result = mgr.update_memory_content(MEMORY_ID, "RESOLVED 2026-07-09")

    assert result["memory_id"] == MEMORY_ID
    data = yaml.safe_load(yaml_file.read_text())
    entry = data["decisions"][0]
    assert entry["id"] == MEMORY_ID
    assert "RESOLVED 2026-07-09" in entry["content"]

    save_kwargs = mgr._store.save.call_args.kwargs
    assert save_kwargs["id"] == MEMORY_ID
    assert save_kwargs["vector"] == [0.1] * 384
    assert "RESOLVED 2026-07-09" in save_kwargs["payload"]["content"]
    encoded_text = mgr._embedder.encode.call_args.args[0]
    assert "RESOLVED 2026-07-09" in encoded_text


def test_update_reencodes_raw_content_not_embedding_text(tmp_path):
    """Repr v2: the dense vector re-encodes the raw new content; embedding_text
    is still rebuilt for the payload and the BM25 sparse leg."""
    _seed_yaml(tmp_path)
    mgr = _mgr(tmp_path, _payload())

    mgr.update_memory_content(MEMORY_ID, "RESOLVED 2026-07-09")

    save_kwargs = mgr._store.save.call_args.kwargs
    encoded_text = mgr._embedder.encode.call_args.args[0]
    assert encoded_text == save_kwargs["payload"]["content"]
    assert save_kwargs["payload"]["embedding_text"].startswith("Project my-app.")
    assert save_kwargs["content"] == save_kwargs["payload"]["embedding_text"]
    assert save_kwargs["payload"]["repr_version"] == 2


@pytest.mark.integration
def test_update_reencodes_vector_in_qdrant(memory_manager):
    """The Qdrant point's dense vector must actually change on update —
    set_payload would leave it stale (the red-team trap this pins)."""
    mgr = memory_manager
    memory_id = mgr.save(
        "Open loop: rotate auth keys before Q3 audit",
        type="decision",
        project="test-project",
    )
    before = mgr.store.get_many([memory_id], with_vectors=True)[0]["_vector"]

    mgr.update_memory_content(memory_id, "RESOLVED 2026-07-09: rotation done")

    after_payloads = mgr.store.get_many([memory_id], with_vectors=True)
    assert len(after_payloads) == 1, "id must be stable — same point, not a new one"
    after = after_payloads[0]
    assert "RESOLVED 2026-07-09" in after["content"]
    assert after["_vector"] != before


def test_update_sanitizes_appended_text(tmp_path):
    """close_loop notes are free agent text — credentials must not persist
    (same invariant save() enforces; adversarial review finding)."""
    _seed_yaml(tmp_path)
    mgr = _mgr(tmp_path, _payload())

    token = "ghp_" + "a" * 36
    result = mgr.update_memory_content(MEMORY_ID, f"RESOLVED 2026-07-09: rotated {token}")

    assert token not in result["content"]
    save_kwargs = mgr._store.save.call_args.kwargs
    assert token not in save_kwargs["payload"]["content"]


def test_update_unknown_id_raises(tmp_path):
    mgr = _mgr(tmp_path, None)
    try:
        mgr.update_memory_content("2099-01-01_fact_deadbeef", "RESOLVED")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not found" in str(e)
    mgr._store.save.assert_not_called()


def test_update_emits_memory_updated_event(tmp_path):
    _seed_yaml(tmp_path)
    mgr = _mgr(tmp_path, _payload())

    mgr.update_memory_content(MEMORY_ID, "RESOLVED 2026-07-14")

    mgr.record_event.assert_called_once()
    kwargs = mgr.record_event.call_args.kwargs
    assert kwargs["event_type"] == "memory_updated"
    assert kwargs["project"] == "my-app"
    assert kwargs["memory_ids"] == [MEMORY_ID]
    assert kwargs["payload"]["memory_id"] == MEMORY_ID
