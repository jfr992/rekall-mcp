"""Contract tests for the idempotent AFK memory operation endpoint."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier, BrokenBarrierError, Lock
from unittest.mock import MagicMock, patch

import pytest
import yaml
from starlette.testclient import TestClient


@pytest.fixture
def afk_manager(tmp_path):
    from memory.manager import MemoryManager

    with (
        patch("memory.manager.VectorStore") as vector_store,
        patch("memory.manager.Embedder") as embedder,
    ):
        vector_store.return_value.count.return_value = 0
        embedder.return_value.encode.return_value = [0.1] * 384
        embedder.return_value.dimensions = 384
        manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_url="http://test")
    manager._store = vector_store.return_value
    manager._embedder = embedder.return_value
    manager._knowledge_graph = MagicMock()
    manager._event_log = MagicMock()
    manager._event_log.tail.return_value = []
    manager.store.get_by_id.return_value = None
    return manager


def _save(manager, **overrides):
    request = {
        "operation_id": "attack:receipt-1",
        "operation_date": "2026-08-24",
        "content": "token=supersecret",
        "tag": "attack",
        "proposed": "Keep signed evidence",
        "type": "note",
        "project": "afk-project",
    }
    request.update(overrides)
    return manager.save_afk_operation(**request)


def _entries(manager, project="afk-project", date="2026-08-24"):
    with (manager.memory_dir / project / f"{date}.yaml").open() as source:
        document = yaml.safe_load(source)
    return [entry for value in document.values() if isinstance(value, list) for entry in value]


def test_afk_save_sanitizes_then_signs_and_uses_contract_id(afk_manager):
    result = _save(afk_manager)

    expected_hash = sha256(b"afk-project\x00attack:receipt-1").hexdigest()
    assert result["memory_id"] == f"2026-08-24_note_{expected_hash}"
    assert result["canonical_content"] == "[REDACTED]"
    assert result["sanitized"] is True
    assert result["envelope"]["canonical_content"] == "[REDACTED]"
    assert (
        "supersecret"
        not in (afk_manager.memory_dir / "afk-project" / "2026-08-24.yaml").read_text()
    )
    assert _entries(afk_manager)[0]["afk_operation"]["response"] == result


def test_same_operation_is_idempotent_but_changed_normalized_input_conflicts(afk_manager):
    first = _save(afk_manager)
    assert _save(afk_manager) == first
    assert len(_entries(afk_manager)) == 1
    assert afk_manager.store.save.call_count == 1

    from memory.manager import AfkOperationConflict

    with pytest.raises(AfkOperationConflict):
        _save(afk_manager, proposed="Different durable claim")
    assert len(_entries(afk_manager)) == 1


def test_afk_signs_scrubbed_tag_and_proposed_with_normalized_conflicts(afk_manager):
    first = _save(
        afk_manager,
        tag="token=first-secret",
        proposed="Bearer first-secret is evidence",
    )
    retry = _save(
        afk_manager,
        tag="token=second-secret",
        proposed="Bearer second-secret is evidence",
    )

    assert retry == first
    assert first["envelope"]["tag"] == "[REDACTED]"
    assert first["envelope"]["proposed"] == "[REDACTED] is evidence"
    stored = (afk_manager.memory_dir / "afk-project" / "2026-08-24.yaml").read_text()
    assert "first-secret" not in stored
    assert "second-secret" not in stored


def test_distinct_operations_keep_same_content_and_isolate_project_and_date(afk_manager):
    first = _save(afk_manager)
    second = _save(afk_manager, operation_id="attack:receipt-2")
    other_project = _save(afk_manager, project="other-project")
    other_date = _save(afk_manager, operation_date="2026-08-25")

    assert (
        len(
            {
                first["memory_id"],
                second["memory_id"],
                other_project["memory_id"],
                other_date["memory_id"],
            }
        )
        == 4
    )
    assert len(_entries(afk_manager)) == 2
    assert afk_manager.get_afk_operation("attack:receipt-1", "afk-project", "2026-08-24") == first
    assert (
        afk_manager.get_afk_operation("attack:receipt-1", "other-project", "2026-08-24")
        == other_project
    )
    assert (
        afk_manager.get_afk_operation("attack:receipt-1", "afk-project", "2026-08-25") == other_date
    )


def test_retry_repairs_vector_after_crash_following_yaml_durability(afk_manager):
    afk_manager.store.save.side_effect = [RuntimeError("vector unavailable"), None]

    with pytest.raises(RuntimeError, match="vector unavailable"):
        _save(afk_manager)
    assert len(_entries(afk_manager)) == 1

    recovered = _save(afk_manager)
    assert recovered["memory_id"].startswith("2026-08-24_note_")
    assert len(_entries(afk_manager)) == 1
    assert afk_manager.store.save.call_count == 2


def test_upsert_then_raise_is_reconciled_without_a_second_vector_write(afk_manager):
    vector_reads = 0

    def get_by_id(_memory_id):
        nonlocal vector_reads
        vector_reads += 1
        return None if vector_reads == 1 else _entries(afk_manager)[0]

    afk_manager.store.get_by_id.side_effect = get_by_id
    afk_manager.store.save.side_effect = RuntimeError("response lost after upsert")

    first = _save(afk_manager)
    retry = _save(afk_manager)

    assert retry == first
    assert afk_manager.store.save.call_count == 1
    assert _entries(afk_manager)[0]["afk_operation"]["vector_state"] == "completed"


def test_stock_delete_removes_afk_memory(afk_manager):
    result = _save(afk_manager)
    afk_manager.store.client.delete = MagicMock()

    assert afk_manager.delete(result["memory_id"]) is True
    assert not (afk_manager.memory_dir / "afk-project" / "2026-08-24.yaml").exists()


def test_afk_and_ordinary_concurrent_writers_do_not_lose_accepted_records(afk_manager):
    def save_afk(index):
        return _save(afk_manager, operation_id=f"attack:concurrent-{index}")

    def save_ordinary(index):
        return afk_manager.save(f"ordinary content {index}", type="note", project="afk-project")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(save_afk, i) for i in range(4)]
        futures += [pool.submit(save_ordinary, i) for i in range(4)]
        [future.result() for future in futures]

    assert len(_entries(afk_manager)) == 8


def test_concurrent_identical_ordinary_saves_revalidate_deduplication_under_lock(afk_manager):
    search_barrier = Barrier(2)
    saved: dict[str, dict] = {}
    saved_lock = Lock()

    def search(**_kwargs):
        try:
            search_barrier.wait(timeout=0.1)
        except BrokenBarrierError:
            pass
        with saved_lock:
            return list(saved.values())

    def save(*, id, payload, **_kwargs):
        with saved_lock:
            saved[id] = {"memory_id": id, "content": payload["content"]}

    afk_manager.store.search.side_effect = search
    afk_manager.store.save.side_effect = save

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                lambda _: afk_manager.save(
                    "identical ordinary memory", type="note", project="afk-project"
                ),
                range(2),
            )
        )

    assert ids[0] == ids[1]
    assert len(_entries(afk_manager)) == 1


@pytest.fixture
def client_and_manager(monkeypatch):
    manager = MagicMock()
    manager.save_afk_operation.return_value = {
        "memory_id": "2026-08-24_note_hash",
        "envelope": {"digest": "digest"},
        "canonical_content": "safe",
        "sanitized": True,
    }
    manager.get_afk_operation.return_value = manager.save_afk_operation.return_value
    monkeypatch.setattr("memory.singleton._instance", manager)
    from server import mcp

    return TestClient(mcp.streamable_http_app()), manager


def test_afk_rest_contract_parses_strictly_and_exposes_lookup(client_and_manager):
    client, manager = client_and_manager
    body = {
        "operation_id": "attack:1",
        "operation_date": "2026-08-24",
        "content": "safe",
        "tag": "attack",
        "proposed": "claim",
        "type": "note",
        "project": "afk-project",
    }
    response = client.post("/api/memory/afk/save", json=body)
    assert response.status_code == 200
    assert response.json()["memory_id"] == "2026-08-24_note_hash"
    assert manager.save_afk_operation.call_args.kwargs == body

    lookup = client.get(
        "/api/memory/afk/operations/attack:1",
        params={"project": "afk-project", "operation_date": "2026-08-24"},
    )
    assert lookup.status_code == 200
    assert manager.get_afk_operation.call_args.args == ("attack:1", "afk-project", "2026-08-24")

    invalid = client.post("/api/memory/afk/save", json={**body, "extra": "rejected"})
    assert invalid.status_code == 400


def test_afk_lookup_returns_404_when_operation_is_absent(client_and_manager):
    client, manager = client_and_manager
    manager.get_afk_operation.return_value = None

    response = client.get(
        "/api/memory/afk/operations/missing",
        params={"project": "afk-project", "operation_date": "2026-08-24"},
    )
    assert response.status_code == 404


def test_afk_lookup_rejects_impossible_dates(client_and_manager):
    client, _ = client_and_manager

    response = client.get(
        "/api/memory/afk/operations/attack:1",
        params={"project": "afk-project", "operation_date": "2026-13-41"},
    )

    assert response.status_code == 400
