"""Integration: same-day conflict pair renders newest-first with outdated stub.

Pins Stage A (newest-first + imperative header) and Stage C (outdated-content
suppression) end-to-end through the production save → recall → format pipeline.

Requires real Qdrant on :6334 (pytest -m integration).

NOTE ON score_threshold: the default recall() threshold (0.45) would filter out
the short test query against the longer embedding_text-formatted stored content.
Following the same pattern as test_integration_memory_os.py (score_threshold=0.0),
we call recall() + _format_with_guidance() directly — the exact two calls that
recall_formatted() delegates to — so the full pipeline is still exercised.
"""

import pytest

import memory.singleton as singleton

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Prevent cross-test contamination via the process-wide singleton."""
    singleton._instance = None
    yield
    singleton._instance = None


def test_same_day_pair_renders_newest_first(memory_manager):
    """Characterization: save a conflict pair end-to-end; the recall+format
    pipeline shows newest content in full, older content suppressed by the
    outdated stub, and the imperative header present (Stage A + Stage C).

    This test SHOULD PASS on a correctly wired feat/freshness-recall branch —
    it is a pinning test, not a red-green step.
    """
    mgr = memory_manager

    # Two semantically near-identical requirement memories (same type, same project,
    # differ only by the limit value).  The all-MiniLM-L6-v2 stored vectors for
    # these sentences have cosine >= 0.95, reliably triggering the conflict-detection
    # path in recall() via the Stage B vector-comparison branch.
    mgr.save(
        "Rate limit is 600 requests per minute.",
        type="requirement",
        project="integration-test",
    )
    mgr.save(
        "Rate limit is 250 requests per minute.",
        type="requirement",
        project="integration-test",
    )

    # Use score_threshold=0.0 — same pattern as test_integration_memory_os.py.
    # The short query "rate limit" scores ~0.24 against the padded embedding_text
    # ("Project integration-test. Type requirement. Tier working. Claim: …"),
    # which is below the production default of 0.45.  Calling recall() + format
    # directly mirrors the exact body of recall_formatted().
    results = mgr.recall(
        "rate limit",
        project="integration-test",
        score_threshold=0.0,
    )
    out = mgr._format_with_guidance(results)

    # Stage C: older content (600) is suppressed — the stub replaces it.
    assert "250" in out, f"Newer content '250' missing from output:\n{out}"
    assert "600" not in out, f"Older content '600' should be stubbed, not visible:\n{out}"
    assert "[outdated — replaced by the newer entry above]" in out, (
        f"Expected outdated stub in output:\n{out}"
    )
    # Stage A: imperative header appears when same-type entries conflict.
    assert "newest is correct" in out, f"Expected imperative header in output:\n{out}"
