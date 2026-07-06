"""Ephemeral eval backend: never touches prod, seeds via the production write path."""

from pathlib import Path

import pytest

from benchmarks.eval.env import assert_not_prod


def test_refuses_prod_qdrant_port():
    with pytest.raises(RuntimeError, match="prod"):
        assert_not_prod("http://localhost:6333", Path("/tmp/eval-store"))


def test_refuses_prod_storage_path(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMORY_STORAGE_PATH", raising=False)
    prod = Path.home() / ".claude" / "memory" / "sub"
    with pytest.raises(RuntimeError, match="prod"):
        assert_not_prod("http://localhost:6334", prod)
    assert_not_prod("http://localhost:6334", tmp_path)  # non-prod passes


def test_backend_env_and_url(tmp_path):
    from benchmarks.eval.env import EphemeralBackend

    b = EphemeralBackend(storage_path=tmp_path / "store")
    assert b.base_url == "http://127.0.0.1:8010"
    env = b._child_env()
    assert env["QDRANT_URL"] == "http://localhost:6334"
    assert env["MEMORY_STORAGE_PATH"] == str(tmp_path / "store")
    assert env["MCP_TRANSPORT"] == "streamable-http"
    assert env["PORT"] == "8010"
    assert env["REKALL_AUTOSAVE"] == "0"


def test_child_env_strips_pytest_markers(tmp_path, monkeypatch):
    """_child_env() must strip PYTEST_VERSION and PYTEST_CURRENT_TEST.

    server.py: _is_testing = "PYTEST_VERSION" in os.environ
    If inherited, the server skips setup_tools() and only 2 of 28 rekall tools
    register — recall_memories never appears in the Claude Code init event.
    """
    from benchmarks.eval.env import EphemeralBackend

    monkeypatch.setenv("PYTEST_VERSION", "7.0.0")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_foo.py::test_bar")
    b = EphemeralBackend(storage_path=tmp_path / "store")
    env = b._child_env()
    assert "PYTEST_VERSION" not in env, "_child_env() must strip PYTEST_VERSION"
    assert "PYTEST_CURRENT_TEST" not in env, "_child_env() must strip PYTEST_CURRENT_TEST"


def test_make_workspace_creates_git_root(tmp_path):
    """make_workspace initializes .git so Claude Code picks up cwd/.claude/settings.json.

    Without a git root, Claude Code ignores project-level settings files entirely —
    project settings only apply when CWD is inside a git-rooted project tree.
    """
    from benchmarks.eval.env import make_workspace

    ws = make_workspace(tmp_path, "git01")
    assert (ws / ".git").is_dir(), (
        "make_workspace must init a git repo so project-level .claude/settings.json applies"
    )


@pytest.mark.integration
def test_seed_then_recall_with_project_filter(tmp_path):
    """Regression guard for the red-team seeding CRITICAL + cwd side door."""
    from benchmarks.eval.env import EphemeralBackend, make_workspace

    ws = make_workspace(tmp_path, "smoke01")
    with EphemeralBackend(storage_path=tmp_path / "store") as b:
        b.wipe()
        idmap = b.seed(
            [{"summary": "Metrics proxy listens on port 9741.", "type": "decision"}],
            cwd=str(ws),
        )
        assert len(idmap) == 1
        ids = b.recall_ids("metrics proxy port", project=ws.name)
        assert set(ids) & set(idmap)  # seeded memory surfaces WITH project filter active
