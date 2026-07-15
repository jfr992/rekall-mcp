import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.responses import JSONResponse


class QueryParams:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.mark.asyncio
async def test_api_agent_startup(monkeypatch):
    from server import api_agent_startup

    manager = MagicMock()
    manager.get_agent_startup.return_value = {
        "scope": {"project": "brain", "agent": "claude-code"},
        "startup_summary": "# Agent Startup: brain\n",
        "resume_packet": {},
        "project_capsule": {"project": "brain", "entities": []},
        "system_hints": [],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(
        query_params=QueryParams({"project": "brain", "agent": "claude-code", "limit": "7"})
    )
    response = await api_agent_startup(request)

    assert isinstance(response, JSONResponse)
    payload = json.loads(response.body)
    assert payload["scope"]["project"] == "brain"
    manager.get_agent_startup.assert_called_once_with(
        project="brain", agent="claude-code", limit=7, session_id=None
    )


@pytest.mark.asyncio
async def test_health_carries_rekall_signature(monkeypatch):
    import server

    monkeypatch.setattr("server._vector_health", lambda: {"sampled": 0, "zero_vectors": 0})
    response = await server.health_check(SimpleNamespace())
    body = json.loads(response.body)
    assert body["server"] == "rekall"
    assert isinstance(body["version"], str) and body["version"]


@pytest.mark.asyncio
async def test_api_project_capsule(monkeypatch):
    from server import api_project_capsule

    manager = MagicMock()
    manager.get_project_capsule.return_value = {
        "project": "brain",
        "entities": ["Codex"],
        "standing_context": [],
        "danger_zones": [],
        "open_loops": [],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(query_params=QueryParams({"project": "brain", "limit": "9"}))
    response = await api_project_capsule(request)

    assert isinstance(response, JSONResponse)
    payload = json.loads(response.body)
    assert payload["project"] == "brain"
    manager.get_project_capsule.assert_called_once_with(project="brain", limit=9, session_id=None)
