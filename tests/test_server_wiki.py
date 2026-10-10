"""REST contract for the wiki routes plus the phase-1 lifecycle (spec: Read path, Pipeline)."""

import json
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

PROCESS_BODY = (
    "## When {#when}\nkey expired [source: 2026-01-01_fact_a1]\n## Preconditions {#preconditions}\nadmin\n"
    "## Steps {#steps}\n1. export key [source: 2026-01-01_fact_a1]\n## Expected output {#expected}\nok\n"
    "## Verify {#verify}\ncurl 200\n## Stop conditions {#stop}\n401\n## Rollback {#rollback}\nrestore\n## Known limitations {#limits}\nnone\n"
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    import server
    from memory.wiki.store import WikiStore

    manager = MagicMock()
    manager.memory_dir = tmp_path
    manager.wiki = WikiStore(tmp_path / "wiki")
    manager.store.get_many.side_effect = lambda ids, **kw: [
        {"memory_id": i, "content": f"content {i}", "project": "demo"} for i in ids
    ]
    manager.store.scroll.return_value = [
        {"memory_id": "2026-01-01_fact_a1", "content": "never deploy without go", "project": "demo"}
    ]
    manager.knowledge_graph.get_edges.return_value = []
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def _fake_llm(monkeypatch, body=PROCESS_BODY, title="Rotate the gateway key"):
    monkeypatch.setattr(
        "server.make_wiki_llm",
        lambda: (
            lambda prompt: (
                json.dumps(
                    {
                        "verdict": "worthy",
                        "question": "how to rotate",
                        "page_type": "process",
                        "scope": {"env": "all"},
                        "reasons": ["r"],
                    }
                )
                if "Answer with JSON" in prompt
                else f"TITLE: {title}\n{body}"
            )
        ),
    )


def test_candidates_and_draft_are_unconfigured_without_llm(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr("server.make_wiki_llm", lambda: None)
    assert tc.get("/api/wiki/candidates?project=demo").json()["status"] == "unconfigured"
    assert (
        tc.post(
            "/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"}
        ).json()["status"]
        == "unconfigured"
    )


def test_lifecycle_candidates_draft_approve_search_read_and_stale(client, monkeypatch):
    tc, manager = client
    _fake_llm(monkeypatch)
    cands = tc.get("/api/wiki/candidates?project=demo").json()["candidates"]
    assert cands[0]["memory_id"] == "2026-01-01_fact_a1" and cands[0]["page_type"] == "process"
    r = tc.post(
        "/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"}
    )
    assert (
        r.status_code == 200
        and r.json()["page"]["page_id"] == "demo/process/rotate-the-gateway-key"
    )
    drafts = tc.get("/api/wiki/drafts").json()["drafts"]
    assert drafts[0]["unsourced_steps"] == 0 and drafts[0]["needs"] == []
    assert (
        tc.post("/api/wiki/drafts/demo/process/rotate-the-gateway-key/approve").status_code == 200
    )
    hits = tc.get("/api/wiki/search?q=rotate gateway key").json()["hits"]
    assert (
        hits[0]["page_id"] == "demo/process/rotate-the-gateway-key" and hits[0]["validity"] == "ok"
    )
    page = tc.get("/api/wiki/page/demo/process/rotate-the-gateway-key").json()
    assert (
        page["section_id"] == "steps"
        and "export key" in page["body"]
        and page["over_budget"] is False
    )
    manager.store.get_many.side_effect = lambda ids, **kw: [
        {"memory_id": i, "content": "c", "project": "demo", "disputed": True} for i in ids
    ]
    assert tc.get("/api/wiki/search?q=rotate gateway key").json()["hits"] == []
    page = tc.get("/api/wiki/page/demo/process/rotate-the-gateway-key").json()
    assert page["validity"] == "withdrawn" and page["body"]


def test_approve_refuses_redaction_with_400(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch, body=PROCESS_BODY.replace("admin", "[REDACTED]"))
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    r = tc.post("/api/wiki/drafts/demo/process/rotate-the-gateway-key/approve")
    assert r.status_code == 400 and "redact" in r.json()["error"].lower()


def test_edit_draft_sets_human_edited_then_reject_removes(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch)
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    r = tc.put(
        "/api/wiki/drafts/demo/process/rotate-the-gateway-key",
        json={"body": PROCESS_BODY.replace("admin", "root")},
    )
    assert r.json()["page"]["human_edited"] is True
    assert (
        tc.post(
            "/api/wiki/drafts/demo/process/rotate-the-gateway-key/reject", json={"reason": "dup"}
        ).json()["status"]
        == "rejected"
    )
    assert tc.get("/api/wiki/drafts").json()["drafts"] == []


def test_page_404_and_bad_id(client):
    tc, _ = client
    assert tc.get("/api/wiki/page/demo/process/nope").status_code == 404
    assert tc.get("/api/wiki/page/../x").status_code in (400, 404)
