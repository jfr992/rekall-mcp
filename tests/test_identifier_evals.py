"""T5 — identifier-recall evals: hybrid BM25+dense on identifier-shaped queries.

Lives apart from tests/test_software_evals.py (frozen probes; corpus additions
would perturb its scenario rankings — that file stays byte-identical).

Technique notes:
- Dense vectors are deterministic and routed (RoutedIdentifierEmbedder):
  identifier target docs are orthogonal to identifier queries while distractors
  overlap the query, so "dense misses / hybrid hits" is a fixture property,
  not a bet on real-embedder quality.
- The bootstrap test seeds BOOTSTRAP_THRESHOLD memories through the real
  manager.save path (chosen over installing a fitted encoder: it also pins
  that a sub-threshold corpus silently never exercises hybrid — Codex M8).
  The other tests install a fitted encoder explicitly because it's faster.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.conftest import TEST_QDRANT_URL
from tests.test_resparse import _install_vocab

from memory import MemoryManager
from memory.scope import MemoryScope

pytestmark = pytest.mark.integration

# Three identifier classes: camelcase-flattened error class, instance ID,
# hyphenated pack name. Queries are the exact tokens.
ERROR_CLASS = "EdgeHostDeviceAlreadyInUse"
INSTANCE_ID = "i-0abc123def456"
PACK_NAME = "lb-metallb-helm"

TARGETS = {
    ERROR_CLASS: (
        f"Deploy failed with {ERROR_CLASS} because the edge host was still "
        "registered to the previous cluster"
    ),
    INSTANCE_ID: (
        f"Instance {INSTANCE_ID} ran out of disk during the canary rollout and "
        "was replaced by the autoscaler"
    ),
    PACK_NAME: (
        f"Pinned {PACK_NAME} to the previous chart version after the "
        "loadbalancer address pool regression"
    ),
}

# Hyphen/underscore-free so no distractor save ever records an
# identifier-shaped OOV token (keeps the drift assertions unambiguous).
DISTRACTORS = [
    f"distractor note number {i} about the deployment pipeline review topic {i}"
    for i in range(8)
]

SCOPE = MemoryScope(agent="test", project="proj")


class RoutedIdentifierEmbedder:
    """Deterministic router: identifier queries and their targets never meet in dense space.

    - exact identifier query -> dims 0..7 (overlaps every distractor)
    - target doc (contains an identifier) -> its own dim at 100+ (orthogonal to the query)
    - distractor i -> dim i (cosine ~0.35 with the query, orthogonal to each other)
    - bootstrap corpus note i -> unique dim at 10+i (no dedupe collapse across 50 saves)
    """

    dimensions = 384

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * 384
        stripped = text.strip()
        if stripped in TARGETS:
            for i in range(8):
                vector[i] = 0.5
            return vector
        for slot, identifier in enumerate(TARGETS):
            if identifier in text:
                vector[100 + slot] = 1.0
                return vector
        if "distractor note number" in text:
            index = int(text.split("distractor note number ")[1].split()[0])
            vector[index % 8] = 1.0
            return vector
        if "corpus note number" in text:
            index = int(text.split("corpus note number ")[1].split()[0])
            vector[10 + index] = 1.0
            return vector
        vector[300 + (hash(text) % 80)] = 1.0
        return vector


def _build_manager(tmp_path: Path, *, vocab_corpus: list[str] | None = None) -> MemoryManager:
    if os.environ.get("REKALL_TEST_LANE") == "embedded":
        manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"))
    else:
        manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_url=TEST_QDRANT_URL)
    manager._embedder = RoutedIdentifierEmbedder()
    if vocab_corpus is not None:
        _install_vocab(manager, vocab_corpus)
    # sparse_encoder resolves BEFORE the store connects, so the collection is
    # (re)created with the matching schema: sparse when a vocab is installed.
    manager.store.recreate_collection()
    return manager


def _top5_ids(manager: MemoryManager, query: str) -> list[str]:
    results = manager.store.search(
        vector=manager.embedder.encode(query), query_text=query, limit=5
    )
    return [r["memory_id"] for r in results]


def test_bootstrap_threshold_save_path_exercises_sparse_leg_for_identifier_query(
    tmp_path, monkeypatch
):
    """Regression pin: hybrid is actually exercised, asserted at the store.

    Seeds BOOTSTRAP_THRESHOLD memories through manager.save so the vocab
    bootstrap fires naturally, then proves the sparse leg executed for an
    identifier query by counting encode_query calls on the store's encoder —
    a hit alone could come from the dense leg.
    """
    from memory.reindex import BOOTSTRAP_THRESHOLD

    manager = _build_manager(tmp_path)
    target_id = manager.save(TARGETS[ERROR_CLASS], type="note", scope=SCOPE)
    for i in range(BOOTSTRAP_THRESHOLD - 1):
        manager.save(f"corpus note number {i} covering the rollout window", type="note", scope=SCOPE)

    assert manager.store.count() == BOOTSTRAP_THRESHOLD
    assert manager._bm25_path.exists()  # bootstrap fired at the threshold
    encoder = manager.store.sparse_encoder
    assert encoder is not None

    calls: list[str] = []
    original = encoder.encode_query

    def counting(text: str) -> dict[int, float]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(encoder, "encode_query", counting)

    manager.recall(ERROR_CLASS, limit=5, score_threshold=0.0)

    assert calls == [ERROR_CLASS]  # sparse leg executed on the real recall path
    assert original(ERROR_CLASS)  # non-empty encoding: hybrid branch, not dense fallthrough
    assert target_id in _top5_ids(manager, ERROR_CLASS)
