"""WikiStore: drafts, approve lifecycle, history, index, log (spec: Layers)."""

import threading

import pytest

from memory.wiki.pages import Page

FM = {
    "title": "Rotate key",
    "description": "How to rotate",
    "page_id": "demo/process/rotate-key",
    "type": "process",
    "project": "demo",
    "scope": {"env": "all"},
    "status": "draft",
    "revision": 0,
    "sources": ["2026-09-19_requirement_9b9a3e83"],
}
BODY = """## When {#when}
x
## Preconditions {#preconditions}
y
## Steps {#steps}
1. Do it. [source: 2026-09-19_requirement_9b9a3e83]
## Expected output {#expected}
z
## Verify {#verify}
v
## Stop conditions {#stop}
s
## Rollback {#rollback}
r
## Known limitations {#limits}
l
"""


@pytest.fixture
def store(tmp_path):
    from memory.wiki.store import WikiStore

    return WikiStore(tmp_path / "wiki")


def test_write_draft_and_read(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    page = store.read("demo/process/rotate-key", status="draft")
    assert page is not None and page.status == "draft"
    assert store.read("demo/process/rotate-key", status="live") is None
    assert (store.root / "SCHEMA.md").exists()


def test_approve_moves_to_live_bumps_revision_and_indexes(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    live = store.approve("demo/process/rotate-key")
    assert live.status == "live" and live.frontmatter["revision"] == 1
    assert live.frontmatter["last_verified"]
    assert store.read("demo/process/rotate-key", status="draft") is None
    entries = store.index_entries()
    assert [e["page_id"] for e in entries] == ["demo/process/rotate-key"]
    assert entries[0]["type"] == "process" and entries[0]["status"] == "live"
    assert "approve | Rotate key" in (store.root / "log.md").read_text()


def test_second_approve_snapshots_history(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    store.approve("demo/process/rotate-key")
    store.write_draft(Page(frontmatter=dict(FM), body=BODY.replace("x", "x2")))
    live = store.approve("demo/process/rotate-key")
    assert live.frontmatter["revision"] == 2
    history = list((store.root / "_history" / "demo" / "process" / "rotate-key").glob("*.md"))
    assert len(history) == 1 and "revision: 1" in history[0].read_text()


def test_approve_refuses_redaction_and_unsourced_process_steps(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY.replace("x", "[REDACTED]")))
    with pytest.raises(ValueError, match="redact"):
        store.approve("demo/process/rotate-key")
    store.write_draft(
        Page(
            frontmatter=dict(FM),
            body=BODY.replace(" [source: 2026-09-19_requirement_9b9a3e83]", ""),
        )
    )
    with pytest.raises(ValueError, match="source"):
        store.approve("demo/process/rotate-key")


def test_reject_removes_draft_and_logs_reason(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    store.reject("demo/process/rotate-key", reason="duplicate of runbook")
    assert store.read("demo/process/rotate-key", status="draft") is None
    assert "reject | Rotate key — duplicate of runbook" in (store.root / "log.md").read_text()


def test_path_for_rejects_traversal(store):
    with pytest.raises(ValueError):
        store.path_for("../../etc/passwd")
    with pytest.raises(ValueError):
        store.path_for("demo/process/../x")


def test_concurrent_approves_keep_index_consistent(store):
    ids = []
    for i in range(6):
        fm = dict(FM, page_id=f"demo/policy/rule-{i}", type="policy", title=f"Rule {i}")
        body = "## Rule {#rule}\nr\n## Why {#why}\nw\n## Exceptions {#exceptions}\ne\n## Sources {#sources}\ns"
        store.write_draft(Page(frontmatter=fm, body=body))
        ids.append(fm["page_id"])
    threads = [threading.Thread(target=store.approve, args=(pid,)) for pid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(e["page_id"] for e in store.index_entries()) == sorted(ids)
