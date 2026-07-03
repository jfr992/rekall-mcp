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
async def test_api_memory_doctor(monkeypatch):
    from server import api_memory_doctor

    manager = MagicMock()
    manager.doctor.return_value = {"status": "healthy", "project": "rekall-mcp"}
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_doctor(
        SimpleNamespace(query_params=QueryParams({"project": "rekall-mcp"}))
    )

    assert isinstance(response, JSONResponse)
    payload = json.loads(response.body)
    assert payload["status"] == "healthy"
    manager.doctor.assert_called_once_with(project="rekall-mcp")
