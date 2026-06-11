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
async def test_api_resume_packet(monkeypatch):
    # /api/memory/context/resume was removed as a duplicate; /api/memory/resume
    # (api_memory_resume) is the single resume route.
    from server import api_memory_resume

    manager = MagicMock()
    manager.get_resume_packet.return_value = {
        "scope": {"project": "brain"},
        "recent": [],
        "important": [],
        "unresolved": [],
        "summary": "# Resume Packet: brain\n",
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(query_params=QueryParams({"project": "brain", "limit": "9"}))
    response = await api_memory_resume(request)

    assert isinstance(response, JSONResponse)
    payload = json.loads(response.body)
    assert payload["scope"]["project"] == "brain"
    manager.get_resume_packet.assert_called_once_with(project="brain", limit=9)
