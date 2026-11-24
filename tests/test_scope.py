import subprocess
from pathlib import Path

from memory.scope import ScopeDetector


def test_scope_detector_defaults_to_general(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scope = ScopeDetector.detect(cwd=tmp_path)

    assert scope.project == tmp_path.name
    assert scope.workspace_root == str(Path(tmp_path).resolve())


def test_scope_detector_respects_explicit_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scope = ScopeDetector.detect(project="brain-os", cwd=tmp_path, agent="codex")

    assert scope.project == "brain-os"
    assert scope.agent == "codex"


def test_scope_detector_personal_boundary_without_remote(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scope = ScopeDetector.detect(cwd=tmp_path)

    assert scope.trust_boundary == "personal"


def test_junk_directory_names_fall_back_to_general(tmp_path):
    """Timestamp-shaped or tmp-style dir names are session artifacts, not
    projects — two prod memories landed under '20260708-091227' (real incident)."""
    junk = tmp_path / "20260708-091227"
    junk.mkdir()
    scope = ScopeDetector.detect(cwd=junk)
    assert scope.project == "general"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path, *, remote: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "dev@example.com")
    _git(path, "config", "user.name", "Dev")
    (path / "README").write_text("init\n")
    _git(path, "add", "README")
    _git(path, "commit", "-m", "init")
    if remote:
        _git(path, "remote", "add", "origin", remote)
    return path


def test_worktree_project_uses_main_repo_name(tmp_path):
    """A linked worktree must store the main repo name, not the worktree folder."""
    main = _init_repo(
        tmp_path / "demo-repo",
        remote="https://user:ghp_secret@github.com/acme/demo-repo.git",
    )
    worktree = tmp_path / "demo-repo-feature"
    _git(main, "worktree", "add", "-b", "feature", str(worktree))
    ScopeDetector.reset_trust_cache()

    scope = ScopeDetector.detect(cwd=worktree)

    assert scope.project == "demo-repo"
    assert scope.repo_name == "demo-repo"
    assert scope.branch == "feature"
    assert Path(scope.workspace_root) == worktree.resolve()
    assert Path(scope.repo_root) == worktree.resolve()
    assert scope.repo_remote == "https://github.com/acme/demo-repo.git"
    assert "ghp_secret" not in scope.repo_remote
    assert "user:" not in scope.repo_remote


def test_clone_folder_alias_uses_origin_repo_name(tmp_path):
    """A second clone of the same origin (e.g. *-clawd) shares the origin repo name."""
    checkout = _init_repo(
        tmp_path / "demo-repo-clawd",
        remote="https://github.com/acme/demo-repo.git",
    )
    ScopeDetector.reset_trust_cache()

    scope = ScopeDetector.detect(cwd=checkout)

    assert scope.project == "demo-repo"
    assert scope.repo_name == "demo-repo"
    assert Path(scope.workspace_root) == checkout.resolve()


def test_unrelated_origin_keeps_main_checkout_name(tmp_path):
    """Do not retitle a checkout just because origin points at a differently named repo."""
    checkout = _init_repo(
        tmp_path / "rekall-mcp",
        remote="https://github.com/acme/memento-mcp.git",
    )
    ScopeDetector.reset_trust_cache()

    scope = ScopeDetector.detect(cwd=checkout)

    assert scope.project == "rekall-mcp"
    assert scope.repo_name == "rekall-mcp"


def test_subdirectory_cwd_uses_main_repo_name(tmp_path):
    main = _init_repo(tmp_path / "demo-repo")
    sub = main / "apps" / "api"
    sub.mkdir(parents=True)
    ScopeDetector.reset_trust_cache()

    scope = ScopeDetector.detect(cwd=sub)

    assert scope.project == "demo-repo"
    assert Path(scope.workspace_root) == sub.resolve()


def test_explicit_project_matching_cwd_basename_resolves_to_main_repo(tmp_path):
    main = _init_repo(tmp_path / "demo-repo")
    worktree = tmp_path / "demo-repo-feature"
    _git(main, "worktree", "add", "-b", "feature", str(worktree))
    ScopeDetector.reset_trust_cache()

    hardened = ScopeDetector.detect(project="demo-repo-feature", cwd=worktree)
    override = ScopeDetector.detect(project="other-app", cwd=worktree)

    assert hardened.project == "demo-repo"
    assert override.project == "other-app"
