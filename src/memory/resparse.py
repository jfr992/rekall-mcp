"""Transactional BM25 vocab refit: preflight -> sentinel -> rewrite -> verify -> publish.

Single-writer requirement: the caller must guarantee no concurrent mutations for
the duration of the transaction. The REST route holds the server's maintenance
barrier; embedded/CLI callers are single-process under the ownership protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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


def resparse(manager: MemoryManager, *, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    """Refit the BM25 vocab and rewrite every point's sparse vector, or change nothing."""
    store = manager.store
    _assert_sparse_schema(store)
    raise NotImplementedError
