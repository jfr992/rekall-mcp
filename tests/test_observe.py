from memory.observe import ObservationEngine


def test_observation_engine_rejects_low_signal_noise():
    engine = ObservationEngine()
    candidate = engine.evaluate("working on auth bug maybe")

    assert candidate.should_save is False
    assert candidate.reason == "low-signal"


def test_observation_engine_detects_decision_and_salience():
    engine = ObservationEngine()
    candidate = engine.evaluate("Decided to use PostgreSQL because connection pooling and JSON support matter")

    assert candidate.memory_type == "decision"
    assert candidate.should_save is True
    assert candidate.salience >= 0.45


def test_observation_engine_detects_preference():
    engine = ObservationEngine()
    candidate = engine.evaluate("JR prefers short direct answers by default")

    assert candidate.memory_type == "preference"
    assert candidate.should_save is True
