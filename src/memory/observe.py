"""Observation pipeline for automatic memory capture.

Turns raw agent observations into high-signal persisted memories by:
- normalizing content
- estimating salience
- classifying type
- rejecting low-signal noise
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "decision": ("decided", "chose", "going with", "opted for", "selected"),
    "learning": ("fixed", "discovered", "learned", "bug", "issue", "root cause"),
    "preference": ("prefer", "prefers", "likes", "wants", "default"),
    "requirement": ("must", "required", "cannot", "has to", "mandatory"),
    "fact": ("runs on", "located", "uses", "endpoint", "port"),
}

LOW_SIGNAL_PATTERNS = (
    "working on",
    "opened file",
    "ran command",
    "trying",
    "exploring",
    "maybe",
    "possibly",
    "temporary",
)


@dataclass(frozen=True, slots=True)
class ObservationCandidate:
    content: str
    memory_type: str
    salience: float
    should_save: bool
    reason: str = ""


class ObservationEngine:
    """Low-noise observation classifier with salience scoring."""

    def __init__(self, classifier: Callable[[str], str] | None = None) -> None:
        self._classifier = classifier

    def evaluate(self, summary: str, memory_type: str = "auto") -> ObservationCandidate:
        normalized = " ".join((summary or "").strip().split())
        if not normalized:
            return ObservationCandidate("", "learning", 0.0, False, "empty")

        lowered = normalized.lower()
        if any(pattern in lowered for pattern in LOW_SIGNAL_PATTERNS):
            return ObservationCandidate(normalized, "learning", 0.15, False, "low-signal")

        inferred = memory_type if memory_type != "auto" else self._infer_type(normalized)
        salience = self._score(normalized, inferred)
        should_save = salience >= 0.45
        reason = "salient" if should_save else "below-threshold"

        return ObservationCandidate(
            content=normalized,
            memory_type=inferred,
            salience=salience,
            should_save=should_save,
            reason=reason,
        )

    def _infer_type(self, summary: str) -> str:
        if self._classifier is not None:
            try:
                return self._classifier(summary)
            except Exception:
                pass

        lowered = summary.lower()
        for memory_type, hints in TYPE_HINTS.items():
            if any(hint in lowered for hint in hints):
                return memory_type
        return "learning"

    def _score(self, summary: str, memory_type: str) -> float:
        lowered = summary.lower()
        score = 0.25

        if len(summary) >= 32:
            score += 0.10
        if len(summary) >= 80:
            score += 0.05

        score += {
            "requirement": 0.35,
            "decision": 0.30,
            "preference": 0.25,
            "learning": 0.25,
            "fact": 0.20,
            "note": 0.10,
            "session": 0.15,
        }.get(memory_type, 0.10)

        if any(word in lowered for word in ["because", "so that", "root cause", "due to"]):
            score += 0.10
        if any(word in lowered for word in ["user", "jr", "claude", "codex"]):
            score += 0.05
        if any(word in lowered for word in ["bug", "decision", "requirement", "prefer"]):
            score += 0.05

        return min(score, 1.0)
