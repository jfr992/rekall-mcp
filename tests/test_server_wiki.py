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
    assert (
        tc.post("/api/wiki/candidates", json={"project": "demo"}).json()["status"] == "unconfigured"
    )
    assert (
        tc.post(
            "/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"}
        ).json()["status"]
        == "unconfigured"
    )


def test_lifecycle_candidates_draft_approve_search_read_and_stale(client, monkeypatch):
    tc, manager = client
    _fake_llm(monkeypatch)
    cands = tc.post("/api/wiki/candidates", json={"project": "demo"}).json()["candidates"]
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


def test_model_calls_run_off_the_event_loop_thread(client, monkeypatch):
    import threading

    tc, _ = client
    seen = []

    def llm(prompt):
        seen.append(threading.current_thread().name)
        if "Answer with JSON" in prompt:
            return json.dumps({"verdict": "worthy", "page_type": "process", "reasons": []})
        return f"TITLE: Rotate the gateway key\n{PROCESS_BODY}"

    def factory():
        loop_thread.append(threading.current_thread().name)
        return llm

    loop_thread = []
    monkeypatch.setattr("server.make_wiki_llm", factory)
    tc.post("/api/wiki/candidates", json={"project": "demo"})
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    assert len(seen) == 2 and loop_thread[0] not in seen


def test_edit_draft_ignores_protected_frontmatter(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch)
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    url = "/api/wiki/drafts/demo/process/rotate-the-gateway-key"
    fm = {"page_id": "demo/policy/other", "status": "live", "type": "policy", "title": "New title"}
    page = tc.put(url, json={"body": PROCESS_BODY, "frontmatter": fm}).json()["page"]
    assert page["page_id"] == "demo/process/rotate-the-gateway-key"
    assert page["status"] == "draft" and page["type"] == "process" and page["title"] == "New title"
    assert [d["page_id"] for d in tc.get("/api/wiki/drafts").json()["drafts"]] == [
        "demo/process/rotate-the-gateway-key"
    ]


def test_unknown_draft_is_404_on_approve_reject_put(client):
    tc, _ = client
    url = "/api/wiki/drafts/demo/process/nope"
    assert tc.post(f"{url}/approve").status_code == 404
    assert tc.post(f"{url}/reject", json={"reason": "x"}).status_code == 404
    assert tc.put(url, json={"body": "x"}).status_code == 404


def test_get_draft_returns_full_body_with_flags_and_404(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch)
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    pid = "demo/process/rotate-the-gateway-key"
    r = tc.get(f"/api/wiki/drafts/{pid}")
    d = r.json()
    assert r.status_code == 200 and d["status"] == "draft" and d["page_id"] == pid
    assert d["body"] == PROCESS_BODY and d["section_id"] is None and d["over_budget"] is False
    assert d["needs"] == [] and d["unsourced_steps"] == 0 and d["has_redaction"] is False
    assert "validity" in d and d["sections"][0] == "when"
    assert tc.get("/api/wiki/drafts/demo/process/nope").status_code == 404
    assert tc.get("/api/wiki/drafts/bad id").status_code == 400
    # POST routes sharing the prefix still resolve to approve/reject, not the GET route
    assert tc.post(f"/api/wiki/drafts/{pid}/approve").status_code == 200
    assert tc.get(f"/api/wiki/drafts/{pid}").status_code == 404


def test_candidates_get_is_405_post_only(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch)
    assert tc.get("/api/wiki/candidates?project=demo").status_code == 405


def test_candidates_partial_failure_keeps_and_caches_earlier_verdicts(client, monkeypatch):
    tc, manager = client
    manager.store.scroll.return_value = [
        {"memory_id": f"2026-01-01_fact_a{i}", "content": f"rule {i}", "project": "demo"}
        for i in (1, 2, 3)
    ]
    calls = []

    def llm(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("model down")
        return json.dumps({"verdict": "worthy", "page_type": "policy", "reasons": []})

    monkeypatch.setattr("server.make_wiki_llm", lambda: llm)
    r = tc.post("/api/wiki/candidates", json={"project": "demo"})
    assert r.status_code == 200
    assert [c["memory_id"] for c in r.json()["candidates"]] == [
        "2026-01-01_fact_a1",
        "2026-01-01_fact_a3",
    ]
    assert set(manager.wiki.read_cache("worthiness")) == {
        "2026-01-01_fact_a1",
        "2026-01-01_fact_a3",
    }


def test_approve_refuses_sources_missing_from_memory_store(client, monkeypatch):
    tc, manager = client
    _fake_llm(monkeypatch)
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    manager.store.get_many.side_effect = lambda ids, **kw: []
    r = tc.post("/api/wiki/drafts/demo/process/rotate-the-gateway-key/approve")
    assert r.status_code == 400 and "2026-01-01_fact_a1" in r.json()["error"]


def test_draft_page_id_uses_project_slug_and_invalid_id_is_400_before_model(client, monkeypatch):
    tc, manager = client
    _fake_llm(monkeypatch)
    r = tc.post(
        "/api/wiki/draft",
        json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process", "project": "MyRepo"},
    )
    page = r.json()["page"]
    assert r.status_code == 200 and page["page_id"] == "myrepo/process/rotate-the-gateway-key"
    assert page["project"] == "MyRepo"

    calls = []
    monkeypatch.setattr("server.make_wiki_llm", lambda: lambda p: calls.append(p) or "")
    bad = tc.post(
        "/api/wiki/draft",
        json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "bogus", "project": "MyRepo"},
    )
    assert bad.status_code == 400 and calls == []


def test_put_after_approve_is_404_not_a_resurrected_draft(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch)
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    url = "/api/wiki/drafts/demo/process/rotate-the-gateway-key"
    assert tc.post(f"{url}/approve").status_code == 200
    assert tc.put(url, json={"body": PROCESS_BODY}).status_code == 404
    assert tc.get("/api/wiki/drafts").json()["drafts"] == []


def test_put_redacts_secret_and_approve_then_refuses(client, monkeypatch):
    tc, _ = client
    _fake_llm(monkeypatch)
    tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    url = "/api/wiki/drafts/demo/process/rotate-the-gateway-key"
    tc.put(url, json={"body": PROCESS_BODY.replace("admin", "api_key=sk-abc123def456")})
    body = tc.get(url).json()["body"]
    assert "sk-abc123" not in body and "[REDACTED]" in body
    r = tc.post(f"{url}/approve")
    assert r.status_code == 400 and "redact" in r.json()["error"].lower()


def test_search_limit_is_clamped_to_three(client, monkeypatch):
    tc, _ = client
    seen = []
    monkeypatch.setattr("server.search_index", lambda *a, **kw: seen.append(kw["limit"]) or [])
    tc.get("/api/wiki/search?q=x&limit=50")
    tc.get("/api/wiki/search?q=x&limit=0")
    assert seen == [3, 1]
