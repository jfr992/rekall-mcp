"""Tests for scripts/reinforce_replay.py — offline dry-run report.

Full surviving event-log history -> per-memory credits-by-kind, effective
score, and would-promote verdict. THE GATE: human reviews this table
before any live write (PLAN.md T2/T7). --dry-run is the default; --apply
performs the real store write via memory.reinforce.process_events.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _event(event_type, payload, project="proj-a", event_id="e1"):
    return {
        "event_type": event_type,
        "project": project,
        "agent": "claude",
        "source": "test",
        "payload": payload,
        "event_id": event_id,
        "observed_at": "2026-07-01T12:00:00",
    }


def test_build_replay_rows_for_useful_feedback(tmp_path):
    from scripts.reinforce_replay import build_replay_rows

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            _event(
                "memory_feedback",
                {"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
                event_id="e1",
            ),
        ],
    )

    memories = {
        "m1": {"memory_id": "m1", "content": "PostgreSQL for JSON support", "tier": "working"}
    }

    rows = build_replay_rows(events_file, memories, now=datetime(2026, 7, 18, 12, 0, 0))

    assert len(rows) == 1
    assert rows[0].memory_id == "m1"
    assert rows[0].credits_by_kind["outcome"] == 1
    assert rows[0].effective == 1.0


def test_build_replay_rows_single_event_does_not_meet_promotion_gate(tmp_path):
    from scripts.reinforce_replay import build_replay_rows

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            _event(
                "memory_feedback",
                {"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
                event_id="e1",
            ),
        ],
    )

    rows = build_replay_rows(events_file, {}, now=datetime(2026, 7, 18, 12, 0, 0))

    assert rows[0].would_promote is False


def test_build_replay_rows_uses_each_events_own_date_for_the_day_spread_gate(tmp_path):
    """Two feedback events on genuinely different calendar days (per their own
    observed_at) must count as 2 distinct days for promotion_eligible — not
    collapse to "today" just because the replay's `now` is a single instant.
    """
    from scripts.reinforce_replay import build_replay_rows

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            {
                **_event(
                    "memory_feedback",
                    {"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
                    event_id="e1",
                ),
                "observed_at": "2026-06-01T10:00:00",
            },
            {
                **_event(
                    "memory_feedback",
                    {"memory_id": "m1", "verdict": "useful", "session_id": "sess-2"},
                    event_id="e2",
                ),
                "observed_at": "2026-06-05T10:00:00",
            },
        ],
    )

    rows = build_replay_rows(events_file, {}, now=datetime(2026, 7, 18, 12, 0, 0))

    assert rows[0].would_promote is True


def test_build_replay_rows_truncates_content_preview_to_80_chars(tmp_path):
    from scripts.reinforce_replay import build_replay_rows

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            _event(
                "memory_feedback",
                {"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
                event_id="e1",
            ),
        ],
    )
    memories = {"m1": {"memory_id": "m1", "content": "x" * 200}}

    rows = build_replay_rows(events_file, memories, now=datetime(2026, 7, 18, 12, 0, 0))

    assert len(rows[0].content_preview) == 80


def test_log_retention_stats_reports_count_and_span(tmp_path):
    from scripts.reinforce_replay import log_retention_stats, parse_events

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            {
                **_event("memory_feedback", {"memory_id": "m1"}, event_id="e1"),
                "observed_at": "2026-07-01T00:00:00",
            },
            {
                **_event("memory_feedback", {"memory_id": "m1"}, event_id="e2"),
                "observed_at": "2026-07-10T00:00:00",
            },
        ],
    )

    stats = log_retention_stats(parse_events(events_file))

    assert stats["count"] == 2
    assert stats["oldest"] == "2026-07-01T00:00:00"
    assert stats["newest"] == "2026-07-10T00:00:00"


def test_main_prints_table_row_for_credited_memory(tmp_path, capsys):
    from scripts.reinforce_replay import main

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            _event(
                "memory_feedback",
                {"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
                event_id="e1",
            ),
        ],
    )

    main(["--events-file", str(events_file)])

    out = capsys.readouterr().out
    assert "m1" in out


def test_main_missing_events_file_clean_exit(tmp_path, capsys):
    from scripts.reinforce_replay import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--events-file", str(tmp_path / "does_not_exist.jsonl")])

    assert exc_info.value.code == 0
    assert "no event data" in capsys.readouterr().out.lower()


def test_main_apply_flag_invokes_process_events(tmp_path):
    from unittest.mock import patch

    from scripts.reinforce_replay import main

    events_file = tmp_path / "_events.jsonl"
    _write_events(
        events_file,
        [
            _event(
                "memory_feedback",
                {"memory_id": "m1", "verdict": "useful", "session_id": "sess-1"},
                event_id="e1",
            ),
        ],
    )

    with patch("scripts.reinforce_replay.process_events") as mock_process:
        main(["--events-file", str(events_file), "--apply"])

    assert mock_process.called
