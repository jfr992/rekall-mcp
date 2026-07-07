"""get_many(with_vectors=True) — Stage B needs stored embedding vectors."""

import pytest


@pytest.mark.integration
def test_get_many_with_vectors(qdrant_store_with_two_points):
    store = qdrant_store_with_two_points
    results = store.get_many(store.known_ids, with_vectors=True)
    assert all(isinstance(r.get("_vector"), list) and len(r["_vector"]) == 384 for r in results)


@pytest.fixture
def qdrant_store_with_two_points():
    """VectorStore populated with two dense points against test Qdrant (:6334)."""
    from core import Embedder, VectorStore

    embedder = Embedder()
    store = VectorStore(collection="test_get_many_vectors", url="http://localhost:6334")

    id1 = "2026-01-01_fact_aaa"
    id2 = "2026-02-01_fact_bbb"

    v1 = embedder.encode("the billing database is MySQL 8")
    v2 = embedder.encode("the billing database migrated to CockroachDB")

    store.save(id=id1, vector=v1, payload={"memory_id": id1, "content": "MySQL 8", "type": "fact"})
    store.save(
        id=id2, vector=v2, payload={"memory_id": id2, "content": "CockroachDB", "type": "fact"}
    )

    store.known_ids = [id1, id2]
    yield store

    try:
        store.delete_collection()
    except Exception:
        pass
