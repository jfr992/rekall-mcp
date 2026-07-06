#!/usr/bin/env python3
"""Generate the frozen stratified 200-item LME dev subset (list of question_ids).

Usage:
    uv run python scripts/gen_lme_dev_subset.py

Input:  benchmarks/data/longmemeval_s_cleaned.json  (264 MB, gitignored)
Output: benchmarks/eval/probes/lme_dev_subset.frozen.json  (~2 KB, committed)

The output is a JSON list of question_id strings — the reproducibility anchor.
Use with: uv run python -m benchmarks.eval.runner --subset benchmarks/eval/probes/lme_dev_subset.frozen.json
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from benchmarks.dataset import load_dataset

SRC = Path(__file__).parent.parent / "benchmarks" / "data" / "longmemeval_s_cleaned.json"
OUT = Path(__file__).parent.parent / "benchmarks" / "eval" / "probes" / "lme_dev_subset.frozen.json"

if not SRC.exists():
    raise SystemExit(f"Dataset not found: {SRC}\nRun: bash benchmarks/download_data.sh")

data = load_dataset(str(SRC))
by_type: dict[str, list[str]] = defaultdict(list)
for e in data:
    by_type[e["question_type"]].append(e["question_id"])

rng = random.Random(42)
subset: list[str] = []
total = sum(len(v) for v in by_type.values())
for t, ids in sorted(by_type.items()):
    k = max(1, round(200 * len(ids) / total))
    subset += rng.sample(sorted(ids), min(k, len(ids)))

# Proportional rounding can land on 199; top up deterministically from the largest strata.
if len(subset) < 200:
    used = set(subset)
    overflow: list[str] = []
    for _, ids in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        overflow.extend(i for i in sorted(ids) if i not in used)
    needed = 200 - len(subset)
    subset += random.Random(42).sample(overflow, min(needed, len(overflow)))

result = sorted(subset[:200])
assert len(result) == 200, f"expected 200 ids, got {len(result)}"
json.dump(result, OUT.open("w"), indent=0)
print(f"{len(result)} ids -> {OUT}  ({OUT.stat().st_size} bytes)")
