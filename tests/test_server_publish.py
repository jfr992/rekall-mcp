"""REST contract tests for /api/memory/publish. Integration — needs Qdrant."""

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client():
    from server import mcp

    app = mcp.streamable_http_app()
    return TestClient(app)


@pytest.mark.integration
def test_preview_returns_tree_files_stats(client):
    r = client.get("/api/memory/publish?project=nonexistent-xyz&mode=preview")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"tree", "files", "stats"}


@pytest.mark.integration
def test_unknown_project_is_empty_not_error(client):
    r = client.get("/api/memory/publish?project=nonexistent-xyz")
    assert r.status_code == 200
    assert r.json()["stats"]["concepts"] == 0


@pytest.mark.integration
def test_dir_mode_rejects_traversal(client):
    r = client.get("/api/memory/publish?mode=dir&dest=/etc/passwd")
    assert r.status_code == 400


@pytest.mark.integration
def test_tar_mode_returns_gzip(client):
    r = client.get("/api/memory/publish?project=nonexistent-xyz&mode=tar")
    assert r.status_code == 200
    assert r.content[:2] == b"\x1f\x8b"


@pytest.mark.integration
def test_synthesize_starts_job_and_status_polls(client):
    r = client.post("/api/memory/publish/synthesize?project=nonexistent-xyz")
    assert r.status_code == 200
    assert r.json()["status"] in {"started", "running"}
    s = client.get("/api/memory/publish/status?project=nonexistent-xyz")
    assert s.status_code == 200
    assert s.json()["status"] in {"running", "done", "idle", "error"}
