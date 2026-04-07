"""Retrieval evaluation metrics: Recall@K, NDCG@K, aggregation."""

from __future__ import annotations

import math
from collections import defaultdict


def dcg(relevances: list[float], k: int) -> float:
    """Discounted Cumulative Gain at rank k."""
    score = 0.0
    for i, rel in enumerate(relevances[:k]):
        score += rel / math.log2(i + 2)
    return score


def ndcg_at_k(retrieved: list[str], ground_truth: set[str], k: int) -> float:
    """Normalized DCG at rank k."""
    if not ground_truth:
        return 0.0
    relevances = [1.0 if doc_id in ground_truth else 0.0 for doc_id in retrieved[:k]]
    ideal = sorted(relevances, reverse=True)
    idcg = dcg(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg(relevances, k) / idcg


def recall_at_k(retrieved: list[str], ground_truth: set[str], k: int) -> float:
    """Fraction of ground-truth documents found in top-k results."""
    if not ground_truth:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & ground_truth) / len(ground_truth)


def recall_any_at_k(retrieved: list[str], ground_truth: set[str], k: int) -> float:
    """Binary: 1.0 if ANY ground-truth doc appears in top-k, else 0.0."""
    if not ground_truth:
        return 0.0
    top_k = set(retrieved[:k])
    return 1.0 if top_k & ground_truth else 0.0


def score_question(
    retrieved_ids: list[str],
    ground_truth_ids: set[str],
    ks: tuple[int, ...] = (5, 10),
) -> dict[str, float]:
    """Score a single question across all metrics and k values."""
    result = {}
    for k in ks:
        result[f"recall_at_{k}"] = recall_at_k(retrieved_ids, ground_truth_ids, k)
        result[f"recall_any_at_{k}"] = recall_any_at_k(retrieved_ids, ground_truth_ids, k)
        result[f"ndcg_at_{k}"] = ndcg_at_k(retrieved_ids, ground_truth_ids, k)
    return result


def aggregate_by_type(
    results: list[dict],
    metric: str,
) -> dict[str, float]:
    """Average a metric grouped by question_type."""
    groups: dict[str, list[float]] = defaultdict(list)
    for r in results:
        groups[r["question_type"]].append(r[metric])
    return {qtype: sum(vals) / len(vals) for qtype, vals in sorted(groups.items())}


def print_results(results: list[dict], mode: str) -> None:
    """Print formatted results table to console."""
    n = len(results)
    metrics = ["recall_any_at_5", "recall_at_5", "ndcg_at_5", "recall_any_at_10", "recall_at_10", "ndcg_at_10"]

    print(f"\n{'=' * 70}")
    print(f"  Mode: {mode}  |  Questions: {n}")
    print(f"{'=' * 70}")

    print(f"\n  {'Metric':<20} {'Score':>10}")
    print(f"  {'-' * 30}")
    for m in metrics:
        vals = [r[m] for r in results]
        avg = sum(vals) / len(vals) if vals else 0.0
        pct = f"{avg * 100:.1f}%"
        print(f"  {m:<20} {pct:>10}")

    print(f"\n  Per-type Recall@5 (any):")
    print(f"  {'-' * 40}")
    by_type = aggregate_by_type(results, "recall_any_at_5")
    for qtype, score in by_type.items():
        pct = f"{score * 100:.1f}%"
        count = sum(1 for r in results if r["question_type"] == qtype)
        print(f"  {qtype:<30} {pct:>6}  (n={count})")
    print()
