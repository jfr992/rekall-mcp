# Memento MCP — LongMemEval Benchmark

Reproducible evaluation of Memento MCP's retrieval pipeline against the
[LongMemEval](https://github.com/xiaowu0162/LongMemEval) benchmark
(500 questions, 6 question types, ~40 sessions per question).

## Quick Start

```bash
# 1. Download dataset
bash benchmarks/download_data.sh

# 2. Start test Qdrant instance
docker compose up qdrant-test -d

# 3. Run benchmark (all modes)
PYTHONPATH=src:. .venv/bin/python -m benchmarks.longmemeval_runner \
    benchmarks/data/longmemeval_s_cleaned.json --mode all

# 4. Quick test (5 questions)
PYTHONPATH=src:. .venv/bin/python -m benchmarks.longmemeval_runner \
    benchmarks/data/longmemeval_s_cleaned.json --mode dense --limit 5
```

## Modes

| Mode | What It Tests | MemPalace Equivalent |
|------|--------------|---------------------|
| `dense` | Pure semantic search (all-MiniLM-L6-v2) | Their "raw" mode (96.6% R@5) |
| `hybrid` | BM25 sparse + dense with RRF fusion | No equivalent — Memento advantage |
| `hybrid_graph` | Hybrid + 1-hop knowledge graph expansion | No equivalent — Memento advantage |

## Results

> **Run `--mode all` and paste results here after execution.**

| Mode | R@5 (any) | R@5 | R@10 | NDCG@5 |
|------|-----------|-----|------|--------|
| `dense` | TBD | TBD | TBD | TBD |
| `hybrid` | TBD | TBD | TBD | TBD |
| `hybrid_graph` | TBD | TBD | TBD | TBD |
| **MemPalace (raw)** | **96.6%** | — | — | — |
| **MemPalace (hybrid+Haiku)** | **100%** | — | — | — |

## Metrics

- **Recall@K (any):** Did ANY ground-truth session appear in top K? (Binary, MemPalace's primary metric)
- **Recall@K:** Fraction of ground-truth sessions found in top K.
- **NDCG@K:** Normalized Discounted Cumulative Gain — rewards higher ranking of relevant results.

## Scoring Methodology

For each of 500 questions:
1. Create isolated Qdrant collection
2. Ingest all haystack sessions (~40 per question)
3. Query with the question text
4. Score retrieved session IDs against `answer_session_ids`
5. Delete collection (no cross-question contamination)

This matches MemPalace's methodology: per-question isolation, same embedder (all-MiniLM-L6-v2),
same dataset (longmemeval_s_cleaned.json), same metric (Recall@5).

## CLI Options

```
positional arguments:
  data_file             Path to longmemeval_s_cleaned.json

options:
  --mode {dense,hybrid,hybrid_graph,all}
  --limit N             Max questions (0=all, default: 0)
  --skip N              Skip first N questions (resume)
  --qdrant-url URL      Qdrant endpoint (default: http://localhost:6334)
  --n-results N         Top-N retrieval depth (default: 50)
  --include-assistant   Include assistant turns in corpus
  --out-dir DIR         JSONL output directory (default: benchmarks/results)
```

## Dataset

[LongMemEval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
(MIT license, 500 questions, 6 types: single-session-user, single-session-assistant,
single-session-preference, temporal-reasoning, knowledge-update, multi-session).
