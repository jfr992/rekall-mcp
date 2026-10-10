"""Wiki page model: frontmatter, sections, guards (spec: Page model)."""

import pytest

SAMPLE = """---
title: Rotate the gateway key
description: When and how to rotate the key
sidebar_position: 10
tags: [process, gateway]
page_id: demo-proj/process/rotate-gateway-key
type: process
project: demo-proj
scope: {env: all}
status: draft
revision: 1
updated: 2026-10-09
last_verified: null
confidence: medium
human_edited: false
sources: [2026-09-19_requirement_9b9a3e83, 2026-08-21_fact_c4b1d436]
---
## When {#when}
Key expired. [source: 2026-09-19_requirement_9b9a3e83]
## Preconditions {#preconditions}
- Admin access
## Steps {#steps}
1. Export the new key. [source: 2026-08-21_fact_c4b1d436]
2. Restart sessions.
## Expected output {#expected}
Sessions reconnect.
## Verify {#verify}
- `curl` returns 200
## Stop conditions {#stop}
- 401 persists
## Rollback {#rollback}
- Restore old key
## Known limitations {#limits}
- None
"""


def test_parse_and_emit_roundtrip():
    from memory.wiki.pages import emit_page, parse_page

    page = parse_page(SAMPLE)
    assert page.page_id == "demo-proj/process/rotate-gateway-key"
    assert page.type == "process"
    assert page.sources == ["2026-09-19_requirement_9b9a3e83", "2026-08-21_fact_c4b1d436"]
    again = parse_page(emit_page(page))
    assert again.frontmatter == page.frontmatter
    assert again.body.strip() == page.body.strip()


def test_split_sections_uses_explicit_ids_and_slugs():
    from memory.wiki.pages import parse_page, split_sections

    sections = split_sections(parse_page(SAMPLE).body)
    ids = [s[0] for s in sections]
    assert ids[:3] == ["when", "preconditions", "steps"]
    assert "2. Restart sessions." in {s[0]: s[2] for s in sections}["steps"]


def test_split_sections_slugifies_headings_without_ids():
    from memory.wiki.pages import split_sections

    out = split_sections("## Known Limitations\ntext\n## Other Thing!\nmore")
    assert [s[0] for s in out] == ["known-limitations", "other-thing"]


def test_missing_sections_for_each_type():
    from memory.wiki.pages import Page, missing_sections

    policy = Page(
        frontmatter={"page_id": "p/policy/x", "type": "policy", "title": "x"},
        body="## Rule {#rule}\nnever\n## Why {#why}\nbecause",
    )
    assert missing_sections(policy) == ["exceptions", "sources"]


def test_unsourced_steps_counts_steps_without_source_tag():
    from memory.wiki.pages import parse_page, unsourced_steps

    assert unsourced_steps(parse_page(SAMPLE)) == 1


def test_redaction_guard_and_token_estimate():
    from memory.wiki.pages import has_redaction, token_estimate

    assert has_redaction("pack [REDACTED] version")
    assert not has_redaction("clean")
    assert token_estimate("a" * 400) == 100


def test_parse_rejects_missing_frontmatter_and_bad_page_id():
    from memory.wiki.pages import parse_page

    with pytest.raises(ValueError):
        parse_page("no frontmatter here")
    with pytest.raises(ValueError):
        parse_page("---\ntitle: t\npage_id: ../escape\ntype: policy\n---\nbody")


def test_split_sections_ignores_headings_inside_code_fences():
    from memory.wiki.pages import split_sections

    out = split_sections("## Steps\n```sh\n## comment\n```\n- a")
    assert [s[0] for s in out] == ["steps"]
    assert "## comment" in out[0][2]
    assert out[0][2].endswith("- a")


def test_step_sources_top_level_items_and_multi_source_tags():
    from memory.wiki.pages import Page, step_sources, unsourced_steps

    text = (
        "Run in order:\n1. a\n   [source: 2026-01-01_fact_aaaa1111]\n"
        "2. b [source: 2026-01-01_fact_bbbb2222]\n   - nested\n"
        "3. c [source: 2026-01-01_fact_cccc3333, 2026-01-01_fact_dddd4444]"
    )
    assert step_sources(text) == [
        ["2026-01-01_fact_aaaa1111"],
        ["2026-01-01_fact_bbbb2222"],
        ["2026-01-01_fact_cccc3333", "2026-01-01_fact_dddd4444"],
    ]
    page = Page(
        frontmatter={"page_id": "p/process/x", "type": "process", "title": "x"},
        body="## Steps {#steps}\n" + text,
    )
    assert unsourced_steps(page) == 0


def test_parse_empty_frontmatter_reports_missing_page_id():
    from memory.wiki.pages import parse_page

    with pytest.raises(ValueError, match="missing page_id"):
        parse_page("---\n---\nbody")


def test_parse_keeps_horizontal_rule_in_body_and_handles_crlf():
    from memory.wiki.pages import parse_page

    text = "---\ntitle: t\npage_id: p/policy/x\ntype: policy\n---\nbefore\n\n---\n\nafter\n"
    assert "---" in parse_page(text).body
    crlf = parse_page(text.replace("\n", "\r\n"))
    assert crlf.page_id == "p/policy/x"
    assert "\r" not in crlf.body
