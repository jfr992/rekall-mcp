"""Tests for the behavioral lifecycle classifier."""
from __future__ import annotations

from memory.lifecycle import LifecycleSignals, classify


def _signals(**overrides):
    defaults = {
        "memory_type": "note",
        "salience": 0.0,
        "age_days": 0,
        "reinforcement_count": 0,
        "contradicts_count": 0,
        "explicit_tier": None,
    }
    defaults.update(overrides)
    return LifecycleSignals(**defaults)


def test_explicit_identity_is_sacred_even_with_contradictions():
    result = classify(_signals(
        memory_type="note",
        contradicts_count=99,
        explicit_tier="identity",
    ))
    assert result.tier == "identity"


def test_contradictions_demote_one_tier():
    # decision + high salience would normally be semantic;
    # 3 contradicts demote it to episodic
    result = classify(_signals(
        memory_type="decision",
        salience=0.9,
        age_days=30,
        reinforcement_count=3,
        contradicts_count=3,
    ))
    assert result.tier == "episodic"


def test_reinforcement_promotes_stale_note_to_semantic():
    result = classify(_signals(
        memory_type="note",
        salience=0.3,
        age_days=10,
        reinforcement_count=6,
    ))
    assert result.tier == "semantic"


def test_young_unreinforced_note_stays_working():
    result = classify(_signals(
        memory_type="note",
        salience=0.3,
        age_days=1,
        reinforcement_count=1,
    ))
    assert result.tier == "working"


def test_high_salience_decision_is_semantic():
    result = classify(_signals(memory_type="decision", salience=0.75))
    assert result.tier == "semantic"


def test_preference_defaults_to_semantic_not_identity():
    result = classify(_signals(memory_type="preference", salience=0.5))
    assert result.tier == "semantic"


def test_session_is_episodic():
    result = classify(_signals(memory_type="session"))
    assert result.tier == "episodic"


def test_durability_monotonic_with_reinforcement():
    base = classify(_signals(memory_type="note", salience=0.3, age_days=10))
    more = classify(_signals(memory_type="note", salience=0.3, age_days=10, reinforcement_count=5))
    assert more.durability > base.durability


def test_lifecycle_reason_is_human_readable():
    result = classify(_signals(
        memory_type="note",
        salience=0.3,
        age_days=10,
        reinforcement_count=6,
    ))
    assert result.reason
    assert "reinforce" in result.reason.lower() or "promoted" in result.reason.lower()


def test_summarize_lifecycle_honors_identity_but_not_other_persisted_tiers():
    from memory.lifecycle import summarize_lifecycle

    # identity persists — explicit_tier="identity" flows through classify unchanged
    out = summarize_lifecycle({"type": "preference", "tier": "identity", "salience": 0.3})
    assert out["tier"] == "identity"

    # non-identity persisted tier is recomputed fresh from signals
    out = summarize_lifecycle({"type": "note", "tier": "semantic", "salience": 0.3})
    # Fresh compute: note type, no reinforcement, age=0 -> working
    assert out["tier"] == "working"
