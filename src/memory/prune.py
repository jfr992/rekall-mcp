"""Safe pruning from memory pressure signals.

Contract:
- `build_plan` returns a `PrunePlan` with a unique `plan_id`, a TTL, and a
  list of `PruneCandidate`s. Identity-tier is never selected. Memories
  without an explicit `salience` field are never selected. Memories
  adjacent to an identity-tier memory are never selected (neighborhood
  protection).
- `apply_plan(plan_id, confirm_plan_id)` requires a matching plan id and
  a non-expired plan. It deletes at most `MAX_DELETIONS_PER_APPLY` memories.
- The MCP tool surface only exposes `build_plan` (as `prune_plan`). Apply is
  REST-only, so agents cannot self-delete.

`plan_prune` and `apply_prune_plan` are kept as thin compat aliases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4


MAX_DELETIONS_PER_APPLY = 200
PLAN_TTL = timedelta(minutes=15)


class PlanNotFound(Exception):
    pass


class PlanExpired(Exception):
    pass


class PlanIdMismatch(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    memory_id: str
    tier: str
    reason: str
    age_days: int
    salience: float


@dataclass(frozen=True, slots=True)
class PrunePlan:
    plan_id: str
    project: str
    generated_at: datetime
    expires_at: datetime
    candidates: tuple[PruneCandidate, ...] = field(default_factory=tuple)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "project": self.project,
            "generated_at": self.generated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "summary": self.summary,
            "candidates": [
                {
                    "memory_id": c.memory_id,
                    "tier": c.tier,
                    "reason": c.reason,
                    "age_days": c.age_days,
                    "salience": c.salience,
                }
                for c in self.candidates
            ],
        }


_PLAN_STORE: dict[str, PrunePlan] = {}


def _age_days(date_str: str, *, now: datetime) -> int:
    try:
        return max(0, (now - datetime.strptime(date_str, "%Y-%m-%d")).days)
    except Exception:
        return 0


def build_plan(manager, *, project: str, limit: int = MAX_DELETIONS_PER_APPLY) -> PrunePlan:
    """Build a prune plan for `project`, storing it in `_PLAN_STORE`."""
    memories = manager.store.scroll(filters={"project": project}, limit=max(limit * 5, 200))
    now = datetime.now()

    # Collect ids of identity-tier memories for neighborhood protection.
    identity_ids: set[str] = set()
    for m in memories:
        if m.get("tier") == "identity":
            mid = m.get("memory_id")
            if mid:
                identity_ids.add(mid)

    def is_protected_neighbor(mid: str) -> bool:
        try:
            neighbors = manager.knowledge_graph.get_neighbors(mid, hops=1) or set()
        except Exception:
            return False
        return bool(neighbors & identity_ids)

    candidates: list[PruneCandidate] = []
    for m in memories:
        memory_id = m.get("memory_id", "")
        if not memory_id:
            continue

        tier = m.get("tier", "working")
        if tier == "identity":
            continue

        # SAFETY: memories without an explicit salience field are NEVER prunable.
        if "salience" not in m:
            continue

        salience = float(m.get("salience") or 0.0)
        if salience > 0.25:
            continue

        reinforcement = int(m.get("reinforcement_count") or 0)
        if reinforcement > 0:
            continue

        age = _age_days(m.get("date", ""), now=now)
        if age < 7:
            continue

        if is_protected_neighbor(memory_id):
            continue

        candidates.append(PruneCandidate(
            memory_id=memory_id,
            tier=tier,
            reason=f"tier={tier} salience={salience:.2f} age={age}d",
            age_days=age,
            salience=salience,
        ))

        if len(candidates) >= limit:
            break

    plan = PrunePlan(
        plan_id=uuid4().hex,
        project=project,
        generated_at=now,
        expires_at=now + PLAN_TTL,
        candidates=tuple(candidates),
        summary=f"{len(candidates)} candidates (max {limit})",
    )
    _PLAN_STORE[plan.plan_id] = plan
    return plan


def apply_plan(manager, *, plan_id: str, confirm_plan_id: str) -> dict[str, Any]:
    """Delete candidates from a previously-built plan.

    Requires `confirm_plan_id == plan_id`. Plan must not be expired.
    Hard-capped at MAX_DELETIONS_PER_APPLY.
    """
    plan = _PLAN_STORE.get(plan_id)
    if plan is None:
        raise PlanNotFound(f"Plan not found: {plan_id}")
    if plan_id != confirm_plan_id:
        raise PlanIdMismatch("confirm_plan_id does not match plan_id")
    if datetime.now() > plan.expires_at:
        _PLAN_STORE.pop(plan_id, None)
        raise PlanExpired(f"Plan expired at {plan.expires_at.isoformat()}")

    deleted: list[str] = []
    skipped: list[str] = []

    for i, candidate in enumerate(plan.candidates):
        if i >= MAX_DELETIONS_PER_APPLY:
            skipped.append(candidate.memory_id)
            continue
        try:
            if manager.delete(candidate.memory_id):
                deleted.append(candidate.memory_id)
            else:
                skipped.append(candidate.memory_id)
        except Exception:  # noqa: BLE001
            skipped.append(candidate.memory_id)

    _PLAN_STORE.pop(plan_id, None)  # one-shot; plan is consumed on apply
    return {
        "plan_id": plan_id,
        "deleted": deleted,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Legacy compat aliases — kept so unrelated callers don't break.
# ---------------------------------------------------------------------------


def plan_prune(memories: list[dict[str, Any]], *, aggressive: bool = False) -> dict[str, Any]:
    """Legacy entrypoint — returns a dict-shaped plan for old callers.

    Respects the unknown-salience exemption even in legacy callers.
    """
    selected: list[dict[str, Any]] = []
    for m in memories:
        if m.get("tier") != "working":
            continue
        if "salience" not in m:
            continue
        salience = float(m.get("salience") or 0.0)
        threshold = 0.45 if aggressive else 0.25
        if salience <= threshold:
            selected.append(m)
    return {
        "selected": selected,
        "selected_count": len(selected),
        "aggressive": aggressive,
    }


def apply_prune_plan(manager, prune_plan: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    """Legacy entrypoint — dict-shaped apply, kept for old callers."""
    selected = prune_plan.get("selected", [])
    deleted: list[str] = []
    for m in selected:
        memory_id = m.get("memory_id")
        if not memory_id:
            continue
        if dry_run:
            deleted.append(memory_id)
            continue
        try:
            if manager.delete(memory_id):
                deleted.append(memory_id)
        except Exception:  # noqa: BLE001
            pass
    return {
        "dry_run": dry_run,
        "selected_count": len(selected),
        "deleted_count": len(deleted),
        "memory_ids": deleted,
    }
