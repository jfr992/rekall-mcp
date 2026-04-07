"""Integration tests for benchmark retrieval modes.

Requires Qdrant on port 6334 (test instance).
Run: docker compose up qdrant-test -d
"""
import json
import pytest

qdrant = pytest.importorskip("qdrant_client")


def qdrant_available():
    try:
        client = qdrant.QdrantClient(url="http://localhost:6334", timeout=2)
        client.get_collections()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not qdrant_available(),
    reason="Qdrant test instance not running on port 6334",
)


SAMPLE_ENTRY = {
    "question_id": "q_bench_001",
    "question_type": "single-session-user",
    "question": "What database does the user prefer?",
    "question_date": "2025-06-15",
    "answer": "PostgreSQL",
    "answer_session_ids": ["sess_003"],
    "haystack_session_ids": ["sess_001", "sess_002", "sess_003", "sess_004", "sess_005"],
    "haystack_dates": ["2025-06-01", "2025-06-05", "2025-06-10", "2025-06-12", "2025-06-14"],
    "haystack_sessions": [
        [
            {"role": "user", "content": "How do I set up a Python virtual environment?"},
            {"role": "assistant", "content": "Use python -m venv..."},
        ],
        [
            {"role": "user", "content": "What's the weather like in Ottawa today?"},
            {"role": "assistant", "content": "I don't have real-time weather data..."},
        ],
        [
            {
                "role": "user",
                "content": "I really love PostgreSQL. It's my favorite database for everything. The JSONB support and window functions are incredible.",
            },
            {"role": "assistant", "content": "PostgreSQL is excellent..."},
        ],
        [
            {"role": "user", "content": "Can you explain Docker networking?"},
            {"role": "assistant", "content": "Docker uses bridge networks by default..."},
        ],
        [
            {"role": "user", "content": "Tell me about Kubernetes pod scheduling"},
            {"role": "assistant", "content": "The kube-scheduler assigns pods..."},
        ],
    ],
}


class TestDenseMode:
    def test_retrieves_correct_session(self):
        from benchmarks.modes import retrieve_dense

        ranked_ids = retrieve_dense(
            SAMPLE_ENTRY, qdrant_url="http://localhost:6334", n_results=5
        )
        assert "sess_003" in ranked_ids[:5]

    def test_returns_all_session_ids(self):
        from benchmarks.modes import retrieve_dense

        ranked_ids = retrieve_dense(
            SAMPLE_ENTRY, qdrant_url="http://localhost:6334", n_results=10
        )
        assert len(ranked_ids) == 5


class TestHybridMode:
    def test_retrieves_correct_session(self):
        from benchmarks.modes import retrieve_hybrid

        ranked_ids = retrieve_hybrid(
            SAMPLE_ENTRY, qdrant_url="http://localhost:6334", n_results=5
        )
        assert "sess_003" in ranked_ids[:5]


class TestHybridGraphMode:
    def test_retrieves_correct_session(self):
        from benchmarks.modes import retrieve_hybrid_graph

        ranked_ids = retrieve_hybrid_graph(
            SAMPLE_ENTRY, qdrant_url="http://localhost:6334", n_results=5
        )
        assert "sess_003" in ranked_ids[:5]
