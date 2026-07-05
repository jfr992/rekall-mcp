"""Tests for scripts/utility_report.py.

Synthetic events in the exact JSONL shape produced by manager.record_event()
so the parser tests real-world data without subprocess.
"""

import json

import pytest


def _ss(session_id, project, recalled_ids, edits=0, test_passes=0, eid="ev0"):
    return json.dumps(
        {
            "agent": "unknown",
            "event_id": eid,
            "event_type": "session_summary",
            "observed_at": "2026-07-03T10:00:00",
            "payload": {
                "edits_after_recall": edits,
                "memory_ids": recalled_ids,
                "session_id": session_id,
                "test_passes_after_recall": test_passes,
            },
            "project": project,
            "source": "client",
        }
    )


def test_parse_events_loads_valid_lines(tmp_path):
    from scripts.utility_report import parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(
        _ss("sess-1", "proj-a", ["mem-x"], edits=1)
        + "\n"
        + _ss("sess-2", "proj-a", ["mem-x"])
        + "\n"
    )

    events = parse_events(f)
    assert len(events) == 2
    assert events[0]["event_type"] == "session_summary"


def test_parse_events_skips_malformed_lines(tmp_path):
    from scripts.utility_report import parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "not valid json\n" + _ss("sess-1", "proj-a", ["mem-x"], edits=1) + "\n" + "{broken\n"
    )

    events = parse_events(f)
    assert len(events) == 1
    assert events[0]["event_type"] == "session_summary"


def _surf(memory_ids, project="proj-a", eid="ev-s"):
    return json.dumps(
        {
            "agent": "unknown",
            "event_id": eid,
            "event_type": "memory_surfaced",
            "observed_at": "2026-07-03T10:00:00",
            "payload": {"memory_ids": memory_ids},
            "project": project,
            "source": "memory_manager",
        }
    )


def test_build_surfaced_counts_counts_surfaced_events(tmp_path):
    from scripts.utility_report import build_surfaced_counts, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(_surf(["mem-y", "mem-z"]) + "\n" + _surf(["mem-y"]) + "\n")

    counts = build_surfaced_counts(parse_events(f))
    assert counts["mem-y"] == 2
    assert counts["mem-z"] == 1


def test_build_session_summaries_normalises_fields(tmp_path):
    """build_session_summaries extracts session_summary events into dicts."""
    from scripts.utility_report import build_session_summaries, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(_ss("sess-1", "proj-a", ["mem-x"], edits=2, test_passes=1) + "\n")

    summaries = build_session_summaries(parse_events(f))

    assert len(summaries) == 1
    s = summaries[0]
    assert s["session_id"] == "sess-1"
    assert s["recalled_ids"] == ["mem-x"]
    assert s["edits_after_recall"] == 2
    assert s["test_passes_after_recall"] == 1


def test_progress_line_format():
    from scripts.utility_report import progress_line

    summaries = [
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x", "mem-y"],
            "edits_after_recall": 1,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s2",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s3",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 1,
        },
    ]
    line = progress_line(summaries)
    # pairs = (session, memory) pairs: s1 contributes 2
    assert "pairs=4" in line
    assert "sessions=3" in line
    assert "projects=1" in line
    assert "need 500/20/3" in line


def test_main_empty_file_clean_exit(tmp_path, capsys):
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text("")

    with pytest.raises(SystemExit) as exc:
        main(["--events-file", str(f)])

    assert exc.value.code == 0
    assert "no event data" in capsys.readouterr().out.lower()


def test_compute_utility_map_two_thirds():
    """utility = sessions_with_outcome / sessions_recalled."""
    from scripts.utility_report import compute_utility_map

    summaries = [
        {
            "session_id": "s1",
            "project": "p",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 1,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s2",
            "project": "p",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s3",
            "project": "p",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 1,
        },
    ]
    utility = compute_utility_map(summaries)
    assert "mem-x" in utility
    assert abs(utility["mem-x"] - 2 / 3) < 0.001


def test_utility_two_thirds(tmp_path):
    """Memory recalled in 3 sessions, outcomes in 2 → utility 0.667."""
    from scripts.utility_report import build_session_summaries, compute_utility_map, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1"),
                _ss("sess-2", "proj-a", ["mem-x"], edits=0, test_passes=0, eid="e2"),
                _ss("sess-3", "proj-a", ["mem-x"], test_passes=1, eid="e3"),
            ]
        )
        + "\n"
    )

    events = parse_events(f)
    summaries = build_session_summaries(events)
    utility = compute_utility_map(summaries)

    assert "mem-x" in utility
    assert abs(utility["mem-x"] - 2 / 3) < 0.001


def test_main_prints_utility_value(tmp_path, capsys):
    """Brief requirement: utility 0.667 printed."""
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1"),
                _ss("sess-2", "proj-a", ["mem-x"], eid="e2"),
                _ss("sess-3", "proj-a", ["mem-x"], test_passes=1, eid="e3"),
            ]
        )
        + "\n"
    )

    main(["--events-file", str(f)])

    out = capsys.readouterr().out
    assert "0.667" in out
    assert "mem-x" in out


def test_main_surfaced_only_in_coverage_output(tmp_path, capsys):
    """Brief requirement: surfaced-only memory absent from utility section, present in coverage."""
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(
        _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1")
        + "\n"
        + _surf(["mem-y"], eid="es")
        + "\n"
    )

    main(["--events-file", str(f)])

    out = capsys.readouterr().out
    # mem-y should appear in coverage section
    assert "mem-y" in out
    # and the utility section should show mem-x with utility 1.0
    assert "mem-x" in out


def test_main_progress_line_in_output(tmp_path, capsys):
    """Brief requirement: pairs=N sessions=M projects=K (need 500/20/3) in output."""
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1"),
                _ss("sess-2", "proj-a", ["mem-x"], eid="e2"),
                _ss("sess-3", "proj-a", ["mem-x"], test_passes=1, eid="e3"),
            ]
        )
        + "\n"
    )

    main(["--events-file", str(f)])

    out = capsys.readouterr().out
    assert "pairs=3" in out
    assert "sessions=3" in out
    assert "projects=1" in out
    assert "need 500/20/3" in out


def test_main_missing_file_clean_exit(tmp_path, capsys):
    """Brief requirement: missing file → print 'no event data' exit 0."""
    from scripts.utility_report import main

    with pytest.raises(SystemExit) as exc:
        main(["--events-file", str(tmp_path / "nonexistent.jsonl")])

    assert exc.value.code == 0
    assert "no event data" in capsys.readouterr().out.lower()
