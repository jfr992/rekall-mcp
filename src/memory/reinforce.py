"""Recall-driven reinforcement: credit extraction, damping, and the promotion gate.

See PLAN.md (T2) for the full design. Credit sources:
- memory_recalled: top-scored memory only, gated by score floor + top-margin
  (Codex F3 — session-wide union assigns fake causation to every recalled id).
- session_summary + its recalls: outcome-grade credit when the session shows
  edits_after_recall>0 or test_passes_after_recall>0, bare credit otherwise.
- memory_feedback: useful/wrong/stale verdicts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from memory.events import MemoryEvent

logger = logging.getLogger(__name__)

RECALL_SCORE_FLOOR = 0.6
RECALL_TOP_MARGIN = 0.05
BARE_RECALL_WEIGHT = 0.25
DAMPING_WINDOW_DAYS = 30
HISTORY_CAP = 20


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
    if not memory_id or verdict not in ("useful", "wrong"):
        return None

    if verdict == "wrong":
        return FeedbackCredit(
            memory_id=memory_id,
            event_id=event.event_id,
            session_id=event.payload.get("session_id"),
            weight=-1.0,
            outcome_grade=False,
            disputed=True,
        )

    return FeedbackCredit(
        memory_id=memory_id,
        event_id=event.event_id,
        session_id=event.payload.get("session_id"),
        weight=1.0,
        outcome_grade=True,
    )


@dataclass(frozen=True, slots=True)
class SupersedesCandidate:
    memory_id: str
    event_id: str
    session_id: str | None


def supersedes_candidate_from_feedback(event: MemoryEvent) -> SupersedesCandidate | None:
    """A stale verdict is truth-maintenance signal, not counter credit.

    Emits/refreshes a supersedes-candidate record for hygiene review
    instead of touching reinforcement_count (Zep lesson: staleness invalidates,
    it doesn't decay a score).
    """
    memory_id = event.payload.get("memory_id")
    if not memory_id or event.payload.get("verdict") != "stale":
        return None

    return SupersedesCandidate(
        memory_id=memory_id,
        event_id=event.event_id,
        session_id=event.payload.get("session_id"),
    )


@dataclass(frozen=True, slots=True)
class OutcomeCredit:
    memory_id: str
    event_id: str
    session_id: str | None
    weight: float
    outcome_grade: bool


def credit_from_session(summary: MemoryEvent, recalls: list[MemoryEvent]) -> list[OutcomeCredit]:
    """Outcome credit for a session_summary's recall-followed-by-use signal.

    Only recalls matching the summary's session_id count. Each recall's own
    top-1 (via credit_from_recall) is a candidate; it earns outcome credit
    (+1.0) only if the session shows edits/test-passes AND its score is
    within RECALL_TOP_MARGIN of the session's best candidate score — a
    weak recall in a session where a different recall clearly drove the
    outcome doesn't get borrowed credit (Codex F3).
    """
    session_id = summary.payload.get("session_id")
    has_outcome = (
        int(summary.payload.get("edits_after_recall") or 0) > 0
        or int(summary.payload.get("test_passes_after_recall") or 0) > 0
    )

    candidates = [
        candidate_result
        for r in recalls
        if r.payload.get("session_id") == session_id
        and (candidate_result := credit_from_recall(r)) is not None
    ]
    if not candidates:
        return []

    if not has_outcome:
        return [
            OutcomeCredit(
                memory_id=c.memory_id,
                event_id=c.event_id,
                session_id=c.session_id,
                weight=BARE_RECALL_WEIGHT,
                outcome_grade=False,
            )
            for c in candidates
        ]

    session_max = max(c.score for c in candidates)
    return [
        OutcomeCredit(
            memory_id=c.memory_id,
            event_id=c.event_id,
            session_id=c.session_id,
            weight=1.0,
            outcome_grade=True,
        )
        if c.score >= session_max - RECALL_TOP_MARGIN
        else OutcomeCredit(
            memory_id=c.memory_id,
            event_id=c.event_id,
            session_id=c.session_id,
            weight=BARE_RECALL_WEIGHT,
            outcome_grade=False,
        )
        for c in candidates
    ]


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    event_id: str
    kind: str
    ts: str
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReinforcementResult:
    history: list[HistoryEntry]
    delta: float


def _damping_factor(n: int) -> float:
    """1/(1+0.5(n-1)) — nth increment in the rolling window, n>=1."""
    return 1.0 / (1.0 + 0.5 * (n - 1))


def apply_reinforcement(
    history: list[HistoryEntry],
    weight: float,
    event_id: str,
    kind: str,
    now: datetime,
    session_id: str | None = None,
) -> ReinforcementResult:
    """Damp `weight` by its position in the rolling 30d window, append to history.

    Only positive weights (reinforcement) are damped — a `wrong` penalty
    (-1.0) is not diminishing-returns credit and applies at full weight.
    History is capped at the last HISTORY_CAP entries (Mem0 precedent).
    """
    cutoff = now.timestamp() - DAMPING_WINDOW_DAYS * 86400
    recent_count = sum(
        1
        for h in history
        if h.kind != "wrong" and datetime.fromisoformat(h.ts).timestamp() >= cutoff
    )

    if weight > 0:
        n = recent_count + 1
        delta = weight * _damping_factor(n)
    else:
        delta = weight

    new_history = [
        *history,
        HistoryEntry(event_id=event_id, kind=kind, ts=now.isoformat(), session_id=session_id),
    ]
    new_history = new_history[-HISTORY_CAP:]

    return ReinforcementResult(history=new_history, delta=delta)


_OUTCOME_KINDS = frozenset({"outcome", "useful"})
_MIN_SESSIONS = 2
_MIN_DAYS = 2


def promotion_eligible(history: list[HistoryEntry]) -> bool:
    """Additional gate enforced in the reinforce pass, not classify().

    classify() promotes at reinforcement_count>=5 on raw count alone; this
    gate additionally requires evidence from >=2 distinct sessions on >=2
    distinct days, with >=1 outcome-grade (use-evidence or useful) event —
    bare recalls/session-count alone can never promote.
    """
    sessions = {h.session_id for h in history if h.session_id}
    days = {h.ts[:10] for h in history}
    has_outcome = any(h.kind in _OUTCOME_KINDS for h in history)

    return len(sessions) >= _MIN_SESSIONS and len(days) >= _MIN_DAYS and has_outcome


@dataclass(frozen=True, slots=True)
class ReinforceState:
    """Durable checkpoint: log cursor + sessions already outcome-credited.

    Persisted outside the event log (_reinforce_state.json) so a rewritten/
    truncated log is detected via EventLog.read_from's own truncated flag
    instead of blind-replayed (F5, F13).
    """

    cursor: str | None
    processed_sessions: frozenset[str]


def load_state(path: Path) -> ReinforceState:
    """Fresh state if the checkpoint file is absent or unreadable."""
    if not path.exists():
        return ReinforceState(cursor=None, processed_sessions=frozenset())

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReinforceState(
            cursor=data.get("cursor"),
            processed_sessions=frozenset(data.get("processed_sessions") or []),
        )
    except (json.JSONDecodeError, OSError, TypeError):
        logger.warning("reinforce state file unreadable, starting fresh: %s", path, exc_info=True)
        return ReinforceState(cursor=None, processed_sessions=frozenset())


def save_state(path: Path, state: ReinforceState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cursor": state.cursor,
        "processed_sessions": sorted(state.processed_sessions),
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
