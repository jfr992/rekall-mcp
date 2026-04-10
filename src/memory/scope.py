"""Memory scope and agent identity helpers.

Defines a richer identity model than plain cwd-name project detection.
This is the foundation for Claude Code + Codex sharing one memory fabric
without contaminating unrelated repos or trust boundaries.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
    trust_boundary: str = "personal"
    session_id: str = ""

    def to_metadata(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in {"", None}}


class ScopeDetector:
    """Detect memory scope from environment and git context."""

    @staticmethod
    def detect(
        *,
        project: str | None = None,
        cwd: str | Path | None = None,
        agent: str | None = None,
        trust_boundary: str | None = None,
        session_id: str | None = None,
    ) -> MemoryScope:
        current = Path(cwd or os.getcwd()).resolve()
        workspace_root = str(current)

        repo_root = ScopeDetector._git(current, ["rev-parse", "--show-toplevel"])
        repo_name = Path(repo_root).name if repo_root else current.name
        branch = ScopeDetector._git(current, ["branch", "--show-current"])
        repo_remote = ScopeDetector._git(current, ["remote", "get-url", "origin"])

        detected_project = project or repo_name or current.name or "general"
        detected_agent = agent or os.environ.get("MEMENTO_AGENT") or ScopeDetector._detect_agent()
        detected_trust = trust_boundary or os.environ.get("MEMENTO_TRUST_BOUNDARY") or ScopeDetector._detect_trust_boundary(repo_remote, repo_name)
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

    @staticmethod
    def _detect_trust_boundary(repo_remote: str, repo_name: str) -> str:
        remote = (repo_remote or "").lower()
        name = (repo_name or "").lower()
        if any(token in remote or token in name for token in ["yum", "audacy"]):
            return name if name in {"yum", "audacy"} else "client"
        return "personal"

    @staticmethod
    def _git(cwd: Path, args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except Exception:
            return ""
