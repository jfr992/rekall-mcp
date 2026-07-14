"""Embedded (local-path) Qdrant mode for VectorStore and MemoryManager."""

import pytest

from core.vector_store import VectorStore


def test_path_mode_constructs_local_client(tmp_path):
    vs = VectorStore(collection="t", path=str(tmp_path / "q"))
    vs.save(
        id="2026-01-01_note_aaaa1111",
        vector=[0.1] * 384,
        payload={"memory_id": "2026-01-01_note_aaaa1111", "content": "x"},
        content=None,
    )
    assert vs.get_many(["2026-01-01_note_aaaa1111"])[0]["memory_id"] == "2026-01-01_note_aaaa1111"


def test_url_and_path_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        VectorStore(collection="t", url="http://localhost:6334", path=str(tmp_path / "q"))
