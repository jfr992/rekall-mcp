"""WikiStore: drafts, approve lifecycle, history, index, log (spec: Layers)."""

import threading
from datetime import date

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


def test_write_draft_takes_the_store_lock(store):
    from unittest.mock import MagicMock

    store._lock = MagicMock()
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    store._lock.__enter__.assert_called()


def test_concurrent_write_draft_is_not_lost_during_approve(store, monkeypatch):
    from memory.wiki.store import WikiStore

    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    real_read = WikiStore.read
    read_done, go, first = threading.Event(), threading.Event(), []

    def pausing_read(self, page_id, status="live"):
        result = real_read(self, page_id, status)
        if status == "draft" and not first:
            first.append(1)
            read_done.set()
            go.wait(timeout=5)
        return result

    monkeypatch.setattr(WikiStore, "read", pausing_read)
    approver = threading.Thread(target=store.approve, args=("demo/process/rotate-key",))
    approver.start()
    assert read_done.wait(timeout=5)
    writer = threading.Thread(
        target=store.write_draft,
        args=(Page(frontmatter=dict(FM), body=BODY.replace("x", "newer")),),
    )
    writer.start()
    writer.join(timeout=0.3)
    go.set()
    approver.join()
    writer.join()
    monkeypatch.setattr(WikiStore, "read", real_read)
    draft = store.read("demo/process/rotate-key", status="draft")
    assert draft is not None and "newer" in draft.body


def test_newlines_in_title_and_description_keep_index_entry(store):
    fm = dict(FM, title="T\nbad", description="a --> x\nb")
    store.write_draft(Page(frontmatter=fm, body=BODY))
    store.approve("demo/process/rotate-key")
    (entry,) = store.index_entries()
    assert entry["title"] == "T bad" and entry["summary"] == "a --> x b"
    assert len((store.root / "log.md").read_text().splitlines()) == 1


def test_reject_reason_newline_stays_one_log_line(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    store.reject("demo/process/rotate-key", reason="a\nb")
    assert (store.root / "log.md").read_text().splitlines() == [
        "## [" + date.today().isoformat() + "] reject | Rotate key — a b"
    ]


def test_approve_rejects_page_id_mismatch_and_draft_needs_page_id(store):
    store.write_draft(Page(frontmatter=dict(FM), body=BODY))
    other = store.path_for("demo/process/other", "draft")
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(store.path_for("demo/process/rotate-key", "draft").read_text())
    with pytest.raises(ValueError, match="mismatch"):
        store.approve("demo/process/other")
    with pytest.raises(ValueError, match="page_id"):
        store.write_draft(Page(frontmatter={"title": "x"}, body=""))


def test_cache_roundtrip_and_corrupt_file_reads_empty(tmp_path):
    from memory.wiki.store import WikiStore

    store = WikiStore(tmp_path / "wiki")
    assert store.read_cache("worthiness") == {}
    (store.root / "_cache" / "worthiness.json").write_text("{not json")
    assert store.read_cache("worthiness") == {}
    store.write_cache("worthiness", {"a": {"verdict": "skip"}})
    assert store.read_cache("worthiness") == {"a": {"verdict": "skip"}}
