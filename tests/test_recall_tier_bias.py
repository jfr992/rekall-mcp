"""Fix I1 — Tier must actually influence recall ranking, not be a rounding error.

This test validates the *formula* (final_score composition) independently of the
manager state, so it stays a fast unit test. The end-to-end integration check
with a real Qdrant lives in test_integration_memory_os.py.
"""

from __future__ import annotations

import pytest


def _score(
    *,
    vector_score: float,
    tier: str,
    importance: float = 0.5,
    is_expanded: bool = False,
    days_old: int = 0,
) -> float:
    """Replicate the scoring block from manager.recall() for a single result."""
    graph_proximity = 0.7 if is_expanded else 1.0
    recency = max(0.0, 1.0 - days_old / 365)
    tier_norm = {"identity": 1.0, "semantic": 0.66, "episodic": 0.33, "working": 0.0}[tier]
    return (
        vector_score * 0.40
        + importance * 0.20
        + recency * 0.10
        + graph_proximity * 0.15
        + tier_norm * 0.15
    )


def test_semantic_beats_working_with_identical_vector_score():
    working = _score(vector_score=0.80, tier="working")
    semantic = _score(vector_score=0.80, tier="semantic")
    # 0.66 * 0.15 = 0.099 — meaningful, not a rounding error
    assert semantic - working >= 0.09


def test_identity_beats_semantic_noticeably():
    semantic = _score(vector_score=0.80, tier="semantic")
    identity = _score(vector_score=0.80, tier="identity")
    # (1.0 - 0.66) * 0.15 = 0.051
    assert identity - semantic >= 0.05


def test_tier_contribution_is_bounded_at_point_15():
    working = _score(vector_score=0.80, tier="working")
    identity = _score(vector_score=0.80, tier="identity")
    # Max tier delta is 1.0 * 0.15 = 0.15
    assert identity - working == pytest.approx(0.15)


def test_old_rounding_error_is_gone():
    """Before fix: tier_bonus * 0.10 gave identity a max of 0.015 — rounding noise.
    After fix: tier_norm * 0.15 gives identity a max of 0.15 — meaningful."""
    working = _score(vector_score=0.80, tier="working")
    identity = _score(vector_score=0.80, tier="identity")
    # Must be an order of magnitude above the old max
    assert identity - working > 0.10
