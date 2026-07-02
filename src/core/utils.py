"""Shared utilities for the core module."""

from __future__ import annotations

import hashlib
import os


def rekall_env(name: str, default: str | None = None) -> str | None:
    """Read a REKALL_<name> env var."""
    return os.environ.get(f"REKALL_{name}") or default


def stable_hash_id(string_id: str) -> int:
    """Convert a string ID to a stable positive int64, suitable for Qdrant point IDs.

    Uses SHA-256 truncated to 8 bytes, modulo 2^63 to guarantee:
    - Deterministic across processes (unlike Python's hash())
    - Positive (Qdrant requires non-negative IDs)
    - Within int64 range

    Args:
        string_id: Any string identifier.

    Returns:
        Positive integer in range [0, 2^63).
    """
    hash_bytes = hashlib.sha256(string_id.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big") % (2**63)
