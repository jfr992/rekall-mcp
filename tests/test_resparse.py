"""T3 — transactional resparse: preflight -> sentinel -> rewrite -> verify -> publish."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.conftest import TEST_QDRANT_URL

from core import BM25Encoder
from memory import MemoryManager
from memory.scope import MemoryScope

pytestmark = pytest.mark.integration

QUERY = "i-03470c789e7b72080"
TARGET_CONTENT = "Instance i-03470c789e7b72080 hit EdgeHostDeviceAlreadyInUse on the edge host"
FILLER_CONTENTS = [
    f"filler note number {i} about the deployment pipeline rollout" for i in range(4)
]
INITIAL_CORPUS = [
    "filler note deployment pipeline rollout postgres",
    "docker compose deployment pipeline notes",
    "jwt validation bug fixed in auth middleware",
    "terraform module for the vpc network stack",
]
SCOPE = MemoryScope(agent="test", project="proj")


class RoutedEmbedder:
    """Deterministic dense router: fillers near the query, the target orthogonal.

    Dense search can never surface the target for QUERY — only the sparse leg
    can, which is exactly what resparse must repair.
    """

    dimensions = 384

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * 384
        if text.strip() == QUERY:
            for i in range(4):
                vector[i] = 0.5
        elif "filler note number" in text:
            index = int(text.split("filler note number ")[1].split()[0])
            vector[index % 4] = 1.0
        else:
            vector[100 + (hash(text) % 200)] = 1.0
        return vector


def _install_vocab(manager: MemoryManager, corpus: list[str] = INITIAL_CORPUS) -> None:
    encoder = BM25Encoder()
    encoder.fit(corpus)
    encoder.save(str(manager._bm25_path))


def _build_manager(tmp_path: Path, *, with_vocab: bool = True) -> MemoryManager:
    if os.environ.get("REKALL_TEST_LANE") == "embedded":
        manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"))
    else:
        manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_url=TEST_QDRANT_URL)
    manager._embedder = RoutedEmbedder()
    if with_vocab:
        _install_vocab(manager)
    # sparse_encoder resolves BEFORE the store connects, so the collection is
    # (re)created with the matching schema: sparse when a vocab is installed.
    manager.store.recreate_collection()
    return manager


def _seed(manager: MemoryManager) -> str:
    for content in FILLER_CONTENTS:
        manager.save(content, type="note", scope=SCOPE)
    return manager.save(TARGET_CONTENT, type="note", scope=SCOPE)


def test_resparse_refuses_when_collection_has_no_sparse_schema(tmp_path):
    from memory.resparse import ResparsePreflightError, resparse

    manager = _build_manager(tmp_path, with_vocab=False)
    manager.save("dense only memory about deployments", type="note", scope=SCOPE)
    _install_vocab(manager)  # vocab appears later; the collection is still dense-only

    with pytest.raises(ResparsePreflightError, match="reindex"):
        resparse(manager)

    assert not manager.resparse_sentinel.exists()
    assert manager.store.count() == 1  # nothing mutated


def test_resparse_refuses_on_orphan_qdrant_points_before_mutation(tmp_path):
    from memory.resparse import ResparsePreflightError, resparse

    manager = _build_manager(tmp_path)
    _seed(manager)
    manager.store.save(
        id="2020-01-01_note_dead0000",
        vector=manager.embedder.encode("orphan point with no yaml source"),
        payload={"memory_id": "2020-01-01_note_dead0000", "content": "orphan"},
        content="orphan point with no yaml source",
    )

    with pytest.raises(ResparsePreflightError, match="1 "):
        resparse(manager)

    assert not manager.resparse_sentinel.exists()


def _identifier_hits(manager: MemoryManager) -> list[str]:
    results = manager.store.search(vector=manager.embedder.encode(QUERY), query_text=QUERY, limit=3)
    return [r["memory_id"] for r in results]


def test_resparse_happy_path_repairs_identifier_recall(tmp_path):
    from memory.resparse import resparse

    manager = _build_manager(tmp_path)
    target_id = _seed(manager)

    # Stale vocab: the identifier is OOV on both query and point side — miss.
    assert target_id not in _identifier_hits(manager)

    result = resparse(manager)

    assert result["points_updated"] == 5 == manager.store.count()
    assert result["vocab_size"] > 0
    assert result["oov_identifier_reset"] is True
    assert target_id in _identifier_hits(manager)

    binding = json.loads(manager._bm25_path.read_text())["_binding"]
    assert binding["target"] == str(manager._qdrant_path or manager._qdrant_url)
    assert binding["collection"] == manager.COLLECTION

    drift = json.loads(manager._bm25_path.with_name("_bm25_drift.json").read_text())
    assert drift["window"] == []
    assert drift["saves_since_fit"] == 0
    assert drift["oov_identifier_seen"] is False
    assert not manager.resparse_sentinel.exists()


def test_interrupted_resparse_holds_sentinel_and_rerun_recovers(tmp_path):
    from memory.resparse import ResparseAbortedError, resparse

    manager = _build_manager(tmp_path)
    target_id = _seed(manager)

    real_update = manager.store.client.update_vectors
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:  # second batch fails, and so does its one retry
            raise RuntimeError("simulated qdrant outage")
        return real_update(*args, **kwargs)

    manager.store.client.update_vectors = flaky
    try:
        with pytest.raises(ResparseAbortedError, match="rerun"):
            resparse(manager, batch_size=2)
    finally:
        manager.store.client.update_vectors = real_update

    assert manager.resparse_sentinel.exists()
    assert manager.sparse_encoder is None  # dense-only while incomplete
    assert manager.doctor()["bm25"]["verdict"] == "resparse_incomplete"

    result = resparse(manager, batch_size=2)

    assert result["points_updated"] == 5
    assert not manager.resparse_sentinel.exists()
    assert manager.sparse_encoder is not None
    assert manager.doctor()["bm25"]["verdict"] != "resparse_incomplete"
    assert target_id in _identifier_hits(manager)


def test_resparse_swaps_both_encoder_refs_and_new_saves_use_new_vocab(tmp_path):
    from core.utils import stable_hash_id
    from memory.resparse import resparse

    manager = _build_manager(tmp_path)
    _seed(manager)
    manager._sparse_vocab_rejected = True  # publish must reset the latch

    resparse(manager)

    assert manager._sparse_encoder is not None
    assert manager._sparse_encoder is manager.store.sparse_encoder
    assert manager.sparse_encoder is manager.store.sparse_encoder
    assert manager._sparse_vocab_rejected is False

    follow_up = manager.save(
        "follow-up on i-03470c789e7b72080 remediation completed", type="note", scope=SCOPE
    )
    point = manager.store.client.retrieve(
        collection_name=manager.store.collection,
        ids=[stable_hash_id(follow_up)],
        with_payload=True,
        with_vectors=True,
    )[0]
    sparse = point.vector["bm25"]
    got = dict(zip(sparse.indices, sparse.values, strict=True))
    expected = manager.store.sparse_encoder.encode_document(point.payload["embedding_text"])
    assert got == pytest.approx(expected)  # encoded with the NEW vocab, in-process
    assert manager.store.sparse_encoder.vocab[QUERY] in got  # identifier now in-vocab


def _dense_vectors(manager: MemoryManager) -> dict[str, list[float]]:
    points = manager.store.scroll(limit=100, with_vectors=True)
    return {p["memory_id"]: p["vector"] for p in points}


def test_dense_vectors_are_byte_identical_after_resparse(tmp_path):
    from memory.resparse import resparse

    manager = _build_manager(tmp_path)
    _seed(manager)
    before = _dense_vectors(manager)

    resparse(manager)

    assert _dense_vectors(manager) == before


def test_count_mismatch_aborts_with_sentinel_held(tmp_path, monkeypatch):
    from memory.resparse import ResparseAbortedError, resparse

    manager = _build_manager(tmp_path)
    _seed(manager)
    monkeypatch.setattr(manager.store, "count", lambda: 9999)

    with pytest.raises(ResparseAbortedError, match="verification failed"):
        resparse(manager)

    assert manager.resparse_sentinel.exists()
    assert manager.sparse_encoder is None


def test_resparse_happy_path_on_embedded_store(tmp_path):
    """The full transaction against the embedded (local-path) store, any lane."""
    from memory.resparse import resparse

    manager = MemoryManager(
        memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "embedded-q")
    )
    manager._embedder = RoutedEmbedder()
    _install_vocab(manager)
    manager.store.recreate_collection()
    target_id = _seed(manager)

    assert target_id not in _identifier_hits(manager)

    result = resparse(manager)

    assert result["points_updated"] == 5 == manager.store.count()
    assert target_id in _identifier_hits(manager)
    assert not manager.resparse_sentinel.exists()
