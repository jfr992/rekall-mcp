"""Tests for Jarvis REST API endpoints."""

import importlib


def test_tracker_endpoints_exist():
    """Verify tracker routes are registered in server."""
    server = importlib.import_module("server")
    assert hasattr(server, "_handle_track_item") and callable(server._handle_track_item)


def test_briefing_endpoints_exist():
    """Verify briefing routes are registered in server."""
    server = importlib.import_module("server")
    assert (
        hasattr(server, "_handle_session_briefing")
        and callable(server._handle_session_briefing)
    )
