"""Shared utilities for the core module."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

# Hostnames the docker compose test profile uses for the disposable Qdrant.
_TEST_QDRANT_HOSTNAMES = {"qdrant-test", "rekall-qdrant-test"}


def is_prod_qdrant_url(url: str) -> bool:
    """True when the URL points at production Qdrant (:6333 outside the test allowlist)."""
    parsed = urlparse(url)
    port = parsed.port or 6333
    return port == 6333 and parsed.hostname not in _TEST_QDRANT_HOSTNAMES


def _prod_storage_paths() -> list[Path]:
    paths = [(Path.home() / ".claude" / "memory").resolve()]
    env_prod = os.environ.get("MEMORY_STORAGE_PATH")
    if env_prod:
        candidate = Path(env_prod).expanduser().resolve()
        # tmp is never prod — tests routinely point MEMORY_STORAGE_PATH at tmp_path
        tmp_roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
        if not any(candidate.is_relative_to(root) for root in tmp_roots):
            paths.append(candidate)
    return paths


def assert_not_prod(
    qdrant_url: str | None = None,
    storage_path: Path | str | None = None,
    qdrant_path: Path | str | None = None,
) -> None:
    """Refuse prod targets. Raises RuntimeError — there is no override flag."""
    if qdrant_url is not None and is_prod_qdrant_url(qdrant_url):
        raise RuntimeError(f"prod Qdrant refused: {qdrant_url}")
    if storage_path is not None:
        resolved = Path(storage_path).expanduser().resolve()
        for prod in _prod_storage_paths():
            if resolved.is_relative_to(prod):
                raise RuntimeError(f"prod storage refused: {resolved}")
    candidate = qdrant_path or os.environ.get("QDRANT_PATH")
    if candidate:
        resolved = Path(candidate).expanduser().resolve()
        home = Path.home().resolve()
        for prod in (home / ".rekall", home / ".claude"):
            if resolved.is_relative_to(prod):
                raise RuntimeError(f"prod embedded Qdrant path refused: {resolved}")


def assert_test_isolation(
    *,
    qdrant_url: str | None = None,
    storage_path: Path | str | None = None,
    qdrant_path: Path | str | None = None,
) -> None:
    """Under pytest (PYTEST_VERSION set), refuse prod storage/Qdrant targets."""
    if "PYTEST_VERSION" not in os.environ:
        return
    try:
        assert_not_prod(qdrant_url=qdrant_url, storage_path=storage_path, qdrant_path=qdrant_path)
    except RuntimeError as exc:
        raise RuntimeError(
            f"test-isolation guard: {exc}. Tests must use tmp_path storage and the "
            "disposable Qdrant on localhost:6334 (see tests/conftest.py)."
        ) from None


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
