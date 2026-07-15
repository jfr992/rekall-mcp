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


def test_collapse_merges_repeated_session_summaries():
    """Two summaries sharing session_id collapse to one with union ids and max outcomes."""
    from scripts.utility_report import collapse_sessions

    summaries = [
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x", "mem-y"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 1,
        },
    ]

    result = collapse_sessions(summaries)

    assert len(result) == 1
    assert result[0]["session_id"] == "s1"
    assert result[0]["recalled_ids"] == ["mem-x", "mem-y"]
    assert result[0]["edits_after_recall"] == 0
    assert result[0]["test_passes_after_recall"] == 1


def test_progress_pairs_not_inflated_by_repeated_stop_fires():
    """Repeated Stop fires for the same session must not inflate the pairs count.

    Without collapse: sum of len(recalled_ids) = 1+2+1 = 4 (the bug).
    With collapse: distinct (session_id, memory_id) pairs = 2+1 = 3.
    """
    from scripts.utility_report import collapse_sessions, progress_line

    summaries = [
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x", "mem-y"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 1,
        },
        {
            "session_id": "s2",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
    ]

    # Demonstrate the bug: raw uncollapsed count is 4
    raw_line = progress_line(summaries)
    assert "pairs=4" in raw_line, "raw (uncollapsed) inflated count must equal 4"

    # After collapse: s1 has 2 distinct ids, s2 has 1 → 3 pairs
    collapsed_line = progress_line(collapse_sessions(summaries))
    assert "pairs=3" in collapsed_line
    assert "sessions=2" in collapsed_line


def test_utility_uses_collapsed_outcomes():
    """Outcome from any Stop fire in a session counts for the whole session.

    s1 fires twice: first with no outcome, then with test_passes=1.
    After collapse s1 has outcome; s2 has no outcome.
    mem-x appears in s1 + s2 → utility = 1/2 = 0.5.
    mem-y appears only in s1    → utility = 1/1 = 1.0.
    """
    from scripts.utility_report import collapse_sessions, compute_utility_map

    summaries = [
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
        {
            "session_id": "s1",
            "project": "proj-a",
            "recalled_ids": ["mem-x", "mem-y"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 1,
        },
        {
            "session_id": "s2",
            "project": "proj-a",
            "recalled_ids": ["mem-x"],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
    ]

    utility = compute_utility_map(collapse_sessions(summaries))

    # s1 outcome yes (test_passes=1 via second Stop fire), s2 outcome no
    assert abs(utility["mem-x"] - 0.5) < 0.001
    assert abs(utility["mem-y"] - 1.0) < 0.001


def _fb(memory_id, verdict, project="proj-a", eid="ev-f", session_id=None):
    return json.dumps(
        {
            "agent": "unknown",
            "event_id": eid,
            "event_type": "memory_feedback",
            "observed_at": "2026-07-14T10:00:00",
            "payload": {
                "verdict": verdict,
                "editor": "ui",
                "memory_ids": [memory_id],
                "session_id": session_id,
            },
            "project": project,
            "source": "feedback_endpoint",
        }
    )


def test_build_feedback_tallies_counts_verdicts_per_memory(tmp_path):
    """memory_feedback events tally into per-memory useful/wrong/stale counts."""
    from scripts.utility_report import build_feedback_tallies, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _fb("mem-x", "useful", eid="f1"),
                _fb("mem-x", "useful", eid="f2"),
                _fb("mem-x", "stale", eid="f3"),
                _fb("mem-y", "wrong", eid="f4"),
            ]
        )
        + "\n"
    )

    tallies = build_feedback_tallies(parse_events(f))

    assert tallies["mem-x"] == {"useful": 2, "wrong": 0, "stale": 1}
    assert tallies["mem-y"] == {"useful": 0, "wrong": 1, "stale": 0}


def test_main_labeled_evidence_section_separate_from_heuristic(tmp_path, capsys):
    """Feedback tallies print under 'labeled evidence', apart from the
    co-occurrence heuristic section — the two evidence classes never mix."""
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1"),
                _fb("mem-x", "useful", eid="f1"),
                _fb("mem-x", "wrong", eid="f2"),
                _fb("mem-z", "stale", eid="f3"),  # feedback-only memory
            ]
        )
        + "\n"
    )

    main(["--events-file", str(f)])

    out = capsys.readouterr().out
    lower = out.lower()
    assert "labeled evidence" in lower
    assert "heuristic co-occurrence" in lower
    # labeled section renders per-memory verdict counts, incl. feedback-only ids
    labeled = lower.split("labeled evidence")[1]
    assert "mem-z" in labeled
    assert "useful" in labeled and "wrong" in labeled and "stale" in labeled
    # the heuristic section comes first and does not contain the labeled tallies
    heuristic = lower.split("labeled evidence")[0]
    assert "mem-z" not in heuristic


def test_feedback_events_leave_exit_criterion_line_unchanged(tmp_path, capsys):
    """Feedback is labeled evidence — it must not count toward the 500-pair gate."""
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1"),
                _fb("mem-x", "useful", eid="f1"),
                _fb("mem-x", "wrong", eid="f2"),
            ]
        )
        + "\n"
    )

    main(["--events-file", str(f)])

    out = capsys.readouterr().out
    assert "pairs=1" in out
    assert "sessions=1" in out
    assert "need 500/20/3" in out


def test_default_events_path_resolves_from_memory_storage_path(tmp_path, capsys, monkeypatch):
    """No --events-file → the report reads <MEMORY_STORAGE_PATH>/_events.jsonl,
    same resolution as the manager. A hardcoded ~/.claude/memory default read
    PROD events in the live smoke."""
    from scripts.utility_report import main

    storage = tmp_path / "relocated-store"
    storage.mkdir()
    monkeypatch.setenv("MEMORY_STORAGE_PATH", str(storage))
    (storage / "_events.jsonl").write_text(
        _ss("sess-1", "proj-a", ["mem-x"], edits=1, eid="e1")
        + "\n"
        + _fb("mem-x", "useful", eid="f1")
        + "\n"
    )

    main([])

    out = capsys.readouterr().out
    assert "labeled evidence" in out.lower()
    labeled = out.lower().split("labeled evidence")[1]
    assert "mem-x" in labeled


def test_main_pairs_collapsed_in_output(tmp_path, capsys):
    """End-to-end: repeated Stop fires → stdout shows pairs=3, not pairs=4."""
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(
        "\n".join(
            [
                _ss("s1", "proj-a", ["mem-x"], edits=0, test_passes=0, eid="e1"),
                _ss("s1", "proj-a", ["mem-x", "mem-y"], edits=0, test_passes=1, eid="e2"),
                _ss("s2", "proj-a", ["mem-x"], edits=0, test_passes=0, eid="e3"),
            ]
        )
        + "\n"
    )

    main(["--events-file", str(f)])

    out = capsys.readouterr().out
    assert "pairs=3" in out
    assert "sessions=2" in out
