"""Read-only corpus dry-run: band membership under OLD vs NEW linker bands.

Seeds v1-representation points (stored dense = encode(embedding_text)) on the
test Qdrant and checks the pair report against the calibration fixture pairs.
"""

from __future__ import annotations

import pytest

from core import Embedder, VectorStore
from memory.representation import build_embedding_text

pytestmark = pytest.mark.integration

COLLECTION = "edge_dryrun_test"


def test_dryrun_reports_old_vs_new_band_membership(tmp_path):
    from scripts.edge_count_dryrun import edge_count_dryrun

    from conftest import TEST_QDRANT_URL

    embedder = Embedder()
    store = VectorStore(collection=COLLECTION, url=TEST_QDRANT_URL)
    store.recreate_collection()

    points = [
        # supersedes-grade pair (decision): above both bands' upper bounds
        ("pg16", "Use PostgreSQL 16 for primary storage", "decision", ["PostgreSQL", "storage"]),
        ("pg15", "Use PostgreSQL 15 for primary storage", "decision", ["PostgreSQL", "storage"]),
        # mid-band pair (learning): old ~0.87 in [0.6, 0.9), new ~0.77 in [0.46, 0.85)
        ("mongo", "Use MongoDB as primary datastore", "learning", ["MongoDB", "datastore"]),
        ("pg", "Use PostgreSQL as primary datastore", "learning", ["PostgreSQL", "datastore"]),
        # unrelated pair (note): far below the new band
        ("s3", "Use S3 for file storage", "note", ["storage"]),
        ("kafka", "Use Kafka for event streaming", "note", ["storage"]),
    ]
    for pid, content, mem_type, entities in points:
        meta = {"project": "api", "type": mem_type, "tier": "working", "entities": entities}
        store.save(
            id=pid,
            vector=embedder.encode(build_embedding_text(content, meta)),
            payload={"memory_id": pid, "content": content, **meta},
        )

    report = edge_count_dryrun(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION)

    # one same-type entity-overlapping pair per type
    assert report["considered_pairs"] == 3

    pairs = {frozenset((a, b)): (old, new) for a, b, old, new in report["pairs"]}
    pg_pair = pairs[frozenset(("pg16", "pg15"))]
    mid_pair = pairs[frozenset(("mongo", "pg"))]

    # pg16/pg15: supersedes-grade in both representations, in NEITHER band
    assert pg_pair[0] >= 0.9 and pg_pair[1] >= 0.85
    # mongo/pg: inside the old band on stored vectors AND the new band re-encoded
    assert 0.6 <= mid_pair[0] < 0.9
    assert 0.46 <= mid_pair[1] < 0.85

    assert report["new_band_pairs"] == 1
    assert frozenset(("mongo", "pg")) in pairs
