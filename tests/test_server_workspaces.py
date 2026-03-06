"""Tests for workspace API endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.mcp.streamable_http_app()) as test_client:
        yield test_client


def test_workspaces_endpoint_returns_list(tmp_path, client):
    """GET /api/workspaces returns discovered repos."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    with patch("server._get_workspace_roots", return_value=[str(tmp_path)]):
        response = client.get("/api/workspaces")

    assert response.status_code == 200
    payload = response.json()
    assert "workspaces" in payload
    assert len(payload["workspaces"]) == 1
    assert payload["workspaces"][0]["name"] == "test-repo"
    assert payload["workspaces"][0]["path"] == str(repo)
