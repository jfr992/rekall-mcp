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
