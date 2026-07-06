"""Guard: the frozen LME dev subset must have exactly 200 ids.

Proportional-rounding across strata can produce 199 without a top-up step.
This test fails on the original 199-item file and passes after the generator
is fixed to top up deterministically.
"""

import json
from pathlib import Path

FROZEN = Path("benchmarks/eval/probes/lme_dev_subset.frozen.json")


def test_frozen_subset_has_exactly_200_ids():
    ids = json.loads(FROZEN.read_text())
    assert len(ids) == 200, (
        f"expected 200 ids, got {len(ids)} — run scripts/gen_lme_dev_subset.py to regenerate"
    )
    assert len(set(ids)) == len(ids), "duplicate ids in frozen subset"
    assert ids == sorted(ids), "frozen subset must be sorted"
