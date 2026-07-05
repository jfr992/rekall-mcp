"""Offline recall-utility report with null-hypothesis baseline.

Reads the Rekall event log (JSONL) and computes per-memory recall utility:
    utility = sessions-with-outcome / sessions-recalled
where denominator counts only session_summary events and memory_surfaced
events NEVER enter the denominator (coverage stat only).

Usage:
    python scripts/utility_report.py [--events-file PATH]

    --events-file  Path to the JSONL event log.
                   Default: ~/.claude/memory/_events.jsonl
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

DEFAULT_EVENTS_FILE = Path.home() / ".claude" / "memory" / "_events.jsonl"


def parse_events(events_file: Path) -> list[dict]:
    """Read JSONL events, skipping malformed lines."""
    if not events_file.exists():
        return []

    events = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def build_session_summaries(events: list[dict]) -> list[dict]:
    """Extract and normalise session_summary events into plain dicts."""
    summaries = []
    for e in events:
        if e.get("event_type") != "session_summary":
            continue
        payload = e.get("payload", {})
        recalled = payload.get("memory_ids", [])
        if not isinstance(recalled, list):
            recalled = []
        summaries.append(
            {
                "session_id": payload.get("session_id"),
                "project": e.get("project", ""),
                "recalled_ids": recalled,
                "edits_after_recall": int(payload.get("edits_after_recall", 0)),
                "test_passes_after_recall": int(payload.get("test_passes_after_recall", 0)),
            }
        )
    return summaries


def compute_utility_map(summaries: list[dict]) -> dict[str, float]:
    """Per-memory utility = sessions_with_outcome / sessions_recalled.

    Denominator: distinct sessions where the memory appeared in a
    session_summary's recalled_ids.  Has-outcome: edits_after_recall > 0
    OR test_passes_after_recall > 0.
    """
    sessions_recalled: dict[str, set[str]] = defaultdict(set)
    sessions_with_outcome: dict[str, set[str]] = defaultdict(set)

    for ss in summaries:
        sid = ss["session_id"] or ""
        has_outcome = ss["edits_after_recall"] > 0 or ss["test_passes_after_recall"] > 0
        for mid in ss["recalled_ids"]:
            sessions_recalled[mid].add(sid)
            if has_outcome:
                sessions_with_outcome[mid].add(sid)

    return {
        mid: len(sessions_with_outcome.get(mid, set())) / len(sess_set)
        for mid, sess_set in sessions_recalled.items()
    }


def build_surfaced_counts(events: list[dict]) -> dict[str, int]:
    """Count surfaced occurrences per memory_id from memory_surfaced events."""
    counts: dict[str, int] = defaultdict(int)
    for e in events:
        if e.get("event_type") != "memory_surfaced":
            continue
        for mid in e.get("payload", {}).get("memory_ids", []):
            counts[mid] += 1
    return dict(counts)


def build_universe(events: list[dict]) -> list[str]:
    """Sorted unique memory_ids from all events (for null baseline sampling)."""
    universe: set[str] = set()
    for e in events:
        for mid in e.get("payload", {}).get("memory_ids", []):
            universe.add(mid)
    return sorted(universe)


def progress_line(summaries: list[dict]) -> str:
    """Build the exit-criterion progress line."""
    pairs = sum(1 for ss in summaries if ss["recalled_ids"])
    sessions = len({ss["session_id"] for ss in summaries if ss["session_id"]})
    projects = len({ss["project"] for ss in summaries if ss["project"]})
    return f"pairs={pairs} sessions={sessions} projects={projects} (need 500/20/3)"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    import math

    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def compute_null_baseline(
    summaries: list[dict],
    universe: list[str],
    rng,
) -> list[float]:
    """Replace each recalled memory with a random draw from universe (seeded).

    Returns per-null-memory utility values for the null distribution.
    """
    if not universe:
        return []

    null_sessions_recalled: dict[str, set[str]] = defaultdict(set)
    null_sessions_outcome: dict[str, set[str]] = defaultdict(set)

    for ss in summaries:
        sid = ss["session_id"] or ""
        has_outcome = ss["edits_after_recall"] > 0 or ss["test_passes_after_recall"] > 0
        for _ in ss["recalled_ids"]:
            null_mid = rng.choice(universe)
            null_sessions_recalled[null_mid].add(sid)
            if has_outcome:
                null_sessions_outcome[null_mid].add(sid)

    return [
        len(null_sessions_outcome.get(mid, set())) / len(sess_set)
        for mid, sess_set in null_sessions_recalled.items()
    ]


def print_report(
    utility_map: dict[str, float],
    surfaced_counts: dict[str, int],
    null_utilities: list[float],
    progress: str,
) -> None:
    """Print the full report to stdout."""
    print(f"Exit criterion: {progress}")
    print()

    print("Recall Utility (denominator: distinct sessions with recall)")
    if utility_map:
        print(f"  {'memory_id':<45} {'utility':>7}")
        for mid, u in sorted(utility_map.items(), key=lambda kv: -kv[1]):
            print(f"  {mid:<45} {u:>7.3f}")
    else:
        print("  (no session_summary data)")
    print()

    real_vals = list(utility_map.values())
    mean_real = _mean(real_vals)
    mean_null = _mean(null_utilities)
    delta = mean_real - mean_null
    sign = "+" if delta >= 0 else ""
    print(
        f"Null baseline: mean_real={mean_real:.3f}  "
        f"mean_null={mean_null:.3f}  (delta={sign}{delta:.3f})"
    )
    if null_utilities and real_vals:
        std_null = _stddev(null_utilities)
        threshold = mean_null + 2 * std_null
        top10 = sorted(real_vals, reverse=True)[:10]
        mean_top10 = _mean(top10)
        status = "MET" if mean_top10 > threshold else "not yet"
        print(f"  2σ criterion: {status} (top-10 mean={mean_top10:.3f}, threshold={threshold:.3f})")
    print()

    surfaced_only = {mid: cnt for mid, cnt in surfaced_counts.items() if mid not in utility_map}
    print("Coverage (memory_surfaced, excluded from recall denominator)")
    if surfaced_only:
        print(f"  {'memory_id':<45} {'surfaced':>8}")
        for mid, cnt in sorted(surfaced_only.items(), key=lambda kv: -kv[1]):
            print(f"  {mid:<45} {cnt:>8}")
    else:
        print("  (no surfaced-only memories)")


def main(argv=None) -> None:
    import argparse
    import random
    import sys

    parser = argparse.ArgumentParser(
        description="Offline recall-utility report with null-hypothesis baseline.",
    )
    parser.add_argument(
        "--events-file",
        type=Path,
        default=DEFAULT_EVENTS_FILE,
        metavar="PATH",
        help="Path to the JSONL event log (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    events = parse_events(args.events_file)
    summaries = build_session_summaries(events)

    if not summaries:
        print("no event data yet")
        sys.exit(0)

    surfaced_counts = build_surfaced_counts(events)
    universe = build_universe(events)
    utility_map = compute_utility_map(summaries)
    null_utilities = compute_null_baseline(summaries, universe, random.Random(42))
    progress = progress_line(summaries)

    print_report(utility_map, surfaced_counts, null_utilities, progress)


if __name__ == "__main__":
    main()
