"""Tests for Jarvis REST API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.mcp.streamable_http_app()) as test_client:
        yield test_client


def test_get_pending_route_returns_http_ok(client):
    with patch(
        "tools.builtin.tracker.TrackerTools._get_pending",
        new=AsyncMock(return_value="No pending items."),
    ) as mock_get_pending:
        response = client.get("/api/tracker/items")

    assert response.status_code == 200
    assert response.json() == {"result": "No pending items."}
    assert mock_get_pending.await_args.kwargs["overdue"] is False


def test_get_pending_route_overdue_query(client):
    with patch(
        "tools.builtin.tracker.TrackerTools._get_pending",
        new=AsyncMock(return_value="No overdue items."),
    ) as mock_get_pending:
        response = client.get("/api/tracker/items?overdue=true")

    assert response.status_code == 200
    assert response.json() == {"result": "No overdue items."}
    assert mock_get_pending.await_args.kwargs["overdue"] is True


def test_post_track_item_route_calls_tracker(client):
    expected_result = "Tracked: TODO-001 - Review BSO helm chart"
    with patch(
        "tools.builtin.tracker.TrackerTools._track_item",
        new=AsyncMock(return_value=expected_result),
    ) as mock_track:
        response = client.post(
            "/api/tracker/items",
            json={
                "title": "Review BSO helm chart",
                "due_date": "2026-03-10",
                "context": "BSO release prep",
                "ticket_id": "TOPE-123",
                "priority": "high",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"result": expected_result}
    _, kwargs = mock_track.await_args
    assert kwargs["title"] == "Review BSO helm chart"
    assert kwargs["due_date"] == "2026-03-10"
    assert kwargs["context"] == "BSO release prep"
    assert kwargs["ticket_id"] == "TOPE-123"
    assert kwargs["priority"] == "high"


def test_post_complete_item_route_calls_tracker(client):
    expected_result = "Completed: TODO-001"
    with patch(
        "tools.builtin.tracker.TrackerTools._complete_item",
        new=AsyncMock(return_value=expected_result),
    ) as mock_complete:
        response = client.post("/api/tracker/items/TODO-001/complete")

    assert response.status_code == 200
    assert response.json() == {"result": expected_result}
    args, kwargs = mock_complete.await_args
    assert len(args) == 1
    assert args[0] == "TODO-001"
    assert kwargs == {}


def test_post_defer_item_route_calls_tracker(client):
    expected_result = "Deferred: TODO-001 from 2026-03-10 to 2026-04-01"
    with patch(
        "tools.builtin.tracker.TrackerTools._defer_item",
        new=AsyncMock(return_value=expected_result),
    ) as mock_defer:
        response = client.post(
            "/api/tracker/items/TODO-001/defer",
            json={"new_date": "2026-04-01"},
        )

    assert response.status_code == 200
    assert response.json() == {"result": expected_result}
    args, kwargs = mock_defer.await_args
    assert len(args) == 2
    assert args[0] == "TODO-001"
    assert args[1] == "2026-04-01"
    assert kwargs == {}


def test_session_briefing_route_returns_session_summary(client):
    expected_result = "# Session Briefing\n- TODO-001"
    with patch(
        "tools.builtin.briefing.BriefingTools._session_briefing",
        new=AsyncMock(return_value=expected_result),
    ) as mock_briefing:
        response = client.get("/api/briefing/session?project=platform")

    assert response.status_code == 200
    assert response.json() == {"result": expected_result}
    args, kwargs = mock_briefing.await_args
    assert args == ()
    assert kwargs == {"project": "platform"}


def test_daily_briefing_route_returns_daily_summary(client):
    expected_result = "# Daily Briefing\n- TODO-001"
    with patch(
        "tools.builtin.briefing.BriefingTools._daily_briefing",
        new=AsyncMock(return_value=expected_result),
    ) as mock_daily:
        response = client.get("/api/briefing/daily?project=platform")

    assert response.status_code == 200
    assert response.json() == {"result": expected_result}
    args, kwargs = mock_daily.await_args
    assert args == ()
    assert kwargs == {"project": "platform"}
