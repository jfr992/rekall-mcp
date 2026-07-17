"""T4 — BM25 vocab drift tracking on the save path (manager-level)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory import MemoryManager

CORPUS = [
    "postgres database decision for the api service",
    "docker compose deployment pipeline notes",
    "jwt validation bug fixed in auth middleware",
    "terraform module for the vpc network stack",
]


class FakeStore:
    """Captures save() calls; search/scroll return nothing (no dedupe hits)."""

    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save(self, id, vector, payload, content=None):
        self.saved.append({"id": id, "content": content, "payload": payload})

    def search(self, **kwargs):
        return []

    def scroll(self, filters=None, limit=10000, with_vectors=False):
        return []

    def count(self):
        return 0


class FakeEmbedder:
    dimensions = 384

    def encode(self, text: str) -> list[float]:
        vector = [0.1] * 384
        vector[0] = len(text) / 1000.0
        return vector


@pytest.fixture
def drift_manager(tmp_path: Path) -> MemoryManager:
    manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "qdrant"))
    manager._store = FakeStore()
    manager._embedder = FakeEmbedder()
    return manager


def _install_vocab(manager: MemoryManager, corpus: list[str] = CORPUS) -> None:
    from core import BM25Encoder

    encoder = BM25Encoder()
    encoder.fit(corpus)
    encoder.save(str(manager._bm25_path))


def _drift_state(manager: MemoryManager) -> dict:
    return json.loads((manager._bm25_path.with_name("_bm25_drift.json")).read_text())


def test_save_records_oov_rate_in_drift_window(drift_manager):
    _install_vocab(drift_manager)

    drift_manager.save("Chose postgres for the api service", type="decision", project="proj")

    encoder = drift_manager.sparse_encoder
    assert encoder is not None
    embedding_text = drift_manager._store.saved[0]["content"]
    tokens = encoder._tokenize(embedding_text)
    expected_rate = round(len([t for t in tokens if t not in encoder.vocab]) / len(tokens), 4)

    state = _drift_state(drift_manager)
    assert state["window"] == [expected_rate]
    assert state["saves_since_fit"] == 1
    assert state["corpus_count_at_fit"] == len(CORPUS)


def test_drift_window_is_capped_at_last_50_saves(drift_manager):
    _install_vocab(drift_manager)

    for i in range(55):
        drift_manager.save(f"unique memory number {i} about topic {i}", project="proj")

    state = _drift_state(drift_manager)
    assert len(state["window"]) == 50
    assert state["saves_since_fit"] == 55


def test_oov_identifier_token_sets_persisted_fast_flag(drift_manager):
    _install_vocab(drift_manager)

    drift_manager.save(
        "Instance i-03470c789e7b72080 hit EdgeHostDeviceAlreadyInUse", project="proj"
    )

    state = _drift_state(drift_manager)
    assert state["oov_identifier_seen"] is True
    assert "i-03470c789e7b72080" in state["oov_identifier_tokens"]


def test_plain_word_oov_does_not_set_identifier_flag(drift_manager):
    from memory.scope import MemoryScope

    _install_vocab(drift_manager)

    # Explicit scope: ambient git detection would inject the hyphenated repo
    # name (rekall-bm25) into embedding_text and trip the flag legitimately.
    drift_manager.save(
        "kubernetes cluster autoscaling investigation",
        project="proj",
        scope=MemoryScope(agent="test", project="proj"),
    )

    state = _drift_state(drift_manager)
    assert state["oov_identifier_seen"] is False
    assert state["oov_identifier_tokens"] == []


def test_no_encoder_loaded_skips_drift_tracking(drift_manager):
    # No vocab installed — sparse_encoder is None.
    drift_manager.save("some memory without any vocab", project="proj")

    assert not drift_manager._bm25_path.with_name("_bm25_drift.json").exists()


def test_corrupt_vocab_degrades_to_dense_only_with_one_loud_warning(tmp_path, caplog):
    import logging

    manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "qdrant"))
    manager._embedder = FakeEmbedder()
    manager._bm25_path.write_text("{definitely not json[")

    with caplog.at_level(logging.WARNING):
        memory_id = manager.save("survives a corrupt vocab file", project="proj")
        results = manager.recall("corrupt vocab", project="proj")

    assert memory_id
    assert isinstance(results, list)
    corrupt_warnings = [r for r in caplog.records if "dense-only" in r.getMessage()]
    assert len(corrupt_warnings) == 1


def test_corrupt_drift_state_is_treated_as_empty_window(drift_manager):
    _install_vocab(drift_manager)
    drift_manager._bm25_path.with_name("_bm25_drift.json").write_text("{not json[")

    memory_id = drift_manager.save("survives corrupt drift state", project="proj")

    assert memory_id
    state = _drift_state(drift_manager)
    assert len(state["window"]) == 1
    assert state["saves_since_fit"] == 1
