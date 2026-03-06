"""Tests for Orchestra REST API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.mcp.streamable_http_app()) as test_client:
        yield test_client


def test_dispatch_task_route(client):
    with patch(
        "tools.builtin.orchestra.AgentOrchestraTools._dispatch_task",
        new=AsyncMock(return_value="Dispatched RUN-001 to claude"),
    ) as mock_dispatch:
        response = client.post(
            "/api/orchestra/dispatch",
            json={"task": "Fix auth bug", "agent": "claude"},
        )

    assert response.status_code == 200
    assert "RUN-001" in response.json()["result"]
    args, kwargs = mock_dispatch.await_args
    assert kwargs["task"] == "Fix auth bug"
    assert kwargs["agent"] == "claude"


def test_agent_status_route(client):
    with patch(
        "tools.builtin.orchestra.AgentOrchestraTools._agent_status",
        new=AsyncMock(return_value="No agent runs found."),
    ) as mock_status:
        response = client.get("/api/orchestra/status")

    assert response.status_code == 200
    assert response.json() == {"result": "No agent runs found."}
    args, kwargs = mock_status.await_args
    assert args == ()
    assert kwargs["status"] is None


def test_review_result_route_with_action(client):
    with patch(
        "tools.builtin.orchestra.AgentOrchestraTools._review_result",
        new=AsyncMock(return_value="**RUN-001** approved and marked completed."),
    ) as mock_review:
        response = client.post(
            "/api/orchestra/runs/RUN-001/review",
            json={"action": "approve"},
        )

    assert response.status_code == 200
    assert "approved" in response.json()["result"]
    args, kwargs = mock_review.await_args
    assert kwargs["run_id"] == "RUN-001"
    assert kwargs["action"] == "approve"
    assert kwargs["feedback"] == ""
