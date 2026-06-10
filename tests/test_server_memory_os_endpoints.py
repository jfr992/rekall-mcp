"""Integration tests for the new memory OS REST endpoints.

Uses Starlette TestClient against the live FastMCP app. Each test is
independent. Requires a real Qdrant on :6334 (integration marker).
"""

import pytest
from starlette.testclient import TestClient


pytestmark = pytest.mark.integration  # exercises live endpoints against a real Qdrant (:6334)


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


# ---------- Task 17: GET /api/memory/kb ----------


def test_kb_returns_four_slices(client):
    response = client.get("/api/memory/kb?project=general")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"decisions", "requirements", "preferences", "learnings"}
    for slice_name in ("decisions", "requirements", "preferences", "learnings"):
        assert isinstance(body[slice_name], list)


# ---------- Task 18: GET /api/memory/pressure ----------


def test_pressure_returns_structured_json(client):
    response = client.get("/api/memory/pressure?project=general")
    assert response.status_code == 200
    body = response.json()
    assert "flagged" in body
    assert "candidates" in body
    assert isinstance(body["flagged"], dict)
    assert "stale_working_count" in body["flagged"]
    assert "low_value_count" in body["flagged"]
    assert "load_score" in body
    assert "capacity" in body


# ---------- Task 19: POST /api/memory/prune/plan ----------


def test_prune_plan_returns_plan_id(client):
    response = client.post("/api/memory/prune/plan", json={"project": "general"})
    assert response.status_code == 200
    body = response.json()
    assert "plan_id" in body
    assert "candidates" in body
    assert "expires_at" in body
    assert isinstance(body["candidates"], list)


def test_prune_plan_requires_project(client):
    response = client.post("/api/memory/prune/plan", json={})
    assert response.status_code == 400


# ---------- Task 20: POST /api/memory/prune/apply ----------


def test_prune_apply_requires_plan_id_confirmation(client):
    plan_resp = client.post("/api/memory/prune/plan", json={"project": "general"})
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["plan_id"]

    bad = client.post("/api/memory/prune/apply", json={"plan_id": plan_id, "confirm": "wrong"})
    assert bad.status_code == 400


def test_prune_apply_rejects_unknown_plan(client):
    response = client.post("/api/memory/prune/apply", json={"plan_id": "nope", "confirm": "nope"})
    assert response.status_code == 400


# ---------- Task 21: POST /api/memory/lifecycle/backfill ----------


def test_lifecycle_backfill_dry_run(client):
    response = client.post("/api/memory/lifecycle/backfill", json={"dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert "updated_by_tier" in body
    assert "total" in body
    assert body["dry_run"] is True


# ---------- Task 22: GET /api/memory/resume ----------


def test_resume_endpoint_returns_truncated_field(client):
    response = client.get("/api/memory/resume?project=general")
    assert response.status_code == 200
    body = response.json()
    assert "recent" in body
    assert "important" in body
    assert "truncated" in body
