"""Stats for the effectiveness eval: CIs, paired tests, FDR, reliability.

Pure stdlib. Resampling unit for the bootstrap is ITEMS — asserted in code,
because a run-level bootstrap is anti-conservative by sqrt(repeats).
"""

from __future__ import annotations

import math
import random


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from discordant counts. repeats=1 only."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_bootstrap_ci(
    item_diffs: list[float],
    b: int = 10_000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile CI on the mean of per-item diffs. Resamples ITEMS."""
    n = len(item_diffs)
    if n == 0:
        raise ValueError("item_diffs must be non-empty")
    rng = random.Random(seed)
    means = []
    for _ in range(b):
        idx = [rng.randrange(n) for _ in range(n)]  # unit = items, by construction
        means.append(sum(item_diffs[i] for i in idx) / n)
    means.sort()
    lo_i = int((alpha / 2) * b)
    hi_i = min(b - 1, int((1 - alpha / 2) * b))
    return (means[lo_i], means[hi_i])


def benjamini_hochberg(pvals: list[float], q: float = 0.10) -> list[bool]:
    """FDR control. Returns per-hypothesis keep-flags in input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    thresh_rank = 0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= q * rank / m:
            thresh_rank = rank
    flags = [False] * m
    for rank, i in enumerate(order, start=1):
        flags[i] = rank <= thresh_rank
    return flags


def run_to_run_unreliable(acc1: float, acc2: float, target_delta: float) -> bool:
    """True when run-to-run SD estimate exceeds target_delta/4 (spec gate)."""
    sd = abs(acc1 - acc2) / math.sqrt(2)
    return sd > target_delta / 4
