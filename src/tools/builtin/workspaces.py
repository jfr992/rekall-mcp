"""Workspace scanner for local Git repositories."""

from __future__ import annotations

from pathlib import Path


class WorkspaceScanner:
    """Scans configured root directories for git repositories."""

    def __init__(self, roots: list[str] | None = None) -> None:
        self._roots = roots or []

    def scan(self) -> list[dict[str, str]]:
        """Scan all roots for directories containing .git."""
        workspaces = []
        for root_str in self._roots:
            root = Path(root_str).expanduser()
            if not root.is_dir():
                continue

            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / ".git").exists():
                    workspaces.append({"name": child.name, "path": str(child)})

        return workspaces
