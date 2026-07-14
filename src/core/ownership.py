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
from typing import Literal

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
    mode: Literal["daemon", "embedded"]
    base_url: str | None = None
    path: Path | None = None


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


def write_active_backend(rekall_dir: Path, backend: str, target: str) -> None:
    """Record who owns the store: {backend, target, pid, written_at}."""
    rekall_dir.mkdir(parents=True, exist_ok=True)
    (rekall_dir / ACTIVE_BACKEND_FILE).write_text(
        json.dumps(
            {
                "backend": backend,
                "target": target,
                "pid": os.getpid(),
                "written_at": datetime.now(UTC).isoformat(),
            }
        )
    )


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
        return probe_daemon(str(record.get("target", ""))) == "rekall"
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


def _assert_store_lock_free(qdrant_path: Path) -> None:
    """Try-and-release qdrant's own flock; translate contention to the ladder.

    The real guard stays qdrant's non-blocking flock at client construction —
    this probe just turns its raw exception into an actionable message.
    """
    lock_file = qdrant_path / ".lock"
    import portalocker

    try:
        handle = open(lock_file, "r+")
    except OSError:
        return  # no lock file — nothing holds the store
    with handle:
        try:
            portalocker.lock(
                handle, portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING
            )
        except portalocker.exceptions.LockException:
            raise RekallStoreLockedError(
                "another rekall process owns the local store — close it, or run "
                "`rekall serve` once so all sessions share one daemon."
            ) from None
        portalocker.unlock(handle)


def release(rekall_dir: Path) -> None:
    """Remove our active-backend record (clean shutdown; atexit target)."""
    state_file = rekall_dir / ACTIVE_BACKEND_FILE
    try:
        if json.loads(state_file.read_text()).get("pid") == os.getpid():
            state_file.unlink()
    except (OSError, ValueError):
        pass  # missing/corrupt/foreign file — leave it to the staleness rule


def acquire(rekall_dir: Path, port: int) -> Acquisition:
    """The single integration point: probe, route/refuse, lock, record."""
    base_url = f"http://127.0.0.1:{port}"
    state = probe_daemon(base_url)
    if state == "rekall":
        return Acquisition(mode="daemon", base_url=base_url)
    if state == "foreign":
        raise ForeignServiceError(
            f"something is serving on {base_url} that isn't a recognizable rekall — "
            "if it's an older rekall, upgrade it; otherwise set PORT."
        )
    qdrant_path = rekall_dir / "qdrant"
    _assert_store_lock_free(qdrant_path)
    if check_active_backend(rekall_dir, "embedded", str(qdrant_path)) == "mismatch":
        raise RekallDaemonRunningError(
            "a live rekall owns this store through another backend "
            f"(see {rekall_dir / ACTIVE_BACKEND_FILE}) — use it, or stop it first."
        )
    write_active_backend(rekall_dir, "embedded", str(qdrant_path))
    atexit.register(release, rekall_dir)
    return Acquisition(mode="embedded", path=qdrant_path)
