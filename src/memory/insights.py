"""Shared bounded-tail event snapshot for insights, stream, and sessions.

The event log has no time index — cursors are byte offsets and a no-cursor
read loads the whole file for a bounded tail. Every aggregation surface reads
through ONE snapshot cached by the log's (mtime_ns, size) so a page render
costs one file read, not three.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from memory.events import EventLog, MemoryEvent

EVENT_WINDOW = 5000

TIERS = ("working", "episodic", "semantic", "identity")

TIERS = ("working", "episodic", "semantic", "identity")

_cache: dict[Path, tuple[tuple[int, int, int], "EventSnapshot"]] = {}


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    events: tuple[MemoryEvent, ...]
    oldest_at: str | None
    window: int


def _log_key(path: Path, window: int) -> tuple[int, int, int]:
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size, window)
    except FileNotFoundError:
        return (0, 0, window)


def event_snapshot(log: EventLog, window: int = EVENT_WINDOW) -> EventSnapshot:
    key = _log_key(log.path, window)
    cached = _cache.get(log.path)
    if cached is not None and cached[0] == key:
        return cached[1]

    events, _cursor, _truncated = log.read_from(None, limit=window)
    snapshot = EventSnapshot(
        events=tuple(events),
        oldest_at=events[0].observed_at if events else None,
        window=window,
    )
    _cache[log.path] = (key, snapshot)
    return snapshot


def _within(observed_at: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(observed_at) >= cutoff
    except ValueError:
        return False


def _top_score(event: MemoryEvent) -> float | None:
    scores = [
        m.get("score")
        for m in event.payload.get("memories") or []
        if isinstance(m, dict) and isinstance(m.get("score"), (int, float))
    ]
    return max(scores) if scores else None


def scoped_events(snapshot: EventSnapshot, project: str | None) -> list[MemoryEvent]:
    """Snapshot events scoped to one project; None or 'all' means everything."""
    if project in (None, "all"):
        return list(snapshot.events)
    return [e for e in snapshot.events if e.project == project]


def build_insights(
    records: list[dict[str, Any]],
    snapshot: EventSnapshot,
    *,
    total: int,
    project: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Cockpit aggregates from one filtered record scroll + the event tail."""
    now = now or datetime.now()
    cutoff_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    tier_counts = dict.fromkeys(TIERS, 0)
    for record in records:
        tier = record.get("tier")
        if tier in tier_counts:
            tier_counts[tier] += 1

    this_monday = now - timedelta(days=now.weekday())
    per_week = []
    for weeks_ago in range(9, -1, -1):
        start = (this_monday - timedelta(weeks=weeks_ago)).strftime("%Y-%m-%d")
        end = (this_monday - timedelta(weeks=weeks_ago - 1)).strftime("%Y-%m-%d")
        per_week.append(
            {
                "week_start": start,
                "count": sum(1 for r in records if start <= (r.get("date") or "") < end),
            }
        )

    cutoff_dt = now - timedelta(days=7)
    events = scoped_events(snapshot, project)
    recalls = [
        e for e in events if e.event_type == "memory_recalled" and _within(e.observed_at, cutoff_dt)
    ]
    top_scores = [s for e in recalls if (s := _top_score(e)) is not None]

    return {
        "total": total,
        "in_scope": len(records),
        "weekly_delta": sum(1 for r in records if (r.get("date") or "") >= cutoff_date),
        "per_week": per_week,
        "recalls_7d": len(recalls),
        "recalls_with_hits_7d": sum(1 for e in recalls if e.payload.get("memory_ids")),
        "misses_7d": sum(1 for e in recalls if not e.payload.get("memory_ids")),
        "avg_top_score_7d": round(sum(top_scores) / len(top_scores), 4) if top_scores else None,
        "avg_top_score_denominator": len(top_scores),
        "promotions_7d": sum(
            1
            for e in events
            if e.event_type == "memory_promoted" and _within(e.observed_at, cutoff_dt)
        ),
        "episodics_created_7d": sum(
            1
            for r in records
            if r.get("tier") == "episodic" and (r.get("date") or "") >= cutoff_date
        ),
        "tier_counts": tier_counts,
        "event_window": {"events": len(snapshot.events), "oldest_at": snapshot.oldest_at},
    }
