"""Trust boundary loader.

Reads ~/.claude/memory/trust.yaml (or $MEMENTO_MEMORY_DIR/trust.yaml) and
returns a TrustResolver. If the file is missing or malformed, every repo
resolves to 'personal'.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


DEFAULT_BOUNDARY = "personal"


@dataclass(frozen=True, slots=True)
class TrustBoundary:
    name: str
    remote_contains: tuple[str, ...] = ()
    name_contains: tuple[str, ...] = ()


def _memory_dir() -> Path:
    override = os.environ.get("MEMENTO_MEMORY_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "memory"


def load_trust_rules() -> list[TrustBoundary]:
    """Load trust rules from disk. Returns an empty list on missing/bad file."""
    path = _memory_dir() / "trust.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to parse trust.yaml; defaulting to personal", exc_info=True)
        return []

    if not isinstance(data, dict):
        return []

    boundaries_raw = data.get("boundaries") or []
    if not isinstance(boundaries_raw, list):
        return []

    result: list[TrustBoundary] = []
    for b in boundaries_raw:
        if not isinstance(b, dict):
            continue
        name = str(b.get("name") or "").strip()
        if not name:
            continue
        match = b.get("match") or {}
        if not isinstance(match, dict):
            match = {}
        remote_contains = match.get("remote_contains")
        name_contains = match.get("name_contains")

        def _tuple(value: Any) -> tuple[str, ...]:
            if value is None:
                return ()
            if isinstance(value, str):
                return (value.lower(),)
            if isinstance(value, (list, tuple)):
                return tuple(str(v).lower() for v in value)
            return ()

        result.append(TrustBoundary(
            name=name,
            remote_contains=_tuple(remote_contains),
            name_contains=_tuple(name_contains),
        ))
    return result


class TrustResolver:
    """Resolve a trust boundary for a (remote, name) pair."""

    def __init__(self, rules: list[TrustBoundary] | None = None) -> None:
        self._rules = rules or []

    def resolve(self, *, remote: str, name: str) -> str:
        remote_l = (remote or "").lower()
        name_l = (name or "").lower()
        for rule in self._rules:
            if any(tok in remote_l for tok in rule.remote_contains):
                return rule.name
            if any(tok in name_l for tok in rule.name_contains):
                return rule.name
        return DEFAULT_BOUNDARY
