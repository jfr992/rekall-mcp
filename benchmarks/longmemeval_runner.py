"""
LongMemEval Benchmark Runner for Rekall MCP
=============================================

Evaluates Rekall's retrieval pipeline against the LongMemEval benchmark.
Compares three modes: dense-only (baseline), hybrid (BM25+dense), hybrid+graph.

Usage:
    python -m benchmarks.longmemeval_runner benchmarks/data/longmemeval_s_cleaned.json
    python -m benchmarks.longmemeval_runner benchmarks/data/longmemeval_s_cleaned.json --mode hybrid
    python -m benchmarks.longmemeval_runner benchmarks/data/longmemeval_s_cleaned.json --mode hybrid_graph
    python -m benchmarks.longmemeval_runner benchmarks/data/longmemeval_s_cleaned.json --limit 20
    python -m benchmarks.longmemeval_runner benchmarks/data/longmemeval_s_cleaned.json --mode all
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from benchmarks.dataset import dataset_stats, get_ground_truth, load_dataset
from benchmarks.metrics import print_results, score_question
from benchmarks.modes import retrieve_dense, retrieve_hybrid, retrieve_hybrid_graph

MODE_FUNCTIONS = {
    "dense": retrieve_dense,
    "hybrid": retrieve_hybrid,
    "hybrid_graph": retrieve_hybrid_graph,
}


def run_single_mode(
    data: list[dict],
    mode: str,
    qdrant_url: str,
    n_results: int,
    include_assistant: bool,
    out_dir: Path | None,
) -> list[dict]:
    """Run one benchmark mode across all questions."""
    retrieve_fn = MODE_FUNCTIONS[mode]
    results = []
    total = len(data)

    print(f"\n  Running mode: {mode}")
    print(f"  Questions: {total}")
    print(f"  Qdrant: {qdrant_url}")
    print(f"  n_results: {n_results}")
    print()

    start_time = time.time()
    errors = 0

    for i, entry in enumerate(data):
        q_start = time.time()
        try:
            ranked_ids = retrieve_fn(
                entry,
                qdrant_url=qdrant_url,
                n_results=n_results,
                include_assistant=include_assistant,
            )
            ground_truth = get_ground_truth(entry)
            scores = score_question(ranked_ids, ground_truth)

            result = {
                "question_id": entry["question_id"],
                "question_type": entry["question_type"],
                "question": entry["question"],
                "mode": mode,
                "retrieved_ids": ranked_ids[:10],
                "ground_truth_ids": list(ground_truth),
                "duration_ms": round((time.time() - q_start) * 1000),
                **scores,
            }
            results.append(result)

        except Exception as e:
            errors += 1
            results.append(
                {
                    "question_id": entry["question_id"],
                    "question_type": entry["question_type"],
                    "question": entry["question"],
                    "mode": mode,
                    "error": str(e),
                    "recall_any_at_5": 0.0,
                    "recall_at_5": 0.0,
                    "ndcg_at_5": 0.0,
                    "recall_any_at_10": 0.0,
                    "recall_at_10": 0.0,
                    "ndcg_at_10": 0.0,
                    "duration_ms": round((time.time() - q_start) * 1000),
                }
            )

        elapsed = time.time() - start_time
        rate = (i + 1) / elapsed if elapsed > 0 else 0
        eta = (total - i - 1) / rate if rate > 0 else 0
        r5 = results[-1].get("recall_any_at_5", 0)
        running_r5 = sum(r.get("recall_any_at_5", 0) for r in results) / len(results)
        status = "OK" if "error" not in results[-1] else "ERR"
        print(
            f"  [{i + 1:>3}/{total}] {status} R@5={r5:.0f} "
            f"running={running_r5 * 100:.1f}% "
            f"({rate:.1f} q/s, ETA {eta:.0f}s)",
            end="\r",
        )

    print()
    total_time = time.time() - start_time
    print(f"  Completed in {total_time:.1f}s ({errors} errors)")

    valid = [r for r in results if "error" not in r]
    if valid:
        print_results(valid, mode)

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"longmemeval_{mode}_{ts}.jsonl"
        with open(out_path, "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
        print(f"  Results saved to: {out_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run LongMemEval benchmark against Rekall MCP retrieval pipeline.",
    )
    parser.add_argument("data_file", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument(
        "--mode",
        choices=["dense", "hybrid", "hybrid_graph", "all"],
        default="dense",
        help="Retrieval mode (default: dense)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max questions (0=all)")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N questions")
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6334",
        help="Qdrant URL (default: test instance on 6334)",
    )
    parser.add_argument("--n-results", type=int, default=50, help="Top-N retrieval")
    parser.add_argument(
        "--include-assistant",
        action="store_true",
        help="Include assistant turns in corpus (default: user-only)",
    )
    parser.add_argument(
        "--out-dir",
        default="benchmarks/results",
        help="Output directory for JSONL results",
    )
    args = parser.parse_args()

    print(f"\n  Loading dataset: {args.data_file}")
    data = load_dataset(args.data_file, limit=args.limit, skip=args.skip)
    stats = dataset_stats(data)
    print(f"  {stats['total_questions']} questions loaded")
    print(f"  Types: {stats['question_types']}")
    print(f"  Avg sessions/question: {stats['avg_sessions_per_question']:.0f}")

    modes = list(MODE_FUNCTIONS.keys()) if args.mode == "all" else [args.mode]
    all_results = {}

    for mode in modes:
        results = run_single_mode(
            data=data,
            mode=mode,
            qdrant_url=args.qdrant_url,
            n_results=args.n_results,
            include_assistant=args.include_assistant,
            out_dir=Path(args.out_dir),
        )
        all_results[mode] = results

    if len(all_results) > 1:
        print(f"\n{'=' * 70}")
        print("  COMPARISON")
        print(f"{'=' * 70}")
        print(f"\n  {'Mode':<20} {'R@5 (any)':>10} {'R@5':>10} {'R@10':>10} {'NDCG@5':>10}")
        print(f"  {'-' * 60}")
        for mode, results in all_results.items():
            valid = [r for r in results if "error" not in r]
            if not valid:
                continue
            r5_any = sum(r["recall_any_at_5"] for r in valid) / len(valid)
            r5 = sum(r["recall_at_5"] for r in valid) / len(valid)
            r10 = sum(r["recall_at_10"] for r in valid) / len(valid)
            n5 = sum(r["ndcg_at_5"] for r in valid) / len(valid)
            print(
                f"  {mode:<20} {r5_any * 100:>9.1f}% {r5 * 100:>9.1f}% "
                f"{r10 * 100:>9.1f}% {n5 * 100:>9.1f}%"
            )
        print(f"  {'MemPalace (raw)':<20} {'96.6%':>10} {'—':>10} {'—':>10} {'—':>10}")
        print()


if __name__ == "__main__":
    main()
