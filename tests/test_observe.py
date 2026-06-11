from memory.observe import ObservationEngine


def test_observation_engine_rejects_low_signal_noise():
    engine = ObservationEngine()
    candidate = engine.evaluate("working on auth bug")  # "working on" phrase

    assert candidate.should_save is False
    assert candidate.reason == "low-signal"


def test_trying_to_migrate_is_not_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "User is trying to migrate from Postgres to Yugabyte due to latency issues",
        memory_type="decision",
    )
    assert candidate.should_save is True
    assert candidate.reason != "low-signal"


def test_exploring_rust_in_long_text_is_not_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "Exploring Rust for the unikernel rewrite because Zig's async story is immature",
        memory_type="learning",
    )
    assert candidate.should_save is True


def test_just_exploring_phrase_is_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate("Just exploring, nothing concrete yet", memory_type="note")
    assert candidate.should_save is False
    assert candidate.reason == "low-signal"


def test_multiple_hedges_in_short_text_is_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate("maybe probably later", memory_type="note")
    assert candidate.should_save is False
    assert candidate.reason == "low-signal"


def test_single_hedge_word_in_long_decision_is_fine():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "Decided to maybe revisit the caching layer after we ship the auth rewrite next quarter",
        memory_type="decision",
    )
    assert candidate.should_save is True


def test_observation_engine_detects_decision_and_salience():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "Decided to use PostgreSQL because connection pooling and JSON support matter"
    )

    assert candidate.memory_type == "decision"
    assert candidate.should_save is True
    assert candidate.salience >= 0.45


def test_observation_engine_detects_preference():
    engine = ObservationEngine()
    candidate = engine.evaluate("JR prefers short direct answers by default")

    assert candidate.memory_type == "preference"
    assert candidate.should_save is True


def test_phrase_inside_long_substantive_note_is_not_low_signal():
    """A noise phrase ('working on') inside a longer substantive observation
    must not get rejected — substring matching alone was dropping real memories."""
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "Fixed the auth bug we were working on; root cause was a missing await in "
        "the token refresh path that dropped the session on slow networks",
        memory_type="learning",
    )
    assert candidate.should_save is True
    assert candidate.reason != "low-signal"
