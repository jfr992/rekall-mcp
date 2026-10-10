"""BM25 over the wiki index with validity filtering and token budget (spec: Read path)."""

import pytest

from memory.wiki.pages import Page
from memory.wiki.store import WikiStore

POLICY = "## Rule {{#rule}}\n{rule}\n## Why {{#why}}\nw\n## Exceptions {{#exceptions}}\ne\n## Sources {{#sources}}\ns"


def _live(store, pid, title, rule, page_type="policy"):
    fm = {
        "title": title,
        "description": title,
        "page_id": pid,
        "type": page_type,
        "project": pid.split("/")[0],
        "sources": [],
    }
    body = (
        POLICY.format(rule=rule)
        if page_type == "policy"
        else (
            "## When {#when}\n"
            + rule
            + "\n## Preconditions {#preconditions}\np\n## Steps {#steps}\n1. s [source: 2026-01-01_fact_abcdef12]\n"
            "## Expected output {#expected}\ne\n## Verify {#verify}\nv\n## Stop conditions {#stop}\ns\n## Rollback {#rollback}\nr\n## Known limitations {#limits}\nl"
        )
    )
    store.write_draft(Page(frontmatter=fm, body=body))
    store.approve(pid)


@pytest.fixture
def store(tmp_path):
    s = WikiStore(tmp_path / "wiki")
    _live(
        s,
        "demo/policy/prod-go",
        "Prod go rule",
        "Never deploy to prod without an explicit go from the owner.",
    )
    _live(
        s, "demo/policy/commits", "Commit trailer", "Always add the co-author trailer to commits."
    )
    _live(
        s,
        "demo/process/rotate-key",
        "Rotate gateway key",
        "Rotate the gateway key when it expires.",
        page_type="process",
    )
    return s


def test_ranks_matching_page_first_with_section_and_excerpt(store):
    from memory.wiki.search import search_index

    hits = search_index(store, "deploy to prod go")
    assert hits[0]["page_id"] == "demo/policy/prod-go"
    assert hits[0]["section_id"] == "rule"
    assert "explicit go" in hits[0]["excerpt"]
    assert hits[0]["validity"] == "ok"


def test_limit_and_budget_are_enforced(store):
    from memory.wiki.search import search_index

    assert len(search_index(store, "rule", limit=1)) == 1
    assert len(search_index(store, "explicit expires co-author", budget_tokens=15)) == 1
    assert len(search_index(store, "explicit expires co-author", budget_tokens=10_000)) == 3


def test_withdrawn_pages_are_dropped(store):
    from memory.wiki.search import search_index

    def withdrawn(page):
        if page.type == "process":
            return {"validity": "withdrawn", "reasons": ["source disputed"]}
        return {"validity": "ok", "reasons": []}

    hits = search_index(store, "rotate gateway key", validity_fn=withdrawn)
    assert all(h["page_id"] != "demo/process/rotate-key" for h in hits)


def test_empty_or_stopword_query_returns_nothing(store):
    from memory.wiki.search import search_index

    assert search_index(store, "???") == []
    assert search_index(store, "the a of") == []


def test_project_filter(store):
    from memory.wiki.search import search_index

    assert search_index(store, "rule", project="other") == []


def test_sentence_final_words_match(store):
    from memory.wiki.search import search_index

    _live(store, "demo/policy/upgrade", "Upgrade note", "Plan to upgrade to v1.17.")
    assert search_index(store, "owner")[0]["page_id"] == "demo/policy/prod-go"
    assert search_index(store, "v1.17")[0]["page_id"] == "demo/policy/upgrade"
