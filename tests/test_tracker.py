"""Tests for the pending items tracker."""

from __future__ import annotations

import asyncio

from pathlib import Path

import pytest


def test_tracker_provider_has_correct_name():
    from tools.builtin.tracker import TrackerTools

    provider = TrackerTools()
    assert provider.name == "tracker"


def test_tracker_provider_is_builtin():
    from tools.builtin.tracker import TrackerTools

    provider = TrackerTools()
    assert provider.builtin is True


def test_tracker_provider_registers_tools():
    from tools.builtin.tracker import TrackerTools

    provider = TrackerTools()
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "track_item" in tool_names
    assert "complete_item" in tool_names
    assert "get_pending" in tool_names
    assert "defer_item" in tool_names


@pytest.fixture
def tracker(tmp_path: Path):
    from tools.builtin.tracker import TrackerTools

    t = TrackerTools()
    t._storage_path = tmp_path / "pending.yaml"
    return t


def test_track_item(tracker):
    result = asyncio.run(tracker._track_item("Fix the auth bug", due_date="2026-03-10"))
    assert "TODO-001" in result
    assert "Fix the auth bug" in result
    assert "2026-03-10" in result


def test_track_multiple_items_increments_id(tracker):
    asyncio.run(tracker._track_item("First"))
    result = asyncio.run(tracker._track_item("Second"))
    assert "TODO-002" in result


def test_complete_item(tracker):
    asyncio.run(tracker._track_item("Task to complete"))
    result = asyncio.run(tracker._complete_item("TODO-001"))
    assert "Completed" in result

    pending = asyncio.run(tracker._get_pending())
    assert "TODO-001" not in pending


def test_complete_nonexistent_item(tracker):
    result = asyncio.run(tracker._complete_item("TODO-999"))
    assert "not found" in result


def test_get_pending_empty(tracker):
    result = asyncio.run(tracker._get_pending())
    assert "No pending items" in result


def test_get_pending_shows_overdue(tracker):
    asyncio.run(tracker._track_item("Overdue task", due_date="2025-01-01"))
    asyncio.run(tracker._track_item("Future task", due_date="2099-12-31"))
    result = asyncio.run(tracker._get_pending(overdue=True))
    assert "Overdue task" in result
    assert "Future task" not in result


def test_defer_item(tracker):
    asyncio.run(tracker._track_item("Deferred task", due_date="2026-03-05"))
    result = asyncio.run(tracker._defer_item("TODO-001", "2026-03-15"))
    assert "2026-03-15" in result

    items = tracker._load_items()
    assert items[0]["due_date"] == "2026-03-15"


def test_track_item_with_ticket(tracker):
    result = asyncio.run(
        tracker._track_item("Review MR", ticket_id="TOPE-456", context="BSO helm chart")
    )
    assert "TODO-001" in result
    items = tracker._load_items()
    assert items[0]["ticket_id"] == "TOPE-456"
    assert items[0]["context"] == "BSO helm chart"


def test_pending_yaml_format(tracker):
    """Verify the YAML file is human-readable."""
    asyncio.run(tracker._track_item("Readable task", due_date="2026-03-10"))
    content = tracker.storage_path.read_text()
    assert "title: Readable task" in content
    assert "status: open" in content
