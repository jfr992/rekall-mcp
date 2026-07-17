"""T3 — transactional resparse: preflight -> sentinel -> rewrite -> verify -> publish."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import BM25Encoder
from memory import MemoryManager
from memory.scope import MemoryScope

from tests.conftest import TEST_QDRANT_URL

pytestmark = pytest.mark.integration

QUERY = "i-03470c789e7b72080"
TARGET_CONTENT = "Instance i-03470c789e7b72080 hit EdgeHostDeviceAlreadyInUse on the edge host"
FILLER_CONTENTS = [f"filler note number {i} about the deployment pipeline rollout" for i in range(4)]
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
