"""Import-only provider preflight (#57): fail the container at start, not at first encode."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO / "scripts" / "entrypoint.sh"


def _run_entrypoint(tmp_path, provider):
    """Run entrypoint.sh outside Docker: fake `python` on PATH -> this interpreter."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    # Wrapper (not a symlink): a symlinked venv python loses its site-packages.
    python = fakebin / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "PYTHONPATH": str(REPO / "src"),
        "EMBEDDING_PROVIDER": provider,
        "QDRANT_URL": "http://localhost:9",
    }
    return subprocess.run(
        ["sh", str(ENTRYPOINT), "true"], env=env, capture_output=True, text=True, timeout=30
    )


def test_preflight_rejects_unknown_provider(monkeypatch):
    from core.embeddings import validate_provider_importable

    monkeypatch.setenv("EMBEDDING_PROVIDER", "no-such-provider")

    error = validate_provider_importable()

    assert error is not None
    assert "EMBEDDING_PROVIDER" in error
    assert "no-such-provider" in error
    assert "fastembed" in error  # names the available providers


def test_preflight_rejects_uninstalled_provider(monkeypatch):
    """The #57 incident: EMBEDDING_PROVIDER=sentence-transformers on a slim image."""
    import importlib.util

    from core.embeddings import validate_provider_importable

    monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence-transformers")
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "sentence_transformers" else real_find_spec(name, *a),
    )

    error = validate_provider_importable()

    assert error is not None
    assert "EMBEDDING_PROVIDER" in error
    assert "sentence_transformers" in error
    assert "not installed" in error


def test_entrypoint_fails_fast_on_bad_provider(tmp_path):
    result = _run_entrypoint(tmp_path, "no-such-provider")

    assert result.returncode == 1
    assert "FATAL" in result.stderr
    assert "EMBEDDING_PROVIDER" in result.stderr


def test_entrypoint_boots_with_importable_provider(tmp_path):
    result = _run_entrypoint(tmp_path, "fastembed")

    assert result.returncode == 0, result.stderr
