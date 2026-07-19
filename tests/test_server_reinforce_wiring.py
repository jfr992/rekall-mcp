"""Live wiring: POST /api/memory/events (session_summary) invokes the T2
reinforce processor server-side, behind REKALL_REINFORCE (default on).

PLAN.md Mechanism: "Consume the posted session_summary server-side (no
second Stop-hook pass, no new transcript scan)". Non-blocking: a processor
failure must never fail the ingestion response.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    from starlette.testclient import TestClient

    manager = MagicMock()
    manager.record_event.return_value = None
    manager.memory_dir = Path(tmp_path)
    import server

    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def _post_summary(tc):
    return tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "sess-abc",
            "project": "my-proj",
            "recalled_ids": ["id-1"],
            "edits_after_recall": 3,
            "test_passes_after_recall": 5,
        },
    )


def test_session_summary_post_triggers_reinforce_processor(client, monkeypatch):
    tc, manager = client
    monkeypatch.delenv("REKALL_REINFORCE", raising=False)

    with patch("memory.reinforce.process_events") as mock_process:
        r = _post_summary(tc)

    assert r.status_code == 200
    mock_process.assert_called_once()


def test_rekall_reinforce_zero_disables_processor(client, monkeypatch):
    tc, manager = client
    monkeypatch.setenv("REKALL_REINFORCE", "0")

    with patch("memory.reinforce.process_events") as mock_process:
        r = _post_summary(tc)

    assert r.status_code == 200
    mock_process.assert_not_called()


def test_reinforce_processor_failure_does_not_fail_ingestion(client, monkeypatch):
    tc, manager = client
    monkeypatch.delenv("REKALL_REINFORCE", raising=False)

    with patch("memory.reinforce.process_events", side_effect=RuntimeError("boom")):
        r = _post_summary(tc)

    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
