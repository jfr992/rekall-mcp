"""Integration tests for benchmark retrieval modes.

Requires disposable test Qdrant:
- host: http://localhost:6334
- docker compose: http://qdrant-test:6333
"""

import os
from copy import deepcopy
from uuid import uuid4

import pytest

qdrant = pytest.importorskip("qdrant_client")


def _test_qdrant_url():
    configured = os.environ.get("QDRANT_URL")
    if configured and ("qdrant-test:6333" in configured or ":6334" in configured):
        return configured
    return "http://localhost:6334"


TEST_QDRANT_URL = _test_qdrant_url()


def qdrant_available():
    try:
        client = qdrant.QdrantClient(url=TEST_QDRANT_URL, timeout=2)
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


@pytest.fixture
def sample_entry():
    entry = deepcopy(SAMPLE_ENTRY)
    entry["question_id"] = f"{entry['question_id']}_{uuid4().hex}"
    return entry


class TestDenseMode:
    def test_retrieves_correct_session(self, sample_entry):
        from benchmarks.modes import retrieve_dense

        ranked_ids = retrieve_dense(sample_entry, qdrant_url=TEST_QDRANT_URL, n_results=5)
        assert "sess_003" in ranked_ids[:5]

    def test_returns_all_session_ids(self, sample_entry):
        from benchmarks.modes import retrieve_dense

        ranked_ids = retrieve_dense(sample_entry, qdrant_url=TEST_QDRANT_URL, n_results=10)
        assert len(ranked_ids) == 5


class TestHybridMode:
    def test_retrieves_correct_session(self, sample_entry):
        from benchmarks.modes import retrieve_hybrid

        ranked_ids = retrieve_hybrid(sample_entry, qdrant_url=TEST_QDRANT_URL, n_results=5)
        assert "sess_003" in ranked_ids[:5]


class TestHybridGraphMode:
    def test_retrieves_correct_session(self, sample_entry):
        from benchmarks.modes import retrieve_hybrid_graph

        ranked_ids = retrieve_hybrid_graph(sample_entry, qdrant_url=TEST_QDRANT_URL, n_results=5)
        assert "sess_003" in ranked_ids[:5]
