"""precision@K — the retrieval-noise metric (field runs at 0.05-0.08)."""

from benchmarks.metrics import precision_at_k


def test_precision_counts_relevant_fraction_of_k():
    retrieved = ["s1", "s2", "s3", "s4", "s5", "s6"]
    gold = {"s2", "s5", "s6"}  # s6 outside top-5
    assert precision_at_k(retrieved, gold, 5) == 2 / 5


def test_precision_empty_or_zero_k_is_zero():
    assert precision_at_k([], {"s1"}, 5) == 0.0
    assert precision_at_k(["s1"], {"s1"}, 0) == 0.0
