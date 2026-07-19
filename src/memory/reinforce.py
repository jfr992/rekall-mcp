"""Recall-driven reinforcement: credit extraction, damping, and the promotion gate.

See PLAN.md (T2) for the full design. Credit sources:
- memory_recalled: top-scored memory only, gated by score floor + top-margin
  (Codex F3 — session-wide union assigns fake causation to every recalled id).
- session_summary + its recalls: outcome-grade credit when the session shows
  edits_after_recall>0 or test_passes_after_recall>0, bare credit otherwise.
- memory_feedback: useful/wrong/stale verdicts.
"""

from __future__ import annotations

import fcntl
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Any

from memory.events import EventLog, MemoryEvent
from memory.lifecycle import LifecycleSignals, classify, compute_retention_days

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
    observed_at: str = ""


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
            observed_at=event.observed_at,
        )

    return FeedbackCredit(
        memory_id=memory_id,
        event_id=event.event_id,
        session_id=event.payload.get("session_id"),
        weight=1.0,
        outcome_grade=True,
        observed_at=event.observed_at,
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
    observed_at: str = ""


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
                observed_at=summary.observed_at,
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
            observed_at=summary.observed_at,
        )
        if c.score >= session_max - RECALL_TOP_MARGIN
        else OutcomeCredit(
            memory_id=c.memory_id,
            event_id=c.event_id,
            session_id=c.session_id,
            weight=BARE_RECALL_WEIGHT,
            outcome_grade=False,
            observed_at=summary.observed_at,
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


@dataclass(frozen=True, slots=True)
class Credit:
    """Normalized credit, regardless of source (recall, session, feedback)."""

    memory_id: str
    event_id: str
    session_id: str | None
    weight: float
    outcome_grade: bool
    disputed: bool = False
    observed_at: str = ""


@dataclass(frozen=True, slots=True)
class CollectResult:
    credits: list[Credit]
    newly_processed_sessions: set[str]
    supersedes_candidates: list[SupersedesCandidate]


def collect_credits(events: list[MemoryEvent], processed_sessions: frozenset[str]) -> CollectResult:
    """Fold a batch of events into credits, newly-processed sessions, and
    stale-supersedes candidates. Pure — no I/O, no store/graph access.

    A session's recalls are credited only once: the first session_summary
    seen for a given session_id in this batch (Stop hook fires per turn,
    so a session accrues many summary events — re-crediting on each would
    massively over-count).
    """
    recalls_by_session: dict[str | None, list[MemoryEvent]] = {}
    for e in events:
        if e.event_type == "memory_recalled":
            recalls_by_session.setdefault(e.payload.get("session_id"), []).append(e)

    credits: list[Credit] = []
    newly_processed: set[str] = set()
    supersedes: list[SupersedesCandidate] = []

    for e in events:
        if e.event_type == "session_summary":
            session_id = e.payload.get("session_id")
            if not session_id or session_id in processed_sessions or session_id in newly_processed:
                continue
            recalls = recalls_by_session.get(session_id, [])
            for outcome in credit_from_session(e, recalls):
                credits.append(
                    Credit(
                        memory_id=outcome.memory_id,
                        event_id=outcome.event_id,
                        session_id=outcome.session_id,
                        weight=outcome.weight,
                        outcome_grade=outcome.outcome_grade,
                        observed_at=outcome.observed_at,
                    )
                )
            newly_processed.add(session_id)

        elif e.event_type == "memory_feedback":
            feedback = credit_from_feedback(e)
            if feedback is not None:
                credits.append(
                    Credit(
                        memory_id=feedback.memory_id,
                        event_id=feedback.event_id,
                        session_id=feedback.session_id,
                        weight=feedback.weight,
                        outcome_grade=feedback.outcome_grade,
                        disputed=feedback.disputed,
                        observed_at=feedback.observed_at,
                    )
                )
            candidate = supersedes_candidate_from_feedback(e)
            if candidate is not None:
                supersedes.append(candidate)

    return CollectResult(
        credits=credits,
        newly_processed_sessions=newly_processed,
        supersedes_candidates=supersedes,
    )


@contextmanager
def reinforce_lock(lock_path: Path) -> Iterator[None]:
    """Serialize read-reclassify-write on a memory's payload (Codex F11).

    A blocking flock on a dedicated lock file — same idiom as the embedded
    store's ownership lock (core/ownership.py), stdlib only.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _history_from_payload(memory: dict[str, Any]) -> list[HistoryEntry]:
    return [
        HistoryEntry(
            event_id=h.get("event_id", ""),
            kind=h.get("kind", ""),
            ts=h.get("ts", ""),
            session_id=h.get("session_id"),
        )
        for h in memory.get("history") or []
    ]


def _history_to_payload(history: list[HistoryEntry]) -> list[dict[str, Any]]:
    return [
        {"event_id": h.event_id, "kind": h.kind, "ts": h.ts, "session_id": h.session_id}
        for h in history
    ]


def _age_days(memory: dict[str, Any], now: datetime) -> int:
    date_str = memory.get("date") or now.strftime("%Y-%m-%d")
    try:
        mem_date = datetime.strptime(date_str, "%Y-%m-%d")
        return max(0, (now - mem_date).days)
    except ValueError:
        return 0


def _apply_credit_to_memory(
    memory_id: str,
    kind_credits: list[Credit],
    *,
    store: Any,
    graph: Any,
    now: datetime,
    lock_path: Path,
    record_event: Callable[..., None],
) -> None:
    """Read-reclassify-write one memory's payload under the named lock."""
    with reinforce_lock(lock_path):
        memory = store.get_by_id(memory_id)
        if not memory:
            return

        history = _history_from_payload(memory)
        total_delta = 0.0
        # Chronological order + each credit's own observed_at (not the
        # single `now` passed to this pass) so day-spread/damping windows
        # reflect when the events actually happened.
        for credit in sorted(kind_credits, key=lambda c: c.observed_at or ""):
            kind = "wrong" if credit.disputed else ("outcome" if credit.outcome_grade else "bare")
            try:
                credit_time = (
                    datetime.fromisoformat(credit.observed_at) if credit.observed_at else now
                )
            except ValueError:
                credit_time = now
            result = apply_reinforcement(
                history=history,
                weight=credit.weight,
                event_id=credit.event_id,
                kind=kind,
                now=credit_time,
                session_id=credit.session_id,
            )
            history = result.history
            total_delta += result.delta

        new_count = max(0.0, float(memory.get("reinforcement_count") or 0) + total_delta)

        current_tier = memory.get("tier")
        explicit_tier = current_tier if current_tier == "identity" else None
        signals = LifecycleSignals(
            memory_type=memory.get("type", "note"),
            salience=float(memory.get("salience") or 0.0),
            age_days=_age_days(memory, now),
            reinforcement_count=new_count,
            contradicts_count=graph.count_contradicts(memory_id) if memory_id else 0,
            explicit_tier=explicit_tier,
        )
        result_cls = classify(signals)

        # classify() promotes to semantic on raw count>=5 alone; the reinforce
        # pass additionally requires session/day spread + outcome-grade
        # evidence (PLAN.md Design > Promotion eligibility). A tier bump that
        # doesn't clear the extra gate is held at the prior tier.
        final_tier = result_cls.tier
        if _TIER_RANK.get(final_tier, 0) > _TIER_RANK.get(
            current_tier, 0
        ) and not promotion_eligible(history):
            final_tier = current_tier or "working"

        disputed = memory.get("disputed", False) or any(c.disputed for c in kind_credits)

        updated_payload: dict[str, Any] = {
            "reinforcement_count": new_count,
            "history": _history_to_payload(history),
            "tier": final_tier,
            "durability": result_cls.durability,
            "lifecycle_reason": result_cls.reason,
            "retention_days": compute_retention_days(memory.get("type", "note"), final_tier),
            "disputed": disputed,
        }
        store.update_payload(memory_id, updated_payload)

        if _TIER_RANK.get(final_tier, 0) > _TIER_RANK.get(current_tier, 0):
            record_event(
                event_type="memory_promoted",
                project=str(memory.get("project") or "general"),
                source="reinforcement",
                memory_ids=[memory_id],
                payload={"memory_id": memory_id, "from_tier": current_tier, "to_tier": final_tier},
            )


_TIER_RANK = {"working": 0, "episodic": 1, "semantic": 2, "identity": 3}


def process_events(
    *,
    event_log: EventLog,
    store: Any,
    graph: Any,
    state_path: Path,
    lock_path: Path,
    now: datetime,
    record_event: Callable[..., None],
    batch_limit: int = 500,
) -> None:
    """Read new events since the last checkpoint, apply credits, persist.

    truncated=True (log rewritten/rotated underneath the cursor) halts
    processing immediately without advancing the checkpoint — never
    blind-replay (F5, F13).
    """
    state = load_state(state_path)
    events, next_cursor, truncated = event_log.read_from(state.cursor, limit=batch_limit)

    if truncated:
        logger.warning(
            "reinforce: event log truncated/rewritten past checkpoint cursor — "
            "halting for manual reconciliation, not advancing checkpoint"
        )
        return

    if not events:
        return

    result = collect_credits(events, processed_sessions=state.processed_sessions)

    by_memory = sorted(result.credits, key=lambda c: c.memory_id)
    for memory_id, group in groupby(by_memory, key=lambda c: c.memory_id):
        _apply_credit_to_memory(
            memory_id,
            list(group),
            store=store,
            graph=graph,
            now=now,
            lock_path=lock_path,
            record_event=record_event,
        )

    for candidate in result.supersedes_candidates:
        record_event(
            event_type="memory_supersedes_candidate",
            project="general",
            source="reinforcement",
            memory_ids=[candidate.memory_id],
            payload={"memory_id": candidate.memory_id, "reason": "stale_feedback"},
        )

    new_state = ReinforceState(
        cursor=next_cursor,
        processed_sessions=state.processed_sessions | result.newly_processed_sessions,
    )
    save_state(state_path, new_state)
