"""Probe corpus schema guard — every probe must be runnable and memory-dependent."""

import json
import re
from pathlib import Path

CORPUS = Path("benchmarks/eval/probes/core.frozen.json")


def test_corpus_schema_and_size():
    probes = json.loads(CORPUS.read_text())
    assert 15 <= len(probes) <= 20
    ids = set()
    for p in probes:
        assert set(p) == {"id", "question", "question_type", "seed_memories", "oracle_regex"}
        assert p["id"] not in ids
        ids.add(p["id"])
        assert p["question_type"] in {
            "exact-recall",
            "preference",
            "temporal",
            "knowledge-update",
            "cross-project",
        }
        assert 1 <= len(p["seed_memories"]) <= 4
        for m in p["seed_memories"]:
            assert set(m) == {"summary", "type"}
            assert m["type"] in {"decision", "learning", "preference", "requirement", "fact"}
        re.compile(p["oracle_regex"])  # must be a valid regex
        # gate-①: the oracle must be satisfiable by at least one seed memory
        assert any(
            re.search(p["oracle_regex"], m["summary"], re.IGNORECASE) for m in p["seed_memories"]
        )
