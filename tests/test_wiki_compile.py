"""Worthiness classification and page drafting with a fake LLM (spec: Worthiness, Pipeline)."""

import hashlib
import json


def _sha(content):
    return hashlib.sha1(content[:4000].encode()).hexdigest()


def _mem(mid, content, **extra):
    return {"memory_id": mid, "content": content, "project": "demo", **extra}


def test_classify_skips_disputed_and_redacted_without_calling_llm():
    from memory.wiki.compile import classify_candidates

    calls = []
    verdict = json.dumps(
        {"verdict": "worthy", "question": "q", "page_type": "policy", "scope": {}, "reasons": ["r"]}
    )

    def llm(prompt):
        calls.append(prompt)
        return verdict

    cache = {}
    out = classify_candidates(
        [
            _mem("2026-01-01_fact_a1", "never deploy without go"),
            _mem("2026-01-02_fact_b2", "pack [REDACTED] rotate"),
            _mem("2026-01-03_fact_c3", "x", disputed=True),
        ],
        llm=llm,
        cache=cache,
    )
    assert [o["memory_id"] for o in out] == ["2026-01-01_fact_a1"]
    assert len(calls) == 1
    assert (
        cache["2026-01-02_fact_b2"]["verdict"] == "skip"
        and cache["2026-01-03_fact_c3"]["verdict"] == "skip"
    )


def test_classify_uses_cache_and_tolerates_bad_json():
    from memory.wiki.compile import classify_candidates

    cache = {
        "2026-01-01_fact_a1": {
            "verdict": "worthy",
            "question": "q",
            "page_type": "reference",
            "scope": {},
            "reasons": [],
            "content_sha": _sha("x"),
        }
    }
    out = classify_candidates(
        [_mem("2026-01-01_fact_a1", "x"), _mem("2026-01-04_fact_d4", "y")],
        llm=lambda prompt: "not json",
        cache=cache,
    )
    assert [o["memory_id"] for o in out] == ["2026-01-01_fact_a1"]
    assert (
        cache["2026-01-04_fact_d4"]["verdict"] == "skip"
        and "unparseable" in cache["2026-01-04_fact_d4"]["reasons"][0]
    )


def test_draft_process_page_has_sections_sources_and_page_id():
    from memory.wiki.compile import draft_page

    body = (
        "## When {#when}\nkey expired [source: 2026-01-01_fact_a1]\n## Preconditions {#preconditions}\nadmin\n"
        "## Steps {#steps}\n1. export key [source: 2026-01-01_fact_a1]\n## Expected output {#expected}\nok\n"
        "## Verify {#verify}\ncurl 200\n## Stop conditions {#stop}\n401\n## Rollback {#rollback}\nrestore\n"
        "## Known limitations {#limits}\nnone\n"
    )
    llm = lambda prompt: "TITLE: Rotate the gateway key\n" + body  # noqa: E731
    page = draft_page(
        [_mem("2026-01-01_fact_a1", "rotate key when expired")],
        page_type="process",
        project="demo",
        title=None,
        llm=llm,
    )
    assert page.page_id == "demo/process/rotate-the-gateway-key"
    assert page.status == "draft" and page.sources == ["2026-01-01_fact_a1"]
    assert "needs" not in page.frontmatter
    assert page.frontmatter["sidebar_position"] == 10 and page.frontmatter["tags"] == ["process"]


def test_draft_prompt_survives_braces_in_templates_and_memories():
    from memory.wiki.compile import draft_page

    seen = []

    def llm(prompt):
        seen.append(prompt)
        return "TITLE: T\n"

    draft_page(
        [_mem("2026-01-01_fact_a1", "use {curly} {page_type}")],
        page_type="policy",
        project="demo",
        title=None,
        llm=llm,
    )
    assert "{#rule}" in seen[0] and "use {curly} {page_type}" in seen[0]


def test_draft_with_missing_sections_marks_needs():
    from memory.wiki.compile import draft_page

    llm = lambda prompt: "TITLE: Half\n## Rule {#rule}\nr\n### extra\nignored\n## Why {#why}\nw\n"  # noqa: E731
    page = draft_page(
        [_mem("2026-01-01_fact_a1", "x")], page_type="policy", project="demo", title=None, llm=llm
    )
    assert page.frontmatter["needs"] == ["exceptions", "sources"]


def test_make_llm_is_none_when_unconfigured(monkeypatch):
    from memory.wiki.compile import make_llm

    for k in (
        "REKALL_PUBLISH_MODEL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    assert make_llm() is None


def test_classify_gates_override_a_cached_worthy_verdict():
    from memory.wiki.compile import classify_candidates

    worthy = {
        "verdict": "worthy",
        "question": "q",
        "page_type": "policy",
        "scope": {},
        "reasons": [],
    }
    cache = {
        "2026-01-01_fact_a1": {**worthy, "content_sha": _sha("x")},
        "2026-01-02_fact_b2": {**worthy, "content_sha": _sha("[REDACTED]")},
    }
    calls = []
    out = classify_candidates(
        [_mem("2026-01-01_fact_a1", "x", disputed=True), _mem("2026-01-02_fact_b2", "[REDACTED]")],
        llm=lambda p: calls.append(p) or "",
        cache=cache,
    )
    assert out == [] and calls == []
    assert cache["2026-01-01_fact_a1"]["verdict"] == "skip" and cache["2026-01-01_fact_a1"][
        "reasons"
    ] == ["disputed"]
    assert cache["2026-01-02_fact_b2"]["verdict"] == "skip"


def test_classify_reclassifies_on_stale_sha_only():
    from memory.wiki.compile import classify_candidates

    fresh = json.dumps(
        {"verdict": "worthy", "question": "q", "page_type": "policy", "scope": {}, "reasons": []}
    )
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return fresh

    stale = {"verdict": "skip", "reasons": ["old"], "content_sha": "deadbeef"}
    cache = {"2026-01-01_fact_a1": stale}
    out = classify_candidates([_mem("2026-01-01_fact_a1", "edited")], llm=llm, cache=cache)
    assert len(out) == 1 and len(calls) == 1
    assert cache["2026-01-01_fact_a1"]["content_sha"] == _sha("edited")
    classify_candidates([_mem("2026-01-01_fact_a1", "edited")], llm=llm, cache=cache)
    assert len(calls) == 1


def test_classify_sanitizes_model_fields():
    from memory.wiki.compile import classify_candidates

    raw = json.dumps(
        {
            "verdict": "worthy",
            "question": 5,
            "page_type": "policy",
            "scope": "prod",
            "reasons": "because",
        }
    )
    cache = {}
    out = classify_candidates([_mem("2026-01-01_fact_a1", "x")], llm=lambda p: raw, cache=cache)
    assert out[0]["scope"] == {} and out[0]["reasons"] == [] and out[0]["question"] is None
