from memory.lifecycle import (
    compute_retention_days,
    determine_tier,
    promote_memory,
    summarize_lifecycle,
)


def test_determine_tier_preference_becomes_identity():
    assert determine_tier("preference", "JR prefers direct answers", 0.6) == "identity"


def test_determine_tier_high_salience_learning_becomes_semantic():
    assert determine_tier("learning", "Critical root cause discovered", 0.9) == "semantic"


def test_promote_working_to_episodic_for_learning():
    assert promote_memory("working", "learning", access_count=3, salience=0.5) == "episodic"


def test_promote_preference_to_identity():
    assert promote_memory("episodic", "preference", access_count=2, salience=0.4) == "identity"


def test_compute_retention_identity_longest():
    assert compute_retention_days("preference", "identity") > compute_retention_days("note", "working")


def test_summarize_lifecycle_returns_tier_and_retention():
    result = summarize_lifecycle({"type": "learning", "salience": 0.8, "access_count": 4})
    assert "tier" in result
    assert "retention_days" in result
