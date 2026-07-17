"""T3 — POST /api/memory/resparse contract + the exclusive maintenance barrier."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

import httpx
import pytest
from starlette.testclient import TestClient
from tests.test_resparse import QUERY, _build_manager, _seed


def _client(monkeypatch) -> TestClient:
    import server

    monkeypatch.setattr("memory.singleton._instance", MagicMock())
    return TestClient(server.build_app())


def test_resparse_route_returns_transaction_result(monkeypatch):
    result = {"points_updated": 5, "vocab_size": 42, "oov_identifier_reset": True}
    monkeypatch.setattr("memory.resparse.resparse", lambda manager: result)

    response = _client(monkeypatch).post("/api/memory/resparse")

    assert response.status_code == 200
    assert response.json() == result


def test_resparse_route_maps_failures_to_500_with_remediation(monkeypatch):
    from memory.resparse import ResparsePreflightError

    def refuse(manager):
        raise ResparsePreflightError("no 'bm25' sparse field — run a full reindex")

    monkeypatch.setattr("memory.resparse.resparse", refuse)

    response = _client(monkeypatch).post("/api/memory/resparse")

    assert response.status_code == 500
    assert "reindex" in response.json()["error"]


def test_resparse_route_rejects_browser_marked_cross_origin(monkeypatch):
    response = _client(monkeypatch).post(
        "/api/memory/resparse",
        content="x=1",
        headers={"Origin": "http://localhost:9999", "Content-Type": "text/plain"},
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_save_during_resparse_queues_and_lands_with_new_vocab(tmp_path, monkeypatch):
    import server
    from core.utils import stable_hash_id
    from memory import resparse as resparse_mod

    manager = _build_manager(tmp_path)
    _seed(manager)
    monkeypatch.setattr("memory.singleton._instance", manager)

    started, release = threading.Event(), threading.Event()
    real_resparse = resparse_mod.resparse

    def slow_resparse(mgr, **kwargs):
        started.set()
        assert release.wait(timeout=10)
        return real_resparse(mgr, **kwargs)

    monkeypatch.setattr("memory.resparse.resparse", slow_resparse)

    transport = httpx.ASGITransport(app=server.build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resparse_task = asyncio.create_task(client.post("/api/memory/resparse"))
        assert await asyncio.to_thread(started.wait, 5)

        save_task = asyncio.create_task(
            client.post(
                "/api/memory/save",
                json={
                    "content": "follow-up on i-03470c789e7b72080 remediation completed",
                    "project": "proj",
                },
            )
        )
        await asyncio.sleep(0.3)
        assert not save_task.done()  # queued behind the barrier

        release.set()
        resparse_response = await resparse_task
        save_response = await save_task

    assert resparse_response.status_code == 200
    # 5 seeded points only: the save never snuck into the transaction window.
    assert resparse_response.json()["points_updated"] == 5
    assert save_response.status_code == 200

    memory_id = save_response.json()["memory_id"]
    point = manager.store.client.retrieve(
        collection_name=manager.store.collection,
        ids=[stable_hash_id(memory_id)],
        with_payload=True,
        with_vectors=True,
    )[0]
    sparse = point.vector["bm25"]
    got = dict(zip(sparse.indices, sparse.values, strict=True))
    expected = manager.store.sparse_encoder.encode_document(point.payload["embedding_text"])
    assert got == pytest.approx(expected)  # the queued save used the NEW vocab
    assert manager.store.sparse_encoder.vocab[QUERY] in got


async def test_observe_route_waits_for_the_maintenance_barrier(monkeypatch):
    import server

    manager = MagicMock()
    manager.save.return_value = "2026-07-17_note_abcd1234"
    monkeypatch.setattr("memory.singleton._instance", manager)

    transport = httpx.ASGITransport(app=server.build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with server._maintenance_barrier():
            task = asyncio.create_task(
                client.post("/api/memory/observe", json={"summary": "queued", "type": "note"})
            )
            await asyncio.sleep(0.2)
            assert not task.done()  # queued while the barrier is held
        response = await task

    assert response.status_code == 200
    assert response.json()["memory_id"] == "2026-07-17_note_abcd1234"
