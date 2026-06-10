import json

import pytest

SAMPLE_ENTRY = {
    "question_id": "q001",
    "question_type": "single-session-user",
    "question": "What is the user's favorite database?",
    "question_date": "2025-06-15",
    "answer": "PostgreSQL",
    "answer_session_ids": ["sess_003"],
    "haystack_session_ids": ["sess_001", "sess_002", "sess_003"],
    "haystack_dates": ["2025-06-01", "2025-06-08", "2025-06-10"],
    "haystack_sessions": [
        [
            {"role": "user", "content": "Help me set up Redis caching"},
            {"role": "assistant", "content": "Sure, here's how to configure Redis..."},
        ],
        [
            {"role": "user", "content": "What's the best CI tool?"},
            {"role": "assistant", "content": "GitHub Actions is popular..."},
        ],
        [
            {"role": "user", "content": "I love PostgreSQL for everything"},
            {"role": "assistant", "content": "PostgreSQL is a great choice..."},
        ],
    ],
}


class TestLoadDataset:
    def test_load_valid_file(self, tmp_path):
        from benchmarks.dataset import load_dataset
        path = tmp_path / "test.json"
        path.write_text(json.dumps([SAMPLE_ENTRY]))
        entries = load_dataset(str(path))
        assert len(entries) == 1
        assert entries[0]["question_id"] == "q001"

    def test_load_with_limit(self, tmp_path):
        from benchmarks.dataset import load_dataset
        data = [SAMPLE_ENTRY, {**SAMPLE_ENTRY, "question_id": "q002"}]
        path = tmp_path / "test.json"
        path.write_text(json.dumps(data))
        entries = load_dataset(str(path), limit=1)
        assert len(entries) == 1

    def test_missing_file_raises(self):
        from benchmarks.dataset import load_dataset
        with pytest.raises(FileNotFoundError):
            load_dataset("/nonexistent/file.json")

    def test_validates_required_fields(self, tmp_path):
        from benchmarks.dataset import load_dataset
        bad = {"question_id": "q001"}
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([bad]))
        with pytest.raises(ValueError, match="missing required"):
            load_dataset(str(path))


class TestBuildCorpus:
    def test_session_granularity(self):
        from benchmarks.dataset import build_session_corpus
        corpus = build_session_corpus(SAMPLE_ENTRY)
        assert len(corpus) == 3
        assert corpus[0]["session_id"] == "sess_001"
        assert "Redis" in corpus[0]["text"]
        assert corpus[0]["date"] == "2025-06-01"

    def test_user_turns_only(self):
        from benchmarks.dataset import build_session_corpus
        corpus = build_session_corpus(SAMPLE_ENTRY)
        assert "Help me set up Redis" in corpus[0]["text"]

    def test_all_turns_mode(self):
        from benchmarks.dataset import build_session_corpus
        corpus = build_session_corpus(SAMPLE_ENTRY, include_assistant=True)
        assert "configure Redis" in corpus[0]["text"]

    def test_ground_truth_extraction(self):
        from benchmarks.dataset import get_ground_truth
        gt = get_ground_truth(SAMPLE_ENTRY)
        assert gt == {"sess_003"}
