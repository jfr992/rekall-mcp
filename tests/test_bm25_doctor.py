"""T4 — doctor `bm25` block: vocab health, drift signals, verdict."""

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
    def save(self, id, vector, payload, content=None):
        pass

    def search(self, **kwargs):
        return []

    def scroll(self, filters=None, limit=10000, with_vectors=False):
        return []

    def count(self):
        return 0


class FakeEmbedder:
    dimensions = 384

    def encode(self, text: str) -> list[float]:
        return [0.1] * 384


@pytest.fixture
def doctor_manager(tmp_path: Path) -> MemoryManager:
    manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "qdrant"))
    manager._store = FakeStore()
    manager._embedder = FakeEmbedder()
    return manager


def _install_vocab(manager: MemoryManager, corpus: list[str] = CORPUS) -> None:
    from core import BM25Encoder

    encoder = BM25Encoder()
    encoder.fit(corpus)
    encoder.save(str(manager._bm25_path))


def _write_drift(manager: MemoryManager, **state) -> None:
    defaults = {
        "window": [],
        "saves_since_fit": 0,
        "corpus_count_at_fit": None,
        "oov_identifier_seen": False,
        "oov_identifier_tokens": [],
    }
    manager._bm25_path.with_name("_bm25_drift.json").write_text(json.dumps({**defaults, **state}))


def test_doctor_reports_healthy_bm25_block(doctor_manager):
    _install_vocab(doctor_manager)
    _write_drift(doctor_manager, window=[0.0, 0.1], saves_since_fit=2)

    report = doctor_manager.doctor()

    block = report["bm25"]
    assert block["vocab_present"] is True
    assert block["vocab_size"] == len(doctor_manager.sparse_encoder.vocab)
    assert block["vocab_age_days"] < 1
    assert block["binding_ok"] is True
    assert block["oov_rate_window"] == pytest.approx(0.05)
    assert block["oov_identifier_seen"] is False
    assert block["saves_since_fit"] == 2
    assert block["verdict"] == "ok"


def test_high_oov_window_mean_makes_verdict_stale(doctor_manager):
    _install_vocab(doctor_manager)
    _write_drift(doctor_manager, window=[0.2, 0.3, 0.1], saves_since_fit=3)

    report = doctor_manager.doctor()

    assert report["bm25"]["verdict"] == "stale"


def test_vocab_older_than_seven_days_makes_verdict_stale(doctor_manager):
    import os
    import time

    _install_vocab(doctor_manager)
    eight_days_ago = time.time() - 8 * 86400
    os.utime(doctor_manager._bm25_path, (eight_days_ago, eight_days_ago))

    report = doctor_manager.doctor()

    assert report["bm25"]["vocab_age_days"] > 7
    assert report["bm25"]["verdict"] == "stale"


def test_oov_identifier_flag_makes_verdict_stale(doctor_manager):
    _install_vocab(doctor_manager)
    _write_drift(
        doctor_manager,
        window=[0.05],
        saves_since_fit=1,
        oov_identifier_seen=True,
        oov_identifier_tokens=["i-03470c789e7b72080"],
    )

    report = doctor_manager.doctor()

    assert report["bm25"]["oov_identifier_seen"] is True
    assert report["bm25"]["verdict"] == "stale"


def test_degraded_bm25_surfaces_in_notes_never_findings_and_leaves_status_alone(doctor_manager):
    """Contract: bm25 health is advisory — global status is governed by store integrity."""
    _install_vocab(doctor_manager)
    _write_drift(doctor_manager, window=[0.9, 0.8], saves_since_fit=2)

    report = doctor_manager.doctor()

    assert report["bm25"]["verdict"] == "stale"
    assert "bm25:stale" in report["notes"]
    assert report["findings"] == []
    assert report["status"] == "healthy"


def test_missing_vocab_reports_missing_verdict(doctor_manager):
    report = doctor_manager.doctor()

    block = report["bm25"]
    assert block["vocab_present"] is False
    assert block["vocab_age_days"] is None
    assert block["vocab_size"] is None
    assert block["verdict"] == "missing"


def test_corrupt_vocab_reports_corrupt_verdict_without_degrading_status(doctor_manager):
    doctor_manager._bm25_path.write_text("{definitely not json[")

    report = doctor_manager.doctor()

    block = report["bm25"]
    assert block["vocab_present"] is True
    assert block["vocab_size"] is None
    assert block["verdict"] == "corrupt"
    assert "bm25:corrupt" in report["notes"]
    assert report["status"] == "healthy"


def test_vocab_bound_to_another_store_reports_binding_not_ok(doctor_manager):
    from core import BM25Encoder

    encoder = BM25Encoder()
    encoder.fit(CORPUS)
    encoder.save(
        str(doctor_manager._bm25_path),
        binding={"target": "http://elsewhere:6333", "collection": "agent_memory"},
    )

    report = doctor_manager.doctor()

    assert report["bm25"]["binding_ok"] is False
