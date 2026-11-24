"""Capsule, startup, and events resolve project from a cwd worktree path."""

import subprocess
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _worktree(tmp_path):
    main = tmp_path / "demo-repo"
    main.mkdir()
    _git(main, "init", "-b", "main")
    _git(main, "config", "user.email", "dev@example.com")
    _git(main, "config", "user.name", "Dev")
    (main / "README").write_text("init\n")
    _git(main, "add", "README")
    _git(main, "commit", "-m", "init")
    worktree = tmp_path / "demo-repo-feature"
    _git(main, "worktree", "add", "-b", "feature", str(worktree))
    return worktree


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    import server
    from memory.scope import ScopeDetector

    ScopeDetector.reset_trust_cache()
    manager = MagicMock()
    manager.get_project_capsule.return_value = {"project": "demo-repo", "memories": []}
    manager.get_agent_startup.return_value = {"startup_summary": "ok"}
    manager.record_event.return_value = None
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_capsule_cwd_resolves_worktree_to_main_repo(tmp_path, client):
    tc, manager = client
    worktree = _worktree(tmp_path)

    r = tc.get(f"/api/memory/capsule?cwd={quote(str(worktree))}")

    assert r.status_code == 200
    manager.get_project_capsule.assert_called_once()
    assert manager.get_project_capsule.call_args.kwargs["project"] == "demo-repo"


def test_startup_cwd_resolves_worktree_to_main_repo(tmp_path, client):
    tc, manager = client
    worktree = _worktree(tmp_path)

    r = tc.get(f"/api/memory/context/startup?cwd={quote(str(worktree))}&agent=claude-code&limit=8")

    assert r.status_code == 200
    manager.get_agent_startup.assert_called_once()
    assert manager.get_agent_startup.call_args.kwargs["project"] == "demo-repo"


def test_events_cwd_resolves_worktree_to_main_repo(tmp_path, client):
    tc, manager = client
    worktree = _worktree(tmp_path)

    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "s",
            "cwd": str(worktree),
            "recalled_ids": [],
        },
    )

    assert r.status_code == 200
    manager.record_event.assert_called()
    assert manager.record_event.call_args.kwargs["project"] == "demo-repo"
