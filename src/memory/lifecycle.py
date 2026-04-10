"""Memory lifecycle and tiering.

Moves the system from flat saved facts toward a more brain-like hierarchy:
- working memory: recent/highly active context
- episodic memory: session/project events
- semantic memory: durable facts/decisions/preferences
- identity memory: user/agent preferences and stable traits
"""

from __future__ import annotations

from typing import Any


TIER_RULES = {
    "requirement": "semantic",
    "decision": "semantic",
    "fact": "semantic",
    "preference": "identity",
    "learning": "episodic",
    "session": "episodic",
    "note": "working",
}


def determine_tier(memory_type: str, content: str = "", salience: float = 0.0) -> str:
    tier = TIER_RULES.get(memory_type, "working")
    lowered = (content or "").lower()

    if memory_type == "learning" and salience >= 0.8:
        return "semantic"
    if memory_type == "note" and salience >= 0.7:
        return "episodic"
    if any(token in lowered for token in ["jr prefers", "user prefers", "default style", "always call"]):
        return "identity"

    return tier


def compute_retention_days(memory_type: str, tier: str) -> int:
    if tier == "identity":
        return 3650
    if tier == "semantic":
        return 365
    if tier == "episodic":
        return 90
    if memory_type == "note":
        return 14
    return 30


def promote_memory(current_tier: str, memory_type: str, access_count: int, salience: float) -> str:
    if current_tier == "identity":
        return current_tier
    if current_tier == "working" and (access_count >= 3 or salience >= 0.85):
        return "episodic" if memory_type in {"learning", "note", "session"} else "semantic"
    if current_tier == "episodic" and (access_count >= 5 or salience >= 0.90):
        return "semantic" if memory_type != "preference" else "identity"
    if memory_type == "preference" and access_count >= 2:
        return "identity"
    return current_tier


def summarize_lifecycle(memory: dict[str, Any]) -> dict[str, Any]:
    memory_type = memory.get("type", "note")
    salience = float(memory.get("salience", 0.0) or 0.0)
    access_count = int(memory.get("access_count", 0) or 0)
    current_tier = memory.get("tier") or determine_tier(memory_type, memory.get("content", ""), salience)
    promoted_tier = promote_memory(current_tier, memory_type, access_count, salience)

    return {
        "tier": promoted_tier,
        "retention_days": compute_retention_days(memory_type, promoted_tier),
    }
