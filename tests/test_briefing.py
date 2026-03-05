"""Tests for the briefing engine."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


def test_briefing_provider_has_correct_name():
    from tools.builtin.briefing import BriefingTools

    provider = BriefingTools()
    assert provider.name == "briefing"


def test_briefing_provider_registers_tools():
    from tools.builtin.briefing import BriefingTools

    provider = BriefingTools()
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "session_briefing" in tool_names
    assert "daily_briefing" in tool_names


@pytest.fixture
def briefing(tmp_path: Path):
    from tools.builtin.briefing import BriefingTools

    b = BriefingTools()
    b._storage_path = tmp_path
    return b


def test_session_briefing_empty(briefing):
    result = asyncio.run(briefing._session_briefing())
    assert "All clear" in result


def test_session_briefing_with_overdue(briefing):
    pending_file = briefing.storage_path / "pending.yaml"
    pending_file.write_text(
        yaml.dump(
            {
                "items": [
                    {
                        "id": "TODO-001",
                        "title": "Review BSO helm chart",
                        "status": "open",
                        "due_date": "2025-01-01",
                        "ticket_id": "TOPE-100",
                    }
                ]
            }
        )
    )
    result = asyncio.run(briefing._session_briefing())
    assert "OVERDUE" in result
    assert "TODO-001" in result
    assert "TOPE-100" in result


def test_session_briefing_with_recent_memories(briefing):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mem_file = briefing.storage_path / f"{today}.yaml"
    mem_file.write_text(
        yaml.dump(
            {
                "date": today,
                "learnings": [
                    {
                        "id": f"{today}_learning_abc",
                        "content": "NATS rotation requires reloader annotation",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        )
    )
    result = asyncio.run(briefing._session_briefing())
    assert "NATS rotation" in result
    assert "Recent Findings" in result


def test_daily_briefing_includes_session(briefing):
    """Daily briefing should include session briefing content."""
    result = asyncio.run(briefing._daily_briefing())
    assert "All clear" in result


def test_format_jira_handles_none(briefing):
    assert briefing._format_jira(None) == []


def test_format_jira_parses_tickets(briefing):
    raw = json.dumps(
        [
            {
                "key": "TOPE-123",
                "fields": {
                    "summary": "Fix auth flow",
                    "status": {"name": "In Progress"},
                },
            }
        ]
    )
    lines = briefing._format_jira(raw)
    assert len(lines) == 1
    assert "TOPE-123" in lines[0]
    assert "Fix auth flow" in lines[0]


def test_format_mrs_handles_none(briefing):
    assert briefing._format_mrs(None) == []


def test_format_mrs_parses_data(briefing):
    raw = json.dumps(
        [
            {
                "title": "feat: add tracker tools",
                "web_url": "https://gitlab.com/mr/1",
                "detailed_merge_status": "mergeable",
            }
        ]
    )
    lines = briefing._format_mrs(raw)
    assert len(lines) == 1
    assert "tracker tools" in lines[0]
