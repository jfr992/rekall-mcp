"""Offline dry-run report for recall-driven reinforcement (PLAN.md T2/T7).

Replays the full surviving event-log history through the same credit math
the live processor uses (memory.reinforce) and prints a table: memory_id,
content preview, credits by kind, effective (damped) score, and whether
the promotion gate would fire. THE GATE: a human reviews this table before
--apply performs the real write.

Usage:
    python scripts/reinforce_replay.py [--events-file PATH] [--apply]

    --events-file  Path to the JSONL event log.
                   Default: <MEMORY_STORAGE_PATH or ~/.claude/memory>/_events.jsonl
    --apply        Perform the real write via memory.reinforce.process_events.
                   Without this flag the command is dry-run only (default).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from memory.events import MemoryEvent
from memory.reinforce import (
    HistoryEntry,
    apply_reinforcement,
    collect_credits,
    process_events,
    promotion_eligible,
)


def parse_events(events_file: Path) -> list[MemoryEvent]:
    """Read JSONL events, skipping malformed lines."""
    if not events_file.exists():
        return []

    events: list[MemoryEvent] = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(MemoryEvent(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return events


@dataclass(frozen=True, slots=True)
class ReplayRow:
    memory_id: str
    content_preview: str
    credits_by_kind: dict[str, int] = field(default_factory=dict)
    effective: float = 0.0
    would_promote: bool = False


def build_replay_rows(
    events_file: Path, memories: dict[str, dict[str, Any]], now: datetime
) -> list[ReplayRow]:
    """Simulate the full reinforce pass from scratch (no checkpoint) and
    return one row per credited memory, sorted by effective score desc.
    """
    events = parse_events(events_file)
    result = collect_credits(events, processed_sessions=frozenset())

    by_memory: dict[str, list] = {}
    for credit in result.credits:
        by_memory.setdefault(credit.memory_id, []).append(credit)

    rows: list[ReplayRow] = []
    for memory_id, credits in by_memory.items():
        history: list[HistoryEntry] = []
        credits_by_kind: dict[str, int] = {}
        effective = 0.0
        # Chronological order + each credit's own observed_at (not the
        # replay's single `now`) so the day-spread/damping windows reflect
        # when the events actually happened, not when the report ran.
        for credit in sorted(credits, key=lambda c: c.observed_at or ""):
            kind = "wrong" if credit.disputed else ("outcome" if credit.outcome_grade else "bare")
            credits_by_kind[kind] = credits_by_kind.get(kind, 0) + 1
            try:
                credit_time = (
                    datetime.fromisoformat(credit.observed_at) if credit.observed_at else now
                )
            except ValueError:
                credit_time = now
            outcome = apply_reinforcement(
                history=history,
                weight=credit.weight,
                event_id=credit.event_id,
                kind=kind,
                now=credit_time,
                session_id=credit.session_id,
            )
            history = outcome.history
            effective += outcome.delta

        content = str((memories.get(memory_id) or {}).get("content") or "")
        rows.append(
            ReplayRow(
                memory_id=memory_id,
                content_preview=content[:80],
                credits_by_kind=credits_by_kind,
                effective=round(effective, 4),
                would_promote=promotion_eligible(history),
            )
        )

    return sorted(rows, key=lambda r: r.effective, reverse=True)


def log_retention_stats(events: list[MemoryEvent]) -> dict[str, Any]:
    """Characterize how much history this replay actually covers."""
    if not events:
        return {"count": 0, "oldest": None, "newest": None}

    timestamps = sorted(e.observed_at for e in events)
    return {"count": len(events), "oldest": timestamps[0], "newest": timestamps[-1]}


def credit_coverage_stats(events: list[MemoryEvent]) -> dict[str, int]:
    """Why credits may be missing: recalls without session_id can never be
    credited (unsafe attribution — plumbed only from v1.14 on)."""
    recalls = [e for e in events if e.event_type == "memory_recalled"]
    sessionless = sum(1 for e in recalls if not e.payload.get("session_id"))
    summaries = sum(1 for e in events if e.event_type == "session_summary")
    return {
        "recalls": len(recalls),
        "recalls_without_session_id": sessionless,
        "summaries": summaries,
    }


def print_report(
    rows: list[ReplayRow], retention: dict[str, Any], coverage: dict[str, int] | None = None
) -> None:
    print(
        f"Log retention: {retention['count']} events, "
        f"oldest={retention['oldest']}, newest={retention['newest']}"
    )
    print()

    if not rows:
        print("(no credited memories)")
        if coverage:
            print(
                f"  coverage: {coverage['recalls']} recalls seen, "
                f"{coverage['recalls_without_session_id']} without session_id "
                f"(uncreditable — attribution plumbed from v1.14), "
                f"{coverage['summaries']} session summaries"
            )
        return

    kinds = sorted({k for row in rows for k in row.credits_by_kind})
    header = f"  {'memory_id':<40} {'content':<40} " + " ".join(f"{k:>8}" for k in kinds)
    header += f" {'effective':>10} {'promote':>8}"
    print(header)
    for row in rows:
        credits_str = " ".join(f"{row.credits_by_kind.get(k, 0):>8}" for k in kinds)
        print(
            f"  {row.memory_id:<40} {row.content_preview:<40} {credits_str} "
            f"{row.effective:>10.3f} {'YES' if row.would_promote else 'no':>8}"
        )


def default_events_file() -> Path:
    import os

    storage = os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")
    return Path(storage).expanduser() / "_events.jsonl"


def main(argv: list[str] | None = None) -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Offline dry-run report for recall-driven reinforcement.",
    )
    parser.add_argument(
        "--events-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to the JSONL event log (default: <MEMORY_STORAGE_PATH>/_events.jsonl)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the real write via memory.reinforce.process_events "
        "(default is dry-run only — review the table first).",
    )
    args = parser.parse_args(argv)

    events_file = args.events_file or default_events_file()
    events = parse_events(events_file)

    if not events:
        print("no event data yet")
        sys.exit(0)

    rows = build_replay_rows(events_file, memories={}, now=datetime.now())
    print_report(rows, log_retention_stats(events), credit_coverage_stats(events))

    if args.apply:
        _apply_live(events_file)


def _apply_live(events_file: Path) -> None:
    """--apply: run the real checkpointed pass against the live store.

    Uses MemoryManager's own storage resolution (MEMORY_STORAGE_PATH /
    QDRANT_URL / QDRANT_PATH) — same env the rest of Rekall reads.
    """
    from memory import MemoryManager

    manager = MemoryManager()
    state_path = events_file.parent / "_reinforce_state.json"
    lock_path = events_file.parent / "_reinforce.lock"

    print()
    print(f"Applying via process_events (checkpoint: {state_path})...")
    process_events(
        event_log=manager.event_log,
        store=manager.store,
        graph=manager.knowledge_graph,
        state_path=state_path,
        lock_path=lock_path,
        now=datetime.now(),
        record_event=manager.record_event,
    )
    print("Done.")


if __name__ == "__main__":
    main()
