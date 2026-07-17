"""Prod regression (2026-07-17, round 2): a sparse-rescued exact-token hit
survived the store threshold (PR #70) but lost the manager blend's final cut —
frozen weights score a low-cosine fresh memory below older high-cosine
distractors. Coverage contract: the best sparse-rescued hit gets one reserved
slot in the final top-limit. Weights untouched.

Runs through the PRODUCTION recall path with production defaults (the previous
eval called store.search with drifted parameters and went green while prod
missed — see LESSONS 2026-07-17).
"""

import pytest


@pytest.mark.integration
class TestSparseRescueFinalCut:
    IDENTIFIER = "EdgeHostDeviceAlreadyInUse"

    @pytest.fixture(params=["server"])
    def manager(self, request, tmp_path, monkeypatch):
        from core import BM25Encoder
        from memory.manager import MemoryManager

        class RoutedEmbedder:
            """Identifier doc dense-orthogonal to its query; distractors adjacent."""

            dimensions = 384

            def encode(self, text: str) -> list[float]:
                v = [0.0] * 384
                ident = TestSparseRescueFinalCut.IDENTIFIER.lower()
                if text.strip().lower() == ident:
                    # the QUERY: dense-adjacent to distractors, orthogonal to target
                    v[0] = 1.0
                elif ident in text.lower():
                    v[383] = 1.0
                else:
                    # distractors and query share the first axis, unique second
                    # axis per text so the 0.97 dedupe never collapses them
                    v[0] = 0.9
                    v[1 + (abs(hash(text)) % 300)] = 0.44
                return v

        distractors = [
            f"palette cluster deploy notes variant {i}: profiles, packs, retries" for i in range(8)
        ]
        target = (
            f"bevm destroy failed: delete edge host returned 500 "
            f"{self.IDENTIFIER} - already used in cluster; force-delete hosts"
        )
        corpus = [*distractors, target]

        # Vocab on disk BEFORE the first save: the lazy encoder loads it, the
        # collection is created with the sparse field, saves carry sparse.
        encoder = BM25Encoder()
        encoder.fit(corpus)
        encoder.save(str(tmp_path / "_bm25_vocab.json"))

        from qdrant_client import QdrantClient

        QdrantClient(url="http://localhost:6334").delete_collection("test_sparse_rescue")

        mgr = MemoryManager(
            memory_dir=tmp_path,
            qdrant_url="http://localhost:6334",
        )
        mgr.COLLECTION = "test_sparse_rescue"
        mgr._embedder = RoutedEmbedder()
        for content in corpus:
            mgr.save(content=content, memory_type="learning", project="lab")

        yield mgr
        try:
            mgr.store.delete_collection()
        except Exception:
            pass

    def test_sparse_rescued_hit_survives_the_final_cut(self, manager):
        # Production defaults: limit=5, default score_threshold.
        results = manager.recall(query=self.IDENTIFIER, limit=5, project="lab")
        contents = [r.get("content", "") for r in results]
        assert any(self.IDENTIFIER in c for c in contents), (
            f"exact-token memory lost the final cut: {[c[:40] for c in contents]}"
        )
