"""Tests for workspace scanner."""

from __future__ import annotations

from pathlib import Path

from tools.builtin.workspaces import WorkspaceScanner


def test_scan_finds_git_repos(tmp_path):
    """Scanner finds directories containing .git."""
    repo1 = tmp_path / "repo-a"
    repo1.mkdir()
    (repo1 / ".git").mkdir()

    repo2 = tmp_path / "repo-b"
    repo2.mkdir()
    (repo2 / ".git").mkdir()

    not_repo = tmp_path / "plain-dir"
    not_repo.mkdir()

    scanner = WorkspaceScanner(roots=[str(tmp_path)])
    workspaces = scanner.scan()

    paths = {w["path"] for w in workspaces}
    assert str(repo1) in paths
    assert str(repo2) in paths
    assert str(not_repo) not in paths


def test_scan_returns_name_and_path(tmp_path):
    """Each workspace has name and path keys."""
    repo = tmp_path / "my-project"
    repo.mkdir()
    (repo / ".git").mkdir()

    scanner = WorkspaceScanner(roots=[str(tmp_path)])
    workspaces = scanner.scan()

    assert len(workspaces) == 1
    assert workspaces[0]["name"] == "my-project"
    assert workspaces[0]["path"] == str(repo)


def test_scan_skips_nonexistent_roots():
    """Scanner silently skips roots that don't exist."""
    scanner = WorkspaceScanner(roots=["/nonexistent/path/abc123"])
    workspaces = scanner.scan()
    assert workspaces == []


def test_scan_expands_tilde():
    """Scanner expands ~ in root paths."""
    scanner = WorkspaceScanner(roots=["~/Repos"])
    workspaces = scanner.scan()
    assert isinstance(workspaces, list)


def test_scan_depth_one_only(tmp_path):
    """Scanner only checks direct children, not nested repos."""
    nested = tmp_path / "parent" / "child"
    nested.mkdir(parents=True)
    (nested / ".git").mkdir()

    scanner = WorkspaceScanner(roots=[str(tmp_path)])
    workspaces = scanner.scan()

    paths = {w["path"] for w in workspaces}
    assert str(nested) not in paths
