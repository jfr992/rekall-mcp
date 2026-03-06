"""Workspace scanner for local Git repositories."""

from __future__ import annotations

from pathlib import Path


class WorkspaceScanner:
    """Scans configured root directories for git repositories."""

    def __init__(self, roots: list[str] | None = None, max_depth: int = 3) -> None:
        self._roots = roots or []
        self._max_depth = max_depth

    def scan(self) -> list[dict[str, str]]:
        """Scan all roots for directories containing .git, up to max_depth."""
        workspaces: list[dict[str, str]] = []
        seen: set[str] = set()
        for root_str in self._roots:
            root = Path(root_str).expanduser()
            if not root.is_dir():
                continue
            self._scan_dir(root, 1, workspaces, seen)
        workspaces.sort(key=lambda w: w["name"].lower())
        return workspaces

    def _scan_dir(self, directory: Path, depth: int, results: list[dict[str, str]], seen: set[str]) -> None:
        if depth > self._max_depth:
            return
        try:
            children = sorted(directory.iterdir())
        except PermissionError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / ".git").exists():
                path_str = str(child)
                if path_str not in seen:
                    seen.add(path_str)
                    results.append({"name": child.name, "path": path_str})
            else:
                self._scan_dir(child, depth + 1, results, seen)
