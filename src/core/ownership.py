"""Single-owner, multi-consumer ownership protocol for the embedded store.

Probe the daemon first, fall back to embedded, record the active backend,
refuse mismatches loudly (spec: portability design rev 3).
"""

from __future__ import annotations

import atexit
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

ACTIVE_BACKEND_FILE = "active-backend.json"


class RekallOwnershipError(RuntimeError):
    """Base for ownership-protocol refusals."""


class RekallDaemonRunningError(RekallOwnershipError):
    """A rekall daemon owns the store — route through it or stop it."""


class ForeignServiceError(RekallOwnershipError):
    """Something unsigned answers on the configured port — never fall through."""


class RekallStoreLockedError(RekallOwnershipError):
    """Another process holds the embedded store's flock."""


@dataclass(frozen=True)
class Acquisition:
    mode: Literal["daemon", "embedded", "url"]
    base_url: str | None = None
    path: Path | None = None
    qdrant_url: str | None = None
    # Embedded mode: the live QdrantClient whose flock IS the store lock.
    # Callers must reuse it (a second client on the same path is refused).
    client: Any = None


def probe_daemon(base_url: str, timeout: float = 1.5) -> Literal["rekall", "foreign", "absent"]:
    """Classify whatever answers on base_url/health.

    Anything that answers without the rekall signature is "foreign" — we never
    fall through to embedded against a responding port (split-brain guard).
    """
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
    except httpx.HTTPError:
        return "absent"
    try:
        body = response.json()
    except ValueError:
        return "foreign"
    if isinstance(body, dict) and body.get("server") == "rekall":
        return "rekall"
    return "foreign"


def write_active_backend(
    rekall_dir: Path, backend: str, target: str, daemon_url: str | None = None
) -> None:
    """Record who owns the store: {backend, target, pid, written_at[, daemon_url]}."""
    rekall_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "backend": backend,
        "target": target,
        "pid": os.getpid(),
        "written_at": datetime.now(UTC).isoformat(),
    }
    if daemon_url:
        record["daemon_url"] = daemon_url
    (rekall_dir / ACTIVE_BACKEND_FILE).write_text(json.dumps(record))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError, ValueError):
        return True  # exists (or unknowable) — treat as alive, never take over
    return True


def _recorded_owner_alive(record: dict) -> bool:
    if record.get("backend") == "url":
        # target is the Qdrant URL; the owning daemon answers on daemon_url
        # (older records put the daemon URL in target — probe that as fallback).
        probe_target = str(record.get("daemon_url") or record.get("target", ""))
        if probe_daemon(probe_target) == "rekall":
            return True
    return _pid_alive(int(record.get("pid", -1)))


def check_active_backend(
    rekall_dir: Path, want_backend: str, want_target: str
) -> Literal["ok", "stale-taken-over", "mismatch"]:
    """Reconcile the recorded owner with what we want to run.

    Mismatch + dead recorded owner ⇒ overwrite and report "stale-taken-over"
    (a stale file can never brick startup). Mismatch + alive ⇒ "mismatch".
    """
    state_file = rekall_dir / ACTIVE_BACKEND_FILE
    if not state_file.exists():
        return "ok"
    try:
        record = json.loads(state_file.read_text())
        assert isinstance(record, dict)
    except (ValueError, AssertionError):
        record = {}  # corrupt file — staleness rule decides below
    if record.get("backend") == want_backend and record.get("target") == want_target:
        return "ok"
    if record and _recorded_owner_alive(record):
        return "mismatch"
    logger.info("stale active-backend.json (owner gone) — taking over: %s", state_file)
    write_active_backend(rekall_dir, want_backend, want_target)
    return "stale-taken-over"


def _open_embedded_store(qdrant_path: Path) -> Any:
    """Construct the real embedded client — holding qdrant's flock IS the lock.

    Probe-and-release would leave a window where two fresh processes both pass
    and both record ownership; the winner's client is created here and handed
    to the caller so lock precedes record with no gap.
    """
    from qdrant_client import QdrantClient

    from core.utils import assert_test_isolation

    assert_test_isolation(qdrant_path=str(qdrant_path))
    try:
        return QdrantClient(path=str(qdrant_path))
    except RuntimeError as exc:
        if "already accessed" not in str(exc):
            raise
        raise RekallStoreLockedError(
            "another rekall process owns the local store — close it, or run "
            "`rekall serve` once so all sessions share one daemon."
        ) from None


def release(rekall_dir: Path) -> None:
    """Remove our active-backend record (clean shutdown; atexit target)."""
    state_file = rekall_dir / ACTIVE_BACKEND_FILE
    try:
        if json.loads(state_file.read_text()).get("pid") == os.getpid():
            state_file.unlink()
    except (OSError, ValueError):
        pass  # missing/corrupt/foreign file — leave it to the staleness rule


def acquire(rekall_dir: Path, port: int, qdrant_url: str | None = None) -> Acquisition:
    """The single integration point: probe, route/refuse, lock, record.

    qdrant_url set = server-backed store: no embedded flock, the record says
    {backend: "url", target: <qdrant_url>} so embedded acquires on the same
    YAML refuse while this owner lives (and vice versa).
    """
    base_url = f"http://127.0.0.1:{port}"
    state = probe_daemon(base_url)
    if state == "rekall":
        return Acquisition(mode="daemon", base_url=base_url)
    if state == "foreign":
        raise ForeignServiceError(
            f"something is serving on {base_url} that isn't a recognizable rekall — "
            "if it's an older rekall, upgrade it; otherwise set PORT."
        )
    client = None
    if qdrant_url:
        backend, target = "url", qdrant_url
    else:
        qdrant_path = rekall_dir / "qdrant"
        client = _open_embedded_store(qdrant_path)  # lock BEFORE record
        backend, target = "embedded", str(qdrant_path)
    if check_active_backend(rekall_dir, backend, target) == "mismatch":
        if client is not None:
            client.close()
        raise RekallDaemonRunningError(
            "a live rekall owns this store through another backend "
            f"(see {rekall_dir / ACTIVE_BACKEND_FILE}) — use it, or stop it first."
        )
    write_active_backend(rekall_dir, backend, target, daemon_url=base_url if qdrant_url else None)
    atexit.register(release, rekall_dir)
    if qdrant_url:
        return Acquisition(mode="url", qdrant_url=qdrant_url)
    return Acquisition(mode="embedded", path=qdrant_path, client=client)
