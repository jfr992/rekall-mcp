"""End-to-end test for Jarvis mode flow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def jarvis_env(tmp_path: Path):
    """Set up a complete Jarvis environment."""
    from tools.builtin.briefing import BriefingTools
    from tools.builtin.tracker import TrackerTools

    tracker = TrackerTools()
    tracker._storage_path = tmp_path / "pending.yaml"

    briefing = BriefingTools()
    briefing._storage_path = tmp_path

    return tracker, briefing, tmp_path


def test_full_jarvis_flow(jarvis_env):
    """Simulate: track items -> briefing shows them -> complete -> briefing updates."""
    tracker, briefing, tmp_path = jarvis_env

    asyncio.run(
        tracker._track_item(
            "Review BSO v0.3.1 MR",
            due_date="2025-01-01",  # Already overdue
            ticket_id="TOPE-789",
        )
    )
    asyncio.run(
        tracker._track_item(
            "Verify SRR creates edge-secrets",
            due_date="2026-03-10",
            context="After z531003 deployment",
        )
    )
    asyncio.run(tracker._track_item("Check helm values sync"))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mem_file = tmp_path / f"{today}.yaml"
    mem_file.write_text(
        yaml.dump(
            {
                "date": today,
                "decisions": [
                    {
                        "id": f"{today}_decision_test",
                        "content": "Switched from mongodb to PostgreSQL for BSO state store",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        )
    )

    result = asyncio.run(briefing._session_briefing())
    assert "OVERDUE" in result
    assert "TOPE-789" in result
    assert "Verify SRR" in result
    assert "PostgreSQL" in result or "Recent Findings" in result

    asyncio.run(tracker._complete_item("TODO-001"))

    result = asyncio.run(briefing._session_briefing())
    assert ("TOPE-789" not in result) or ("OVERDUE" not in result.split("TOPE-789")[0])

    asyncio.run(tracker._defer_item("TODO-002", "2026-04-01"))
    items = tracker._load_items()
    deferred = [i for i in items if i["id"] == "TODO-002"]
    assert deferred[0]["due_date"] == "2026-04-01"
