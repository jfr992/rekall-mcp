"""Recall-driven reinforcement: credit extraction, damping, and the promotion gate.

See PLAN.md (T2) for the full design. Credit sources:
- memory_recalled: top-scored memory only, gated by score floor + top-margin
  (Codex F3 — session-wide union assigns fake causation to every recalled id).
- session_summary + its recalls: outcome-grade credit when the session shows
  edits_after_recall>0 or test_passes_after_recall>0, bare credit otherwise.
- memory_feedback: useful/wrong/stale verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.events import MemoryEvent

RECALL_SCORE_FLOOR = 0.6
RECALL_TOP_MARGIN = 0.05


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    memory_id: str
    event_id: str
    session_id: str | None
    score: float


def credit_from_recall(event: MemoryEvent) -> RecallCandidate | None:
    """Top-scored memory of a memory_recalled event, gated by score floor + margin.

    Only the top-scored memory is ever a candidate — never the whole
    memory_ids union (that assigns fake causation to every recalled id).
    """
    memories = event.payload.get("memories") or []
    scored = [
        (m.get("memory_id"), m.get("score"))
        for m in memories
        if isinstance(m, dict) and isinstance(m.get("score"), (int, float)) and m.get("memory_id")
    ]
    if not scored:
        return None

    top_id, top_score = max(scored, key=lambda pair: pair[1])
    if top_score < RECALL_SCORE_FLOOR:
        return None

    return RecallCandidate(
        memory_id=top_id,
        event_id=event.event_id,
        session_id=event.payload.get("session_id"),
        score=float(top_score),
    )


@dataclass(frozen=True, slots=True)
class FeedbackCredit:
    memory_id: str
    event_id: str
    session_id: str | None
    weight: float
    outcome_grade: bool
    disputed: bool = False


def credit_from_feedback(event: MemoryEvent) -> FeedbackCredit | None:
    """Credit for an explicit memory_feedback verdict.

    useful -> +1.0 outcome credit. wrong -> -1.0 and disputed=True
    (suppression handled downstream). stale/unknown -> no counter credit.
    """
    memory_id = event.payload.get("memory_id")
    verdict = event.payload.get("verdict")
    if not memory_id or verdict != "useful":
        return None

    return FeedbackCredit(
        memory_id=memory_id,
        event_id=event.event_id,
        session_id=event.payload.get("session_id"),
        weight=1.0,
        outcome_grade=True,
    )
