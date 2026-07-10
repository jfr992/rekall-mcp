"""Migrate dense vectors to representation v2: encode(content) in place.

Qdrant is the source of truth — this scrolls points WITH payloads and updates
ONLY the named dense vector in place (update_vectors + set_payload), never
replacing the point, so the BM25 sparse leg survives verbatim. It deliberately
does NOT rebuild from YAML: YAML is stale for reinforcement_count / tier
promotions and would resurrect compacted memories.

Per point: dense vector = encode(payload["content"]); payload gains
repr_version: 2 so an interrupted run resumes idempotently (already-stamped
points are skipped).

Safety guards:
- A bm25 collection without a loadable _bm25_vocab.json ABORTS before touching
  anything (dense-only upserts would silently wipe every sparse vector).
- In a bm25 collection, points with blank embedding_text are skipped unstamped
  (counted as skipped_blank_embedding_text) — backfill embedding_text (e.g.
  migrate_hybrid schema pass), then re-run.
- Points with blank content keep their v1 vector permanently (counted as
  no_content, not a failure). Deliberate: there is nothing to re-encode, and
  re-encoding embedding_text would just reproduce the v1 vector they already
  have. Zero-vector repair is scripts/reembed_vectors.py's job.

Usage (never against production without a tarball first — see CLAUDE.md):
    QDRANT_URL=http://localhost:6333 uv run python scripts/migrate_repr_v2.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logger = logging.getLogger(__name__)

BATCH = 64


def _load_sparse_encoder(memory_dir: Path):
    """BM25 encoder when the vocab exists; None keeps the sparse leg untouched."""
    vocab = memory_dir / "_bm25_vocab.json"
    if not vocab.exists():
        return None
    from core import BM25Encoder

    encoder = BM25Encoder()
    encoder.load(str(vocab))
    return encoder


def _snapshot(store) -> tuple[int, dict[str, str], int]:
    """(count, {memory_id: tier} for identity points, compacted-point count)."""
    count = store.count()
    identity: dict[str, str] = {}
    compacted = 0
    for payload in store.scroll(limit=100_000):
        if payload.get("tier") == "identity":
            identity[payload.get("memory_id", "")] = "identity"
        if payload.get("compacted"):
            compacted += 1
    return count, identity, compacted


def migrate_repr_v2(
    qdrant_url: str,
    collection: str = "agent_memory",
    memory_dir: str | Path = "~/.claude/memory",
) -> dict[str, Any]:
    """Re-encode every point's dense vector from payload["content"]. Idempotent."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointVectors

    from core import Embedder, VectorStore

    memory_dir = Path(memory_dir).expanduser()
    client = QdrantClient(url=qdrant_url, timeout=60)

    # Only write the sparse leg when the collection actually has one — an
    # upsert naming "bm25" against a dense-only collection 400s per point.
    # Conversely, a bm25 collection WITHOUT a loadable encoder must abort:
    # dense-only upserts replace the whole point, silently destroying every
    # sparse vector while the run reports success.
    sparse_config = client.get_collection(collection).config.params.sparse_vectors or {}
    sparse_encoder = None
    if "bm25" in sparse_config:
        sparse_encoder = _load_sparse_encoder(memory_dir)
        if sparse_encoder is None:
            raise RuntimeError(
                f"Collection {collection!r} has a bm25 sparse vector but no BM25 "
                f"vocab was loadable from {memory_dir / '_bm25_vocab.json'} — "
                "migrating would wipe all sparse vectors. Fix MEMORY_STORAGE_PATH "
                "or restore _bm25_vocab.json, then re-run."
            )

    store = VectorStore(
        collection=collection,
        url=qdrant_url,
        sparse_encoder=sparse_encoder,
    )
    embedder = Embedder()

    count_before, identity_before, compacted_before = _snapshot(store)

    migrated = skipped = failed = blank_embedding_text = no_content = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=BATCH,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break

        for point in points:
            payload = dict(point.payload or {})
            if payload.get("repr_version") == 2:
                skipped += 1
                continue

            content = str(payload.get("content") or "")
            memory_id = payload.get("memory_id", point.id)
            if not content.strip():
                # Nothing to re-encode: the point keeps its v1 vector (see
                # module docstring). Counted, unstamped, not a run failure.
                logger.warning(f"  {memory_id}: blank content, keeping v1 vector")
                no_content += 1
                continue

            embedding_text = str(payload.get("embedding_text") or "").strip()
            if sparse_encoder is not None and not embedding_text:
                # Belt-and-braces (HIGH-1b): kept even though update_vectors
                # below never touches the sparse leg.
                logger.warning(f"  {memory_id}: blank embedding_text in bm25 collection, skipping")
                blank_embedding_text += 1
                continue

            try:
                # Update ONLY the named dense vector in place; the sparse leg
                # and the rest of the point are never rewritten, which removes
                # the whole replace-the-point sparse-wipe class.
                client.update_vectors(
                    collection_name=collection,
                    points=[PointVectors(id=point.id, vector=embedder.encode(content))],
                )
                client.set_payload(
                    collection_name=collection,
                    payload={"repr_version": 2},
                    points=[point.id],
                )
                migrated += 1
            except Exception as e:
                logger.warning(f"  {memory_id}: {e}")
                failed += 1

        if migrated and migrated % 100 < BATCH:
            logger.info(f"progress: migrated={migrated} skipped={skipped} failed={failed}")
        if offset is None:
            break

    count_after, identity_after, compacted_after = _snapshot(store)

    result = {
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
        "skipped_blank_embedding_text": blank_embedding_text,
        "no_content": no_content,
        "compacted_resurrected": max(0, compacted_after - compacted_before),
        "count_before": count_before,
        "count_after": count_after,
        "identity_tier_changes": len(set(identity_before.items()) ^ set(identity_after.items())),
        "compacted_present": compacted_after,
    }

    logger.info(
        f"DONE migrated={migrated} skipped={skipped} failed={failed} "
        f"count={count_before}->{count_after} "
        f"identity_tier_changes={result['identity_tier_changes']} "
        f"compacted_present={compacted_after}"
    )
    if count_after != count_before:
        logger.error("VERIFY FAILED: point count changed")
    if result["identity_tier_changes"]:
        logger.error("VERIFY FAILED: identity-tier memberships changed")
    if result["compacted_resurrected"]:
        logger.error("VERIFY FAILED: previously-compacted points resurrected")
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    qdrant_url = os.environ.get("QDRANT_URL")
    if not qdrant_url:
        print("QDRANT_URL env var is required (no default — this touches every vector)")
        return 1
    result = migrate_repr_v2(
        qdrant_url=qdrant_url,
        collection=os.environ.get("REKALL_COLLECTION", "agent_memory"),
        memory_dir=os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory"),
    )
    print(f"Result: {result}")
    ok = (
        result["failed"] == 0
        and result["count_before"] == result["count_after"]
        and result["identity_tier_changes"] == 0
        and result["compacted_resurrected"] == 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
