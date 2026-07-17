"""Entity backlinks: GET /api/memory/by-entity + manager.find_by_entity (U2.5 T2)."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def fake_manager(monkeypatch):
    fake = MagicMock()
    fake.find_by_entity.return_value = [
        {"memory_id": "m1", "content": "x", "entities": ["MetalLB"]}
    ]
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.fixture
def client():
    from server import mcp

    return TestClient(mcp.streamable_http_app())


def test_by_entity_plumbs_params_and_returns_shape(client, fake_manager):
    r = client.get("/api/memory/by-entity?entity=MetalLB&project=byte-edge&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["entity"] == "MetalLB"
    assert body["count"] == 1
    assert body["memories"][0]["memory_id"] == "m1"
    assert fake_manager.find_by_entity.call_args.kwargs == {
        "project": "byte-edge",
        "limit": 5,
    }
    assert fake_manager.find_by_entity.call_args.args == ("MetalLB",)


def test_by_entity_rejects_missing_or_blank_entity(client, fake_manager):
    assert client.get("/api/memory/by-entity").status_code == 400
    assert client.get("/api/memory/by-entity?entity=%20%20").status_code == 400
    fake_manager.find_by_entity.assert_not_called()


@pytest.mark.integration
def test_find_by_entity_is_case_insensitive(memory_manager):
    """Stored entity casing is first-occurrence ("MetalLB"), not lowercase —
    a lowercased query must still find it (MatchValue alone is exact-case)."""
    memory_manager.save(
        "Chose MetalLB for bare-metal load balancing",
        type="decision",
        project="net-lab",
    )

    hits = memory_manager.find_by_entity("metallb", project="net-lab", limit=10)

    assert len(hits) == 1
    assert "MetalLB" in hits[0]["entities"]


@pytest.mark.integration
def test_find_by_entity_scopes_to_project_and_caps_at_limit(memory_manager):
    memory_manager.save(
        "MetalLB speaker pods need the memberlist secret", type="learning", project="net-lab"
    )
    memory_manager.save("MetalLB IP pools defined per rack", type="fact", project="net-lab")
    memory_manager.save("MetalLB is not used in cloud-lab", type="note", project="cloud-lab")

    scoped = memory_manager.find_by_entity("MetalLB", project="net-lab", limit=10)
    assert len(scoped) == 2
    assert {m["project"] for m in scoped} == {"net-lab"}

    capped = memory_manager.find_by_entity("MetalLB", project="net-lab", limit=1)
    assert len(capped) == 1

    everywhere = memory_manager.find_by_entity("MetalLB", limit=10)
    assert len(everywhere) == 3
