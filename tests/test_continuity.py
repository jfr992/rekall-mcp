from memory.continuity import extract_next_steps, format_handoff_summary


def test_extract_next_steps_prefers_actionable_memories():
    memories = [
        {"content": "TODO: finish the Codex adapter", "importance": 0.5, "type": "learning"},
        {"content": "User prefers concise answers", "importance": 0.7, "type": "preference"},
    ]

    steps = extract_next_steps(memories)
    assert steps
    assert "TODO" in steps[0]


def test_format_handoff_summary_contains_sections():
    summary = format_handoff_summary(
        recent=[{"date": "2026-04-10", "content": "Built resume packet"}],
        important=[{"tier": "semantic", "type": "decision", "content": "Use scope-aware identity"}],
        next_steps=["Add Codex adapter"],
    )

    assert "Handoff Summary" in summary
    assert "Likely next steps" in summary
