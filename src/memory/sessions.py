"""Fold U1 events into session objects for the /sessions transparency view.

Pure functions over MemoryEvent lists — no I/O, no manager access. Field
truth: session_summary and memory_surfaced carry payload.session_id;
recalled ids live under payload.memory_ids (record_event merges them).
Recall events are null-session today (manager hardcodes None), so recall
attribution is a join: same project, observed_at inside the session window,
and payload.memory_ids intersecting the summaries' memory_ids (SPEC U1 1a).
"""

from __future__ import annotations

from typing import Any

from memory.events import MemoryEvent


def _new_session(session_id: str, project: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "project": project,
        "started_at": None,
        "last_at": None,
        "injected": [],
        "recalls": [],
        "totals": {"recalls": 0, "injected": 0, "tokens": 0},
    }


def _touch(session: dict[str, Any], observed_at: str) -> None:
    if session["started_at"] is None or observed_at < session["started_at"]:
        session["started_at"] = observed_at
    if session["last_at"] is None or observed_at > session["last_at"]:
        session["last_at"] = observed_at


def _recall_entry(event: MemoryEvent) -> dict[str, Any]:
    payload = event.payload or {}
    return {
        "query": payload.get("query"),
        "memories": payload.get("memories") or [],
        "token_estimate": int(payload.get("token_estimate") or 0),
        "observed_at": event.observed_at,
    }


def _attach_recall(session: dict[str, Any], event: MemoryEvent) -> None:
    entry = _recall_entry(event)
    session["recalls"].append(entry)
    session["totals"]["tokens"] += entry["token_estimate"]
    _touch(session, event.observed_at)


def _join_target(
    event: MemoryEvent,
    sessions: dict[str, dict[str, Any]],
    summary_ids: dict[str, set[str]],
    window_end: dict[str, str],
) -> dict[str, Any] | None:
    """SPEC U1 1a join: project + window + memory_ids intersection.

    memory_ids intersection is the discriminator — project+time alone would
    cross-attribute concurrent sessions. Ties resolve to the session whose
    summary fired soonest after the recall (smallest window end).
    """
    recall_ids = set((event.payload or {}).get("memory_ids") or [])
    candidates = [
        sid
        for sid, end in window_end.items()
        if sessions[sid]["project"] == event.project
        and event.observed_at <= end
        and recall_ids & summary_ids.get(sid, set())
    ]
    if not candidates:
        return None
    return sessions[min(candidates, key=lambda sid: window_end[sid])]


def fold_sessions(events: list[MemoryEvent], limit: int = 50) -> list[dict[str, Any]]:
    """Fold events into session objects, newest-activity first."""
    sessions: dict[str, dict[str, Any]] = {}
    summary_ids: dict[str, set[str]] = {}
    window_end: dict[str, str] = {}

    for event in events:
        payload = event.payload or {}
        session_id = payload.get("session_id")
        if not session_id or event.event_type not in ("session_summary", "memory_surfaced"):
            continue
        session = sessions.setdefault(session_id, _new_session(session_id, event.project))
        _touch(session, event.observed_at)

        if event.event_type == "session_summary":
            summary_ids.setdefault(session_id, set()).update(payload.get("memory_ids") or [])
            end = window_end.get(session_id)
            if end is None or event.observed_at > end:
                window_end[session_id] = event.observed_at
        else:
            seen = {item["memory_id"] for item in session["injected"]}
            for memory_id in payload.get("memory_ids") or []:
                if memory_id not in seen:
                    # Per-memory token estimates are not recorded; only the
                    # event-level aggregate exists (counted in totals.tokens).
                    session["injected"].append({"memory_id": memory_id, "token_estimate": None})
                    seen.add(memory_id)
            session["totals"]["tokens"] += int(payload.get("token_estimate") or 0)

    for event in events:
        if event.event_type != "memory_recalled":
            continue
        payload = event.payload or {}
        session_id = payload.get("session_id")
        target = (
            sessions.get(session_id)
            if session_id
            else _join_target(event, sessions, summary_ids, window_end)
        )
        if target is None:
            # Honest bucket: attribution failed, but the recall stays visible.
            bucket_id = f"unattributed:{event.project}"
            target = sessions.setdefault(bucket_id, _new_session(bucket_id, event.project))
        _attach_recall(target, event)

    for session in sessions.values():
        session["totals"]["injected"] = len(session["injected"])
        session["totals"]["recalls"] = len(session["recalls"])
        session["recalls"].sort(key=lambda r: r["observed_at"])

    ordered = sorted(sessions.values(), key=lambda s: s["last_at"] or "", reverse=True)
    return ordered[:limit]
