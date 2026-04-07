import pytest


class TestDCG:
    def test_perfect_ranking(self):
        from benchmarks.metrics import dcg
        relevances = [1.0, 1.0, 1.0, 0.0, 0.0]
        score = dcg(relevances, k=5)
        assert score == pytest.approx(2.1309, rel=1e-3)

    def test_empty(self):
        from benchmarks.metrics import dcg
        assert dcg([], k=5) == 0.0

    def test_no_relevant(self):
        from benchmarks.metrics import dcg
        assert dcg([0.0, 0.0, 0.0], k=3) == 0.0


class TestNDCG:
    def test_perfect_ranking(self):
        from benchmarks.metrics import ndcg_at_k
        retrieved = ["a", "b", "c", "d"]
        ground_truth = {"a", "b"}
        score = ndcg_at_k(retrieved, ground_truth, k=4)
        assert score == 1.0

    def test_inverted_ranking(self):
        from benchmarks.metrics import ndcg_at_k
        retrieved = ["x", "y", "a", "b"]
        ground_truth = {"a", "b"}
        score = ndcg_at_k(retrieved, ground_truth, k=4)
        assert 0.0 < score < 1.0

    def test_no_hits(self):
        from benchmarks.metrics import ndcg_at_k
        retrieved = ["x", "y", "z"]
        ground_truth = {"a", "b"}
        assert ndcg_at_k(retrieved, ground_truth, k=3) == 0.0

    def test_empty_ground_truth(self):
        from benchmarks.metrics import ndcg_at_k
        assert ndcg_at_k(["a", "b"], set(), k=2) == 0.0


class TestRecallAtK:
    def test_full_recall(self):
        from benchmarks.metrics import recall_at_k
        retrieved = ["a", "b", "c"]
        ground_truth = {"a", "b"}
        assert recall_at_k(retrieved, ground_truth, k=3) == 1.0

    def test_partial_recall(self):
        from benchmarks.metrics import recall_at_k
        retrieved = ["a", "x", "y"]
        ground_truth = {"a", "b"}
        assert recall_at_k(retrieved, ground_truth, k=3) == 0.5

    def test_zero_recall(self):
        from benchmarks.metrics import recall_at_k
        retrieved = ["x", "y", "z"]
        ground_truth = {"a", "b"}
        assert recall_at_k(retrieved, ground_truth, k=3) == 0.0

    def test_k_truncation(self):
        from benchmarks.metrics import recall_at_k
        retrieved = ["x", "y", "z", "w", "v", "a"]
        ground_truth = {"a"}
        assert recall_at_k(retrieved, ground_truth, k=5) == 0.0
        assert recall_at_k(retrieved, ground_truth, k=6) == 1.0


class TestRecallAny:
    def test_at_least_one_hit(self):
        from benchmarks.metrics import recall_any_at_k
        retrieved = ["x", "a", "y"]
        ground_truth = {"a", "b"}
        assert recall_any_at_k(retrieved, ground_truth, k=3) == 1.0

    def test_no_hit(self):
        from benchmarks.metrics import recall_any_at_k
        retrieved = ["x", "y", "z"]
        ground_truth = {"a", "b"}
        assert recall_any_at_k(retrieved, ground_truth, k=3) == 0.0


class TestAggregateResults:
    def test_aggregate_by_type(self):
        from benchmarks.metrics import aggregate_by_type
        results = [
            {"question_type": "single-session-user", "recall_at_5": 1.0},
            {"question_type": "single-session-user", "recall_at_5": 0.0},
            {"question_type": "temporal-reasoning", "recall_at_5": 1.0},
        ]
        agg = aggregate_by_type(results, metric="recall_at_5")
        assert agg["single-session-user"] == pytest.approx(0.5)
        assert agg["temporal-reasoning"] == pytest.approx(1.0)
