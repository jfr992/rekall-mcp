"""Integration tests for the new memory OS REST endpoints.

Uses Starlette TestClient against the live FastMCP app. Each test is
independent; the production Qdrant at :6333 is used for read paths
(tests do not modify state).
"""

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client():
    from server import mcp
    app = mcp.streamable_http_app()
    return TestClient(app)


# ---------- Task 16: GET /api/memory/detail/{id} ----------


def test_detail_returns_not_found_for_missing_memory(client):
    response = client.get("/api/memory/detail/nonexistent_id_xxx")
    assert response.status_code == 200
    body = response.json()
    # Spec: memory=None, neighbors=[], scope=None when not found
    assert body.get("memory") is None
    assert body.get("neighbors") == []
