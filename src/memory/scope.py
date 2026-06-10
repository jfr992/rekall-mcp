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

from memory.trust import DEFAULT_BOUNDARY, TrustResolver, load_trust_rules

_CRED_RE = re.compile(r"(https?://)[^@/]+@")


def _strip_creds(url: str | None) -> str:
    """Remove user:token@ from HTTPS remote URLs. Leaves SSH/git URLs alone."""
    if not url:
        return ""
    return _CRED_RE.sub(r"\1", url)


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


@lru_cache(maxsize=32)
def _git_info(cwd: str) -> tuple[str, str, str]:
    """Cached (repo_root, branch, repo_remote) for a cwd."""
    return (
        _git(cwd, ["rev-parse", "--show-toplevel"]),
        _git(cwd, ["branch", "--show-current"]),
        _git(cwd, ["remote", "get-url", "origin"]),
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

        repo_root, branch, raw_remote = _git_info(str(current))
        repo_name = Path(repo_root).name if repo_root else current.name
        repo_remote = _strip_creds(raw_remote)

        detected_project = project or repo_name or current.name or "general"
        detected_agent = agent or os.environ.get("MEMENTO_AGENT") or cls._detect_agent()
        detected_trust = (
            trust_boundary
            or os.environ.get("MEMENTO_TRUST_BOUNDARY")
            or cls._trust_resolver().resolve(remote=repo_remote, name=repo_name)
        )
        detected_session = session_id or os.environ.get("MEMENTO_SESSION_ID", "")

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
