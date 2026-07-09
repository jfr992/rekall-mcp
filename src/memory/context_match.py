"""Deterministic context partition for recall (spec 2026-07-08).

Post-score: the frozen ranking computes scores untouched; this reorders the
already-ranked pool. Survivor floor: at least ceil(limit/2) of the baseline
top-limit always survive — context can displace only below the floor.
Matching is content-substring (lowercased token overlap): the entity regex
misses plain lowercase words (red-team proof), so entities are a bonus, never
required. task_hint under MIN_HINT_TOKENS non-stopword tokens is ignored
(short hints broaden, not narrow — measured risk).
"""

from __future__ import annotations

import math

MIN_HINT_TOKENS = 2
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "with"}


def _hint_tokens(task_hint: str | None) -> list[str]:
    if not task_hint:
        return []
    tokens = [t for t in task_hint.lower().split() if t and t not in _STOPWORDS]
    return tokens if len(tokens) >= MIN_HINT_TOKENS else []


def _matches(memory: dict, tokens: list[str]) -> bool:
    content = str(memory.get("content", "")).lower()
    if any(t in content for t in tokens):
        return True
    entities = {str(e).lower() for e in memory.get("entities") or []}
    return bool(entities.intersection(tokens))


def partition_by_context(results: list[dict], task_hint: str | None, limit: int) -> list[dict]:
    # Mutates matched dicts in place (_context_matched=True) — recall() builds
    # fresh dicts per call, so this is safe; do not feed cached pools.
    tokens = _hint_tokens(task_hint)
    if not tokens:
        return results[:limit]

    floor = math.ceil(limit / 2)
    baseline = results[:limit]
    keep = baseline[:floor]  # unconditional survivors, rank order
    keep_ids = {m.get("memory_id") for m in keep}

    matched = [m for m in results if m.get("memory_id") not in keep_ids and _matches(m, tokens)]
    rest = [m for m in baseline if m.get("memory_id") not in keep_ids and not _matches(m, tokens)]

    out: list[dict] = list(keep)
    for m in matched:
        if len(out) >= limit:
            break
        m["_context_matched"] = True
        out.append(m)
    for m in rest:
        if len(out) >= limit:
            break
        out.append(m)
    # floor members that also match get the annotation (they earned it twice)
    for m in keep:
        if _matches(m, tokens):
            m["_context_matched"] = True
    return out[:limit]
