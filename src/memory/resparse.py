"""Transactional BM25 vocab refit: preflight -> sentinel -> rewrite -> verify -> publish.

Single-writer requirement: the caller must guarantee no concurrent mutations for
the duration of the transaction. The REST route holds the server's maintenance
barrier; embedded/CLI callers are single-process under the ownership protocol.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from memory.migrate_hybrid import load_all_yaml_memories

if TYPE_CHECKING:
    from memory.manager import MemoryManager

logger = logging.getLogger(__name__)

BATCH_SIZE = 64
REMEDIATION_REINDEX = "run a full reindex (`rekall reindex`) to rebuild the collection"


class ResparsePreflightError(RuntimeError):
    """Preflight refusal — nothing was mutated."""


class ResparseAbortedError(RuntimeError):
    """Aborted mid-transaction — the sentinel stays; rerun resparse to recover."""


def _assert_sparse_schema(store) -> None:
    info = store.client.get_collection(collection_name=store.collection)
    sparse_fields = getattr(info.config.params, "sparse_vectors", None) or {}
    if "bm25" not in sparse_fields:
        raise ResparsePreflightError(
            f"collection {store.collection!r} has no 'bm25' sparse field — "
            f"{REMEDIATION_REINDEX}"
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


def resparse(manager: MemoryManager, *, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    """Refit the BM25 vocab and rewrite every point's sparse vector, or change nothing."""
    store = manager.store
    _assert_sparse_schema(store)
    memories, qdrant_ids = _assert_parity(manager, store)
    raise NotImplementedError
