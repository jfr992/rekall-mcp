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


def test_migrate_aborts_when_bm25_collection_has_no_vocab(tmp_path):
    """A collection WITH a bm25 sparse config but no loadable vocab must ABORT:
    dense-only upserts would silently destroy every point's sparse vector while
    the run reports success."""
    from scripts.migrate_repr_v2 import migrate_repr_v2

    from conftest import TEST_QDRANT_URL

    class DummySparse:
        def encode(self, content):
            return {1: 1.0}

    embedder = Embedder()
    store = VectorStore(collection=COLLECTION, url=TEST_QDRANT_URL, sparse_encoder=DummySparse())
    store.recreate_collection()
    store.save(
        id="2026-07-01_note_cccc3333",
        vector=embedder.encode("some note"),
        payload={"memory_id": "2026-07-01_note_cccc3333", "content": "some note", "type": "note"},
    )

    with pytest.raises(RuntimeError, match="bm25"):
        # tmp_path has no _bm25_vocab.json
        migrate_repr_v2(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION, memory_dir=tmp_path)


def test_migrate_skips_blank_embedding_text_points_in_bm25_collection(tmp_path):
    """In a bm25 collection, a point with blank embedding_text must be SKIPPED
    (counted, not stamped): upserting it dense-only would wipe its sparse
    vector. Points with embedding_text migrate normally."""
    from scripts.migrate_repr_v2 import migrate_repr_v2

    from conftest import TEST_QDRANT_URL
    from core import BM25Encoder

    encoder = BM25Encoder()
    encoder.fit(["Project api. Claim: good point with sparse text", "some other doc"])
    encoder.save(str(tmp_path / "_bm25_vocab.json"))

    embedder = Embedder()
    store = VectorStore(collection=COLLECTION, url=TEST_QDRANT_URL, sparse_encoder=encoder)
    store.recreate_collection()

    good = {
        "memory_id": "2026-07-01_note_good1111",
        "content": "good point with sparse text",
        "embedding_text": "Project api. Claim: good point with sparse text",
        "type": "note",
    }
    blank = {
        "memory_id": "2026-07-01_note_blank222",
        "content": "point with blank embedding text",
        "embedding_text": "   ",
        "type": "note",
    }
    for p in (good, blank):
        store.save(
            id=p["memory_id"],
            vector=embedder.encode(p["embedding_text"]),
            payload=p,
            content=p["embedding_text"].strip() or None,
        )

    result = migrate_repr_v2(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION, memory_dir=tmp_path)

    assert result["migrated"] == 1
    assert result["skipped_blank_embedding_text"] == 1
    assert result["failed"] == 0

    by_id = {m["memory_id"]: m for m in store.get_many([good["memory_id"], blank["memory_id"]])}
    assert by_id[good["memory_id"]]["repr_version"] == 2
    # not stamped: a later run (after embedding_text backfill) can still migrate it
    assert "repr_version" not in by_id[blank["memory_id"]]


def test_migrate_blank_content_keeps_v1_vector_and_does_not_fail_run(tmp_path):
    """A point with blank content can never be re-encoded: it keeps its v1
    vector, is counted as no_content (not failed — the run's exit code stays
    honest for idempotent re-runs), and stays unstamped. compacted_resurrected
    is reported for the nonzero-exit verify path."""
    from scripts.migrate_repr_v2 import migrate_repr_v2

    from conftest import TEST_QDRANT_URL

    embedder = Embedder()
    store = VectorStore(collection=COLLECTION, url=TEST_QDRANT_URL)
    store.recreate_collection()
    store.save(
        id="2026-07-01_note_blankc11",
        vector=embedder.encode("placeholder v1 vector"),
        payload={"memory_id": "2026-07-01_note_blankc11", "content": "   ", "type": "note"},
    )

    result = migrate_repr_v2(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION, memory_dir=tmp_path)

    assert result["no_content"] == 1
    assert result["failed"] == 0
    assert result["migrated"] == 0
    assert result["compacted_resurrected"] == 0
    point = store.get_by_id("2026-07-01_note_blankc11")
    assert "repr_version" not in point


def test_main_exits_nonzero_on_compacted_resurrection(monkeypatch):
    """The verify failure for resurrected compacted points must fail the run."""
    import scripts.migrate_repr_v2 as mod

    monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
    monkeypatch.setattr(
        mod,
        "migrate_repr_v2",
        lambda **kwargs: {
            "migrated": 1,
            "skipped": 0,
            "failed": 0,
            "skipped_blank_embedding_text": 0,
            "no_content": 0,
            "count_before": 1,
            "count_after": 1,
            "identity_tier_changes": 0,
            "compacted_present": 1,
            "compacted_resurrected": 1,
        },
    )

    assert mod.main([]) == 1


def test_migrate_preserves_sparse_vector_byte_identical(tmp_path):
    """A point whose embedding_text is OOV for the vocab (sparse-encodes to {})
    must keep its stored sparse vector byte-identical: the migration updates
    ONLY the named dense vector, never replacing the point."""
    from qdrant_client import QdrantClient
    from scripts.migrate_repr_v2 import migrate_repr_v2

    from conftest import TEST_QDRANT_URL
    from core import BM25Encoder
    from core.utils import stable_hash_id

    encoder = BM25Encoder()
    encoder.fit(["postgresql storage decision text", "another vocabulary document"])
    encoder.save(str(tmp_path / "_bm25_vocab.json"))

    embedder = Embedder()
    store = VectorStore(collection=COLLECTION, url=TEST_QDRANT_URL, sparse_encoder=encoder)
    store.recreate_collection()

    # Seed with in-vocab text so the point HAS a sparse vector, then the
    # payload's embedding_text is OOV — old store.save migration would take
    # the dense-only branch and wipe the sparse leg.
    memory_id = "2026-07-01_note_oov11111"
    store.save(
        id=memory_id,
        vector=embedder.encode("v1 placeholder"),
        payload={
            "memory_id": memory_id,
            "content": "postgresql storage decision text",
            "embedding_text": "zzzqx wvvkj entirely out of vocabulary",
            "type": "note",
        },
        content="postgresql storage decision text",
    )

    client = QdrantClient(url=TEST_QDRANT_URL)

    def sparse_of() -> tuple[list[int], list[float]]:
        rec = client.retrieve(
            collection_name=COLLECTION, ids=[stable_hash_id(memory_id)], with_vectors=True
        )[0]
        sparse = rec.vector["bm25"]
        return list(sparse.indices), list(sparse.values)

    sparse_before = sparse_of()
    assert sparse_before[0], "fixture must have a non-empty sparse vector"
    dense_before = store.get_many([memory_id], with_vectors=True)[0]["_vector"]

    result = migrate_repr_v2(qdrant_url=TEST_QDRANT_URL, collection=COLLECTION, memory_dir=tmp_path)

    assert result["migrated"] == 1
    assert sparse_of() == sparse_before, "sparse vector must survive byte-identical"
    after = store.get_many([memory_id], with_vectors=True)[0]
    assert after["_vector"] != dense_before, "dense vector must be re-encoded"
    assert after["repr_version"] == 2


def test_main_strict_by_default_fails_on_unmigrated_points(monkeypatch):
    """Points left at v1 are semantically invisible to content-encoded dense
    queries — a partial migration must not exit 0 unless explicitly allowed."""
    import scripts.migrate_repr_v2 as mod

    monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
    result = {
        "migrated": 5,
        "skipped": 0,
        "failed": 0,
        "skipped_blank_embedding_text": 1,
        "no_content": 1,
        "unmigrated_ids": ["2026-07-01_note_blank222", "2026-07-01_note_blankc11"],
        "count_before": 7,
        "count_after": 7,
        "identity_tier_changes": 0,
        "compacted_present": 0,
        "compacted_resurrected": 0,
    }
    monkeypatch.setattr(mod, "migrate_repr_v2", lambda **kwargs: dict(result))

    assert mod.main([]) == 1, "strict default: unmigrated points must fail the run"
    assert mod.main(["--allow-partial"]) == 0, "--allow-partial overrides explicitly"
