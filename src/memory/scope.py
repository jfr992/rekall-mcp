"""Memory scope and agent identity helpers.

Defines a richer identity model than plain cwd-name project detection.
Trust boundaries are resolved via ~/.claude/memory/trust.yaml (optional).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from core import rekall_env
from memory.trust import DEFAULT_BOUNDARY, TrustResolver, load_trust_rules

_PROJECT_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_project(name: str) -> str:
    cleaned = _PROJECT_UNSAFE.sub("-", name.strip()).strip("-")[:64]
    return "general" if not cleaned.strip(".") else cleaned


_CRED_RE = re.compile(r"(https?://)[^@/]+@")

# Session artifacts, not projects: timestamp-shaped dirs (20260708-091227),
# pure-numeric dirs, and tmp-style scratch names.
_JUNK_PROJECT_RE = re.compile(r"^(\d{8}-\d{6}|\d+|tmp[\w.-]*|scratch[\w.-]*)$", re.IGNORECASE)


def _is_junk_project_name(name: str) -> bool:
    return bool(_JUNK_PROJECT_RE.match(name))


def _strip_creds(url: str | None) -> str:
    """Remove user:token@ from HTTPS remote URLs. Leaves SSH/git URLs alone."""
    if not url:
        return ""
    return _CRED_RE.sub(r"\1", url)


def strip_remote_creds(url: str | None) -> str | None:
    """Like _strip_creds but preserves None (does not coerce None to empty string)."""
    if url is None:
        return None
    return _strip_creds(url)


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Identity envelope for a memory operation."""

    agent: str = "unknown"
    project: str = "general"
    workspace_root: str = ""
    repo_root: str = ""
    repo_name: str = ""
    repo_remote: str = ""
    branch: str = ""
    trust_boundary: str = DEFAULT_BOUNDARY
    session_id: str = ""

    def to_metadata(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in {"", None}}


def _origin_repo_name(remote: str) -> str:
    """Last path segment of origin, with credentials and a trailing .git removed."""
    if not remote:
        return ""
    cleaned = _strip_creds(remote).rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]
    if "/" in cleaned:
        name = cleaned.rsplit("/", 1)[-1]
    elif ":" in cleaned:
        name = cleaned.rsplit(":", 1)[-1]
    else:
        name = cleaned
    return normalize_project(name) if name else ""


def _main_checkout_name(common_dir: str, repo_root: str, cwd: str) -> str:
    """Directory name of the main checkout, from --git-common-dir."""
    if not common_dir:
        return Path(repo_root or cwd).name
    path = Path(common_dir)
    if not path.is_absolute():
        base = Path(repo_root) if repo_root else Path(cwd)
        path = (
            (base / ".git").resolve()
            if common_dir in {".git", "./.git"}
            else (Path(cwd) / path).resolve()
        )
    else:
        path = path.resolve()
    if path.name == ".git":
        return path.parent.name
    if path.name.endswith(".git"):
        return path.stem
    return path.name


def _preferred_repo_name(checkout_name: str, origin_name: str) -> str:
    """Prefer origin when it matches the checkout name or is a prefix of it."""
    checkout = normalize_project(checkout_name)
    origin = normalize_project(origin_name) if origin_name else ""
    if origin and (
        checkout == origin or checkout.startswith(origin + "-") or checkout.startswith(origin + "_")
    ):
        return origin
    return checkout


@lru_cache(maxsize=32)
def _git_info(cwd: str) -> tuple[str, str, str, str]:
    """Cached (repo_root, branch, repo_remote, git_common_dir) for a cwd."""
    common = _git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if not common:
        common = _git(cwd, ["rev-parse", "--git-common-dir"])
    return (
        _git(cwd, ["rev-parse", "--show-toplevel"]),
        _git(cwd, ["branch", "--show-current"]),
        _git(cwd, ["remote", "get-url", "origin"]),
        common,
    )


def _git(cwd: str, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


class ScopeDetector:
    """Detect memory scope from environment and git context."""

    _resolver: TrustResolver | None = None

    @classmethod
    def _trust_resolver(cls) -> TrustResolver:
        if cls._resolver is None:
            cls._resolver = TrustResolver(load_trust_rules())
        return cls._resolver

    @classmethod
    def reset_trust_cache(cls) -> None:
        cls._resolver = None
        _git_info.cache_clear()

    @classmethod
    def detect(
        cls,
        *,
        project: str | None = None,
        cwd: str | Path | None = None,
        agent: str | None = None,
        trust_boundary: str | None = None,
        session_id: str | None = None,
    ) -> MemoryScope:
        current = Path(cwd or os.getcwd()).resolve()
        workspace_root = str(current)

        repo_root, branch, raw_remote, common_dir = _git_info(str(current))
        repo_remote = _strip_creds(raw_remote)
        if repo_root:
            repo_name = _preferred_repo_name(
                _main_checkout_name(common_dir, repo_root, str(current)),
                _origin_repo_name(repo_remote),
            )
        else:
            repo_name = current.name

        if project:
            explicit = normalize_project(project)
            cwd_basename = normalize_project(current.name)
            worktree_basename = (
                normalize_project(Path(repo_root).name) if repo_root else cwd_basename
            )
            # An explicit project that is just the cwd/worktree folder is treated
            # as a mistaken hook value and resolved to the main repo name.
            if repo_root and explicit in {cwd_basename, worktree_basename}:
                detected_project = repo_name
            else:
                detected_project = explicit
        else:
            detected_project = normalize_project(repo_name or current.name or "general")
            if _is_junk_project_name(detected_project):
                detected_project = "general"
        detected_agent = agent or rekall_env("AGENT") or cls._detect_agent()
        detected_trust = (
            trust_boundary
            or rekall_env("TRUST_BOUNDARY")
            or cls._trust_resolver().resolve(remote=repo_remote, name=repo_name)
        )
        detected_session = session_id or rekall_env("SESSION_ID", "")

        return MemoryScope(
            agent=detected_agent,
            project=detected_project,
            workspace_root=workspace_root,
            repo_root=repo_root,
            repo_name=repo_name,
            repo_remote=repo_remote,
            branch=branch,
            trust_boundary=detected_trust,
            session_id=detected_session,
        )

    @staticmethod
    def _detect_agent() -> str:
        if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
            return "claude-code"
        if os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_ENV"):
            return "codex"
        return "unknown"
