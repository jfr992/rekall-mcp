"""Migration to dense repr v2: re-encode payload["content"] in place, idempotent.

Qdrant is the source of truth (YAML is stale for reinforcement_count / tier
promotions and would resurrect compacted memories). Runs against the disposable
test Qdrant on :6334 only.
"""

from __future__ import annotations

import math

import pytest

from core import Embedder, VectorStore

pytestmark = pytest.mark.integration

COLLECTION = "repr_v2_migration_test"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


@pytest.fixture
def seeded_store():
    """Seed a v1-representation collection: dense = encode(embedding_text)."""
    from conftest import TEST_QDRANT_URL

    embedder = Embedder()
    store = VectorStore(collection=COLLECTION, url=TEST_QDRANT_URL)
    store.recreate_collection()

    points = [
        {
            "memory_id": "2026-07-01_decision_aaaa1111",
            "content": "Decided to use PostgreSQL for JSON support",
            "embedding_text": (
                "Project api. Type decision. Tier working. "
                "Claim: Decided to use PostgreSQL for JSON support"
            ),
            "type": "decision",
            "project": "api",
            "tier": "working",
            "date": "2026-07-01",
        },
        {
            "memory_id": "2026-07-02_preference_bbbb2222",
            "content": "User prefers concise responses",
            "embedding_text": (
                "Project general. Type preference. Tier identity. "
                "Claim: User prefers concise responses"
            ),
            "type": "preference",
            "project": "general",
            "tier": "identity",
            "reinforcement_count": 7,
            "date": "2026-07-02",
        },
    ]
    for p in points:
        store.save(
            id=p["memory_id"],
            vector=embedder.encode(p["embedding_text"]),
            payload=p,
        )
    return store, embedder, points


def test_migrate_reencodes_content_in_place_and_is_idempotent(seeded_store, tmp_path):
    from scripts.migrate_repr_v2 import migrate_repr_v2

    from conftest import TEST_QDRANT_URL

    store, embedder, points = seeded_store
    count_before = store.count()

    result = migrate_repr_v2(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION, memory_dir=tmp_path)

    assert result["migrated"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == 0
    # verification block ran and passed
    assert result["count_before"] == result["count_after"] == count_before
    assert result["identity_tier_changes"] == 0
    assert result["compacted_present"] == 0

    migrated = {
        m["memory_id"]: m
        for m in store.get_many([p["memory_id"] for p in points], with_vectors=True)
    }
    for p in points:
        item = migrated[p["memory_id"]]
        # same point id, payload intact, repr stamped
        assert item["content"] == p["content"]
        assert item["tier"] == p["tier"]
        assert item["repr_version"] == 2
        # dense vector now encodes raw content
        assert _cosine(item["_vector"], embedder.encode(p["content"])) > 0.9999

    # reinforcement_count (Qdrant-only truth) preserved
    assert migrated["2026-07-02_preference_bbbb2222"]["reinforcement_count"] == 7

    # idempotent resume: second run skips every point
    rerun = migrate_repr_v2(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION, memory_dir=tmp_path)
    assert rerun["migrated"] == 0
    assert rerun["skipped"] == 2
    assert rerun["failed"] == 0
    assert store.count() == count_before
