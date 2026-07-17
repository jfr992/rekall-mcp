"""scroll_all — exhaustive filtered scroll for insights tier/date aggregation.

The plain scroll() caps at `limit` and drops Qdrant's next_offset; aggregate
counts need every matching point, fetched in pages.
"""

import pytest


@pytest.fixture
def scroll_store():
    from core import VectorStore

    store = VectorStore(collection="test_scroll_all", url="http://localhost:6334")
    for i in range(5):
        memory_id = f"2026-07-0{i + 1}_fact_{i}"
        store.save(
            id=memory_id,
            vector=[float(i + 1)] * 384,
            payload={
                "memory_id": memory_id,
                "type": "fact",
                "project": "proj-a",
                "tier": "working",
            },
        )
    yield store
    try:
        store.delete_collection()
    except Exception:
        pass


@pytest.mark.integration
def test_scroll_all_paginates_past_batch_size(scroll_store):
    results = scroll_store.scroll_all(filters={"project": "proj-a"}, batch_size=2)

    assert len(results) == 5
    assert {r["memory_id"] for r in results} == {f"2026-07-0{i + 1}_fact_{i}" for i in range(5)}
