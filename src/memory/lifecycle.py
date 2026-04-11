"""Memory lifecycle and behavioral tiering.

Tiers are computed from a small set of behavioral signals, not a pure
type->tier lookup. A frequently-reinforced note promotes to semantic; a
contradicted decision demotes one tier. Identity tier is sacred — only
reachable via explicit `save(tier="identity")`.

Tiers:
- working:  recent/low-confidence scratch
- episodic: session/time-anchored events
- semantic: durable facts/decisions
- identity: stable user/agent preferences (explicit only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Tier = Literal["working", "episodic", "semantic", "identity"]

_TIER_ORDER: tuple[Tier, ...] = ("working", "episodic", "semantic", "identity")
_TIER_WEIGHT: dict[Tier, float] = {
    "working": 0.0,
    "episodic": 0.33,
    "semantic": 0.66,
    "identity": 1.0,
}

# Type-default tier used as the starting point before behavioral adjustments.
_TYPE_DEFAULT_TIER: dict[str, Tier] = {
    "requirement": "semantic",
    "decision": "semantic",
    "fact": "semantic",
    "preference": "semantic",   # identity only via explicit_tier
    "learning": "episodic",
    "session": "episodic",
    "note": "working",
}


@dataclass(frozen=True, slots=True)
class LifecycleSignals:
    """Inputs to the lifecycle classifier."""

    memory_type: str
    salience: float
    age_days: int
    reinforcement_count: int
    contradicts_count: int
    explicit_tier: Tier | None = None


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    """Output of the lifecycle classifier."""

    tier: Tier
    durability: float
    reason: str


def _demote(tier: Tier) -> Tier:
    idx = _TIER_ORDER.index(tier)
    return _TIER_ORDER[max(idx - 1, 0)]


def classify(signals: LifecycleSignals) -> LifecycleResult:
    """Classify a memory's tier and durability from behavioral signals."""

    # Rule 1: identity is sacred
    if signals.explicit_tier == "identity":
        return LifecycleResult(
            tier="identity",
            durability=1.0,
            reason="explicit identity tier",
        )

    start: Tier = signals.explicit_tier or _TYPE_DEFAULT_TIER.get(signals.memory_type, "working")
    tier: Tier = start
    reasons: list[str] = [f"type={signals.memory_type} -> {start}"]

    # Rule 2: reinforced + aged notes/facts/learnings promote to semantic
    if (
        signals.memory_type in {"note", "fact", "learning"}
        and signals.reinforcement_count >= 5
        and signals.age_days >= 7
    ):
        tier = "semantic"
        reasons.append(f"reinforced x{signals.reinforcement_count} + age {signals.age_days}d -> promoted to semantic")

    # Rule 3: high-salience decisions/requirements stay at semantic
    if signals.memory_type in {"decision", "requirement"} and signals.salience >= 0.6:
        tier = "semantic"
        reasons.append(f"salience {signals.salience:.2f} -> held at semantic")

    # Rule 4: contradictions demote one tier (never below working)
    if signals.contradicts_count >= 2:
        before = tier
        tier = _demote(tier)
        reasons.append(f"contradicts x{signals.contradicts_count} -> demoted {before} -> {tier}")

    # Durability: 4 equal-weight quarters
    contradicts_penalty = min(signals.contradicts_count * 0.25, 1.0)
    reinforcement_weight = min(signals.reinforcement_count * 0.2, 1.0)
    durability = (
        0.25 * _TIER_WEIGHT[tier]
        + 0.25 * max(0.0, min(signals.salience, 1.0))
        + 0.25 * (1.0 - contradicts_penalty)
        + 0.25 * reinforcement_weight
    )

    return LifecycleResult(
        tier=tier,
        durability=round(max(0.0, min(durability, 1.0)), 4),
        reason="; ".join(reasons),
    )


# ---------------------------------------------------------------------------
# Backward-compat shim: existing callers still call `summarize_lifecycle(payload)`.
# ---------------------------------------------------------------------------


def summarize_lifecycle(memory: dict[str, Any]) -> dict[str, Any]:
    """Backward-compat wrapper returning the new payload fields.

    Existing callers in `manager.save` continue to invoke this and get
    tier + durability + retention_days + lifecycle_reason in one dict.
    """
    signals = LifecycleSignals(
        memory_type=memory.get("type", "note"),
        salience=float(memory.get("salience") or 0.0),
        age_days=int(memory.get("age_days") or 0),
        reinforcement_count=int(memory.get("reinforcement_count") or 0),
        contradicts_count=int(memory.get("contradicts_count") or 0),
        explicit_tier=memory.get("tier"),
    )
    result = classify(signals)
    return {
        "tier": result.tier,
        "durability": result.durability,
        "lifecycle_reason": result.reason,
        "retention_days": compute_retention_days(signals.memory_type, result.tier),
    }


# ---------------------------------------------------------------------------
# Temporary stubs — Task 2 will replace these with proper compat shims.
# They exist here solely to keep the import chain alive until then.
# ---------------------------------------------------------------------------


def determine_tier(memory_type: str, content: str = "", salience: float = 0.0) -> str:
    """Stub: delegates to classify(). Task 2 will formalize this shim."""
    signals = LifecycleSignals(
        memory_type=memory_type,
        salience=salience,
        age_days=0,
        reinforcement_count=0,
        contradicts_count=0,
        explicit_tier=None,
    )
    return classify(signals).tier


def promote_memory(current_tier: str, memory_type: str, access_count: int, salience: float) -> str:
    """Stub: delegates to classify(). Task 2 will formalize this shim."""
    signals = LifecycleSignals(
        memory_type=memory_type,
        salience=salience,
        age_days=0,
        reinforcement_count=access_count,
        contradicts_count=0,
        explicit_tier=current_tier if current_tier == "identity" else None,
    )
    return classify(signals).tier


def compute_retention_days(memory_type: str, tier: str) -> int:
    """Retention hint for pressure/prune heuristics. Unchanged semantics."""
    if tier == "identity":
        return 3650
    if tier == "semantic":
        return 365
    if tier == "episodic":
        return 90
    if memory_type == "note":
        return 14
    return 30
