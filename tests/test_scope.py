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
