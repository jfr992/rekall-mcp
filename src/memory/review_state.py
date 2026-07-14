"""Review-state projection materialized from the event log (U1 Task 4).

`_review_state.json` lives in the memory dir, keyed by memory_id, and is
derived purely from `_events.jsonl` (memory_reviewed / memory_updated /
memory_pruned). INVARIANT: the server is the ONLY writer — the CLI and hooks
must never emit review events or write this file. Events stay audit-only;
this file is a cache that `load()` rebuilds whenever it is missing,
unparseable, or older than the events file (covers tarball restores — both
files live inside the reindex/backup roots).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_FILENAME = "_review_state.json"
EVENTS_FILENAME = "_events.jsonl"

State = dict[str, dict[str, Any]]


def apply_event(state: State, event: dict[str, Any]) -> State:
    """Fold one event dict into the projection. Returns a new state."""
    event_type = event.get("event_type")
    payload = event.get("payload") or {}
    observed_at = event.get("observed_at")

    def _updated(mid: str, **fields: Any) -> State:
        new_state = dict(state)
        entry = dict(new_state.get(mid) or {})
        entry.update(fields)
        new_state[mid] = entry
        return new_state

    if event_type == "memory_reviewed":
        memory_id = payload.get("memory_id")
        if not memory_id:
            return state
        count = (state.get(memory_id) or {}).get("review_count", 0)
        return _updated(
            memory_id,
            last_verdict=payload.get("verdict"),
            verdict_editor=payload.get("editor"),
            reviewed_at=observed_at,
            review_count=count + 1,
        )

    if event_type == "memory_updated":
        memory_id = payload.get("memory_id")
        if not memory_id:
            return state
        return _updated(memory_id, updated_at=observed_at)

    if event_type == "memory_pruned":
        new_state = state
        for memory_id in payload.get("memory_ids") or []:
            entry = dict(new_state.get(memory_id) or {})
            entry["pruned_at"] = observed_at
            new_state = {**new_state, memory_id: entry}
        return new_state

    return state


def rebuild(memory_dir: Path | str) -> State:
    """Fold the full event log into a fresh projection."""
    events_path = Path(memory_dir) / EVENTS_FILENAME
    if not events_path.exists():
        return {}

    state: State = {}
    with events_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                logger.warning("rebuild: skipping malformed event line: %.200s", line)
                continue
            state = apply_event(state, event)
    return state
