"""Gate evaluation for superseded-prune (spec 2026-07-06 Part 2, gates 1-4).

Pure: takes edges + a memory lookup, returns leaf-first ordered candidates.
Gates 5-7 (backup, caps/token, reporting) live in the endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

MIN_MEMORY_AGE_DAYS = 90
MIN_EDGE_AGE_DAYS = 7
MIN_PAIR_GAP_DAYS = 30
MAX_PER_FIRE = 10
MAX_PER_DAY = 20


@dataclass(frozen=True)
class Candidate:
    memory_id: str
    superseded_by: str


def _days(a: str | None, b: date) -> int | None:
    if not a:
        return None
    try:
        return (b - datetime.strptime(a[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return None


def build_candidates(edges, get_memory, today: date) -> list[Candidate]:
    out: list[Candidate] = []
    for source, target, data in edges:
        if data.get("relation") != "supersedes":  # gate 1
            continue
        # LLM-refined supersedes edges are recall-ranking signals only — never deletion signals.
        if data.get("llm_refined"):
            continue
        # Same for provisional-band edges (widened [0.85, 0.90) similarity range).
        if data.get("band") == "provisional":
            continue
        edge_age = _days(data.get("created"), today)
        if edge_age is None or edge_age < MIN_EDGE_AGE_DAYS:  # gate 3.5 (missing = refuse)
            continue
        old = get_memory(target)
        new = get_memory(source)
        if old is None or new is None:  # gate 2 (superseder must exist)
            continue
        if old.get("reinforcement_count", 0) > 0 or old.get("compacted"):  # gate 1.5
            continue
        old_age = _days(old.get("date"), today)
        if old_age is None or old_age < MIN_MEMORY_AGE_DAYS:  # gate 3
            continue
        try:
            gap = (
                _days(
                    old.get("date"), datetime.strptime(new.get("date", "")[:10], "%Y-%m-%d").date()
                )
                if new.get("date")
                else None
            )
        except ValueError:
            gap = None
        if gap is None or gap < MIN_PAIR_GAP_DAYS:  # gate 3.6
            continue
        if old.get("tier") == "identity":  # gate 4
            continue
        out.append(Candidate(memory_id=target, superseded_by=source))

    # leaf-first: a candidate that supersedes another candidate sorts after its target
    candidate_ids = {c.memory_id for c in out}
    superseder_of_candidate = {c.superseded_by for c in out if c.superseded_by in candidate_ids}
    out.sort(key=lambda c: (c.memory_id in superseder_of_candidate, c.memory_id))
    return out
