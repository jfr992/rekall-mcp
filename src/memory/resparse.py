"""Transactional BM25 vocab refit: preflight -> sentinel -> rewrite -> verify -> publish.

Single-writer requirement: the caller must guarantee no concurrent mutations for
the duration of the transaction. The REST route holds the server's maintenance
barrier; embedded/CLI callers are single-process under the ownership protocol.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from qdrant_client.http.models import PointVectors, SparseVector

from core import BM25Encoder
from core.utils import stable_hash_id
from memory.migrate_hybrid import build_corpus, load_all_yaml_memories

if TYPE_CHECKING:
    from memory.manager import MemoryManager

logger = logging.getLogger(__name__)

BATCH_SIZE = 64
REMEDIATION_REINDEX = "run a full reindex (`rekall reindex`) to rebuild the collection"
REMEDIATION_RERUN = "rerun POST /api/memory/resparse to recover; never hand-delete the marker"


class ResparsePreflightError(RuntimeError):
    """Preflight refusal — nothing was mutated."""


class ResparseAbortedError(RuntimeError):
    """Aborted mid-transaction — the sentinel stays; rerun resparse to recover."""


def _assert_sparse_schema(store) -> None:
    info = store.client.get_collection(collection_name=store.collection)
    sparse_fields = getattr(info.config.params, "sparse_vectors", None) or {}
    if "bm25" not in sparse_fields:
        raise ResparsePreflightError(
            f"collection {store.collection!r} has no 'bm25' sparse field — {REMEDIATION_REINDEX}"
        )


def _unreadable_yaml_files(memory_dir: Path) -> list[str]:
    bad: list[str] = []
    for yaml_file in sorted(memory_dir.rglob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            yaml.safe_load(yaml_file.read_text())
        except Exception:
            bad.append(str(yaml_file))
    return bad


def _all_qdrant_ids(store) -> tuple[set[str], int]:
    """Every memory_id in the collection, paginated to exhaustion (no caps)."""
    ids: set[str] = set()
    unlabeled = 0
    offset = None
    while True:
        points, offset = store.client.scroll(
            collection_name=store.collection,
            limit=256,
            offset=offset,
            with_payload=["memory_id"],
        )
        for point in points:
            memory_id = (point.payload or {}).get("memory_id")
            if memory_id:
                ids.add(str(memory_id))
            else:
                unlabeled += 1
        if offset is None:
            return ids, unlabeled


def _assert_parity(manager: MemoryManager, store) -> tuple[list[dict[str, Any]], set[str]]:
    unreadable = _unreadable_yaml_files(manager.memory_dir)
    if unreadable:
        raise ResparsePreflightError(
            f"{len(unreadable)} unreadable YAML file(s) ({unreadable[:3]}) — refusing "
            f"before mutation; {REMEDIATION_REINDEX}"
        )

    memories = load_all_yaml_memories(manager.memory_dir)
    yaml_ids = {str(memory["memory_id"]) for memory in memories}
    qdrant_ids, unlabeled = _all_qdrant_ids(store)
    orphans = sorted(qdrant_ids - yaml_ids)
    if orphans or unlabeled:
        raise ResparsePreflightError(
            f"{len(orphans) + unlabeled} qdrant point(s) with no YAML source "
            f"({len(orphans)} orphan ids, {unlabeled} without memory_id) — refusing "
            f"before mutation; {REMEDIATION_REINDEX}"
        )
    return memories, qdrant_ids


def _sparse_text(memory: dict[str, Any]) -> str:
    # Exactly what the save path sparse-encodes (store.save content=embedding_text).
    return str(memory.get("embedding_text") or "").strip() or str(memory.get("content") or "")


def _rewrite_sparse_vectors(
    store, memories: list[dict[str, Any]], encoder: BM25Encoder, batch_size: int
) -> int:
    points_updated = 0
    for start in range(0, len(memories), batch_size):
        batch = [
            PointVectors(
                id=stable_hash_id(memory["memory_id"]),
                vector={
                    "bm25": SparseVector(
                        indices=list(sparse.keys()),
                        values=list(sparse.values()),
                    )
                },
            )
            for memory in memories[start : start + batch_size]
            for sparse in [encoder.encode_document(_sparse_text(memory))]
        ]
        try:
            store.client.update_vectors(collection_name=store.collection, points=batch, wait=True)
        except Exception:
            logger.warning("resparse batch %d failed — retrying once", start, exc_info=True)
            store.client.update_vectors(collection_name=store.collection, points=batch, wait=True)
        points_updated += len(batch)
    return points_updated


def _read_drift(manager: MemoryManager) -> dict[str, Any]:
    try:
        state = json.loads(manager._bm25_path.with_name("_bm25_drift.json").read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _reset_drift(manager: MemoryManager, corpus_count: int) -> None:
    drift_path = manager._bm25_path.with_name("_bm25_drift.json")
    state = {
        "window": [],
        "saves_since_fit": 0,
        "corpus_count_at_fit": corpus_count,
        "oov_identifier_seen": False,
        "oov_identifier_tokens": [],
    }
    tmp = drift_path.with_name(drift_path.name + ".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, drift_path)


def resparse(manager: MemoryManager, *, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    """Refit the BM25 vocab and rewrite every point's sparse vector, or change nothing."""
    store = manager.store
    _assert_sparse_schema(store)
    memories, qdrant_ids = _assert_parity(manager, store)
    oov_identifier_reset = bool(_read_drift(manager).get("oov_identifier_seen"))

    sentinel = manager.resparse_sentinel
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    try:
        corpus = build_corpus(memories)
        encoder = BM25Encoder()
        encoder.fit(corpus)

        indexed = [m for m in memories if str(m["memory_id"]) in qdrant_ids]
        points_updated = _rewrite_sparse_vectors(store, indexed, encoder, batch_size)

        count = store.count()
        if points_updated != count:
            raise RuntimeError(
                f"resparse verification failed: {points_updated} points updated "
                f"!= {count} points in collection"
            )
    except Exception as exc:
        # Sparse vectors are now mixed-generation: degrade to dense-only until
        # a rerun completes (the sentinel keeps fresh processes dense-only too).
        manager._sparse_encoder = None
        store.sparse_encoder = None
        raise ResparseAbortedError(
            f"resparse aborted ({exc}) — sparse leg disabled; {REMEDIATION_RERUN}"
        ) from exc

    encoder.save(
        str(manager._bm25_path),
        binding={
            "target": str(manager._qdrant_path or manager._qdrant_url),
            "collection": manager.COLLECTION,
            "points": points_updated,
        },
    )
    manager._sparse_encoder = encoder
    store.sparse_encoder = encoder
    manager._sparse_vocab_rejected = False
    _reset_drift(manager, corpus_count=len(corpus))
    sentinel.unlink(missing_ok=True)
    return {
        "points_updated": points_updated,
        "vocab_size": len(encoder.vocab),
        "oov_identifier_reset": oov_identifier_reset,
    }
