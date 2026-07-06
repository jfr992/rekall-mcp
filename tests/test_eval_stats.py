"""Stats for the effectiveness eval: CIs, paired tests, FDR, reliability."""

import pytest
from benchmarks.eval.stats import wilson_ci


def test_wilson_ci_known_value():
    # 8/10 successes, z=1.96 -> (0.4902, 0.9433) (textbook value)
    lo, hi = wilson_ci(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3)
    assert hi == pytest.approx(0.9433, abs=1e-3)


def test_mcnemar_exact_symmetric_is_one():
    from benchmarks.eval.stats import mcnemar_exact

    assert mcnemar_exact(5, 5) == pytest.approx(1.0, abs=1e-9)


def test_mcnemar_exact_skewed_is_small():
    from benchmarks.eval.stats import mcnemar_exact

    # 15 vs 1 discordant: p = 2 * P(X <= 1 | n=16, p=.5) = 2*(17/65536)
    assert mcnemar_exact(15, 1) == pytest.approx(2 * 17 / 65536, rel=1e-6)


def test_paired_bootstrap_ci_covers_true_delta_and_excludes_zero():
    from benchmarks.eval.stats import paired_bootstrap_ci

    # 200 items, true mean diff 0.10, +/-0.30 spread
    rng = __import__("random").Random(7)
    diffs = [0.10 + rng.choice([-0.3, 0.0, 0.3]) for _ in range(200)]
    lo, hi = paired_bootstrap_ci(diffs, b=2000, seed=1)
    assert lo < 0.10 < hi
    assert lo > 0.0  # detectable at n=200


def test_paired_bootstrap_rejects_empty():
    from benchmarks.eval.stats import paired_bootstrap_ci

    with pytest.raises(ValueError):
        paired_bootstrap_ci([])


def test_benjamini_hochberg_classic():
    from benchmarks.eval.stats import benjamini_hochberg

    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    flags = benjamini_hochberg(pvals, q=0.05)
    assert flags == [True, True, False, False, False, False, False, False]


def test_run_to_run_unreliable_gate():
    from benchmarks.eval.stats import run_to_run_unreliable

    assert run_to_run_unreliable(0.70, 0.60, target_delta=0.10) is True
    assert run_to_run_unreliable(0.70, 0.69, target_delta=0.10) is False
