from memory.pressure import identify_pressure, render_pressure_report


def test_identify_pressure_finds_low_value_and_stale_working():
    memories = [
        {
            "memory_id": "a",
            "tier": "working",
            "retention_days": 14,
            "salience": 0.2,
            "date": "2026-03-01",
            "content": "opened file x",
            "type": "note",
        },
        {
            "memory_id": "b",
            "tier": "semantic",
            "retention_days": 365,
            "salience": 0.9,
            "date": "2026-04-10",
            "content": "Use PostgreSQL",
            "type": "decision",
        },
    ]

    pressure = identify_pressure(memories, today="2026-04-10")
    assert pressure["low_value_count"] == 1
    assert pressure["stale_working_count"] == 1
    assert len(pressure["candidates"]) == 1


def test_render_pressure_report_has_header():
    report = render_pressure_report(
        {"low_value_count": 1, "stale_working_count": 1, "candidates": []}
    )
    assert "Memory Pressure Report" in report
