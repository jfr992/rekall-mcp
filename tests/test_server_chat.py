"""Tests for chat API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.mcp.streamable_http_app()) as test_client:
        yield test_client


def test_chat_endpoint_requires_message(client):
    """POST /api/orchestra/chat requires a message field."""
    response = client.post("/api/orchestra/chat", json={})
    assert response.status_code == 400
    assert response.json()["error"] == "message is required"


def test_chat_endpoint_and_history(client):
    """POST /api/orchestra/chat returns assistant response and updates history."""
    with patch(
        "tools.builtin.chat_orchestrator.ChatOrchestrator.handle_chat",
        new=AsyncMock(return_value={"message": "Acknowledged", "dispatches": []}),
    ):
        response = client.post(
            "/api/orchestra/chat",
            json={"message": "hello", "workspace": "/tmp"},
        )

    assert response.status_code == 200
    assert response.json() == {"message": "Acknowledged", "dispatches": []}

    history = client.get("/api/orchestra/chat/history").json()["messages"]
    assert {"role": "user", "content": "hello"} in history
    assert {"role": "assistant", "content": "Acknowledged"} in history


def test_chat_history_endpoint_returns_list(client):
    """GET /api/orchestra/chat/history returns message list."""
    response = client.get("/api/orchestra/chat/history")
    assert response.status_code == 200
    assert isinstance(response.json()["messages"], list)
