# Rekall Wiki Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Rekall-served, human-approved wiki of compiled markdown pages (process, policy, reference, entity) with a bounded, validity-checked read path for agents, a Docusaurus-like docs surface in the cockpit, assisted authoring of the first pages, and measurement wired into the existing session-summary loop.

**Architecture:** A new `src/memory/wiki/` package owns the page model, file store, validity, search and compile steps as pure, file-backed units under `<MEMORY_STORAGE_PATH>/wiki/`. `src/server.py` exposes them as REST routes; `src/tools/builtin/memory.py` exposes `wiki_lookup`/`wiki_read` as MCP tools that emit `wiki_delivered` events; both session-end hooks count wiki deliveries and page-id references; the cockpit gets a `/wiki` surface following the `kb` pattern.

**Tech Stack:** Python 3.11, FastMCP/Starlette, PyYAML, httpx (existing Anthropic-compatible client in `publish.py`), pytest; Next.js cockpit with TanStack Query, Zod, vitest, `react-markdown` + `remark-gfm` (new deps); bash hooks.

**Spec:** `docs/superpowers/specs/2026-10-09-rekall-wiki-design.md`

## Global Constraints

- Branch `feat/wiki-phase1` (already created from `main`, spec committed). Never push to main. Conventional commits ending with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Tests: `uv run --extra dev pytest <paths> -v`; before the final commit the CI commands exactly: `uv run ruff check src tests`, `uv run ruff format --check src tests`, full pytest (expect only pre-existing skips), `cd ui && npm test`. If uv's cache is sandbox-blocked, prefix `UV_CACHE_DIR=$TMPDIR/uv-cache`; run outside the sandbox when `/tmp` writes are denied.
- Do not edit `tests/test_software_evals.py`. No schema bump on memory records. Nothing machine- or company-specific in code, tests, or docs (no `/Users/...`, no project names from the maintainer's machine).
- Wiki root is `manager.memory_dir / "wiki"`; the test-isolation guard applies (tests use `tmp_path`).
- Page id format: `<project>/<type>/<slug>` matching `^[a-z0-9][a-z0-9._-]*/(process|policy|reference|entity)/[a-z0-9][a-z0-9-]*$`. Memory id regex stays `\d{4}-\d{2}-\d{2}_[a-z]+_[0-9a-f]+`.
- Token estimate everywhere = `len(text) // 4`. Lookup: ≤3 hits and ≤600 tokens total. Read: section ≤1,500 tokens; full page ≤3,000; a `process` page is never truncated (return it whole with `over_budget: true` instead).
- No model call on any read path. Model calls only in `compile.py`, through the same configuration the publish job uses (`REKALL_PUBLISH_MODEL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY`); when unconfigured, candidate/draft endpoints return `{"status": "unconfigured"}` and write nothing.
- Live pages change only through approve. A page containing the string `[REDACTED]` can never be approved. A `process` page with a step lacking `[source: <memory_id>]` can never be approved.
- Hooks stay bash 3.2 compatible; every failure path exits 0.
- Comments: one line, why not what.

## Review Focus

1. `page_id` from a URL with `..` or an absolute path must never escape the wiki root (`store.py` resolves and rejects). Test in Task 2.
2. A memory id listed in `sources` that no longer exists in the store must count as `stale`, not crash validity. Test in Task 3.
3. A query with no tokens after normalization (`"???"`) returns an empty hit list, not an exception. Test in Task 4.
4. Synthesis output that includes extra sections or wrong heading levels is still parsed; missing required sections leave the page a draft with `needs`. Test in Task 5.
5. Two concurrent approves of the same page id must not corrupt `index.md` (approve rebuilds the index under a lock). Test in Task 2.
6. A `wiki_read` on a withdrawn `process` page returns the warning first and the body after, never an empty body. Test in Task 7.

---

### Task 1: Page model (`pages.py`)

**Files:**
- Create: `src/memory/wiki/__init__.py` (empty), `src/memory/wiki/pages.py`
- Test: `tests/test_wiki_pages.py`

**Interfaces:**
- Produces:
  - `PAGE_ID_RE: re.Pattern`
  - `@dataclass(frozen=True) class Page: frontmatter: dict, body: str` with `page_id`, `type`, `project`, `sources: list[str]`, `status` properties reading frontmatter.
  - `parse_page(text: str) -> Page` (raises `ValueError` on missing frontmatter or missing `page_id`/`type`/`title`)
  - `emit_page(page: Page) -> str`
  - `split_sections(body: str) -> list[tuple[str, str, str]]` → `(section_id, heading, markdown)` where `section_id` comes from `{#id}` on the H2, else slugified heading.
  - `required_sections(page_type: str) -> list[str]`: process → `["when","preconditions","steps","expected","verify","stop","rollback","limits"]`; policy → `["rule","why","exceptions","sources"]`; reference → `["facts","sources"]`; entity → `["what","related","sources"]`.
  - `missing_sections(page: Page) -> list[str]`
  - `has_redaction(text: str) -> bool` (`"[REDACTED]" in text`)
  - `step_sources(section_markdown: str) -> list[list[str]]` → per bullet/numbered step, the memory ids in `[source: ...]`
  - `unsourced_steps(page: Page) -> int` for process pages
  - `token_estimate(text: str) -> int`

- [ ] **Step 1: Write the failing tests**

```python
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
    assert "2. Restart sessions." in dict((s[0], s[2]) for s in sections)["steps"]


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_wiki_pages.py -v`
Expected: FAIL with `ModuleNotFoundError: memory.wiki`.

- [ ] **Step 3: Implement `pages.py`**

```python
"""Wiki page model: Docusaurus-compatible markdown with Rekall frontmatter."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

PAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*/(process|policy|reference|entity)/[a-z0-9][a-z0-9-]*$")
MEMORY_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z]+_[0-9a-f]+")
_H2_RE = re.compile(r"^## (.+?)(?:\s*\{#([a-z0-9-]+)\})?\s*$", re.M)
_SOURCE_RE = re.compile(r"\[source:\s*([^\]]+)\]")
_STEP_RE = re.compile(r"^\s*(?:\d+\.|[-*])\s+", re.M)
_REQUIRED = {
    "process": ["when", "preconditions", "steps", "expected", "verify", "stop", "rollback", "limits"],
    "policy": ["rule", "why", "exceptions", "sources"],
    "reference": ["facts", "sources"],
    "entity": ["what", "related", "sources"],
}


@dataclass(frozen=True)
class Page:
    frontmatter: dict
    body: str

    @property
    def page_id(self) -> str:
        return str(self.frontmatter["page_id"])

    @property
    def type(self) -> str:
        return str(self.frontmatter["type"])

    @property
    def project(self) -> str:
        return str(self.frontmatter.get("project") or self.page_id.split("/")[0])

    @property
    def sources(self) -> list[str]:
        return [str(s) for s in (self.frontmatter.get("sources") or [])]

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status") or "draft")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def parse_page(text: str) -> Page:
    if not text.startswith("---\n"):
        raise ValueError("page has no frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    fm = yaml.safe_load(text[4:end]) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter must be a mapping")
    for key in ("page_id", "type", "title"):
        if not fm.get(key):
            raise ValueError(f"frontmatter missing {key}")
    if not PAGE_ID_RE.match(str(fm["page_id"])):
        raise ValueError("invalid page_id")
    if fm["type"] not in _REQUIRED:
        raise ValueError("invalid type")
    body = text[end + 4 :].lstrip("\n")
    return Page(frontmatter=fm, body=body)


def emit_page(page: Page) -> str:
    fm = yaml.safe_dump(page.frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=None).strip()
    return f"---\n{fm}\n---\n{page.body.rstrip()}\n"


def split_sections(body: str) -> list[tuple[str, str, str]]:
    matches = list(_H2_RE.finditer(body))
    out = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group(1).strip()
        section_id = m.group(2) or slugify(heading)
        out.append((section_id, heading, body[start:end].strip()))
    return out


def required_sections(page_type: str) -> list[str]:
    return list(_REQUIRED.get(page_type, []))


def missing_sections(page: Page) -> list[str]:
    present = {s[0] for s in split_sections(page.body)}
    return [s for s in required_sections(page.type) if s not in present]


def has_redaction(text: str) -> bool:
    return "[REDACTED]" in text


def step_sources(section_markdown: str) -> list[list[str]]:
    steps = [s for s in _STEP_RE.split(section_markdown) if s.strip()]
    return [[sid.strip() for sid in _SOURCE_RE.findall(step)] for step in steps]


def unsourced_steps(page: Page) -> int:
    if page.type != "process":
        return 0
    sections = dict((s[0], s[2]) for s in split_sections(page.body))
    return sum(1 for sources in step_sources(sections.get("steps", "")) if not sources)


def token_estimate(text: str) -> int:
    return len(text) // 4
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_wiki_pages.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memory/wiki/__init__.py src/memory/wiki/pages.py tests/test_wiki_pages.py
git commit -m "feat(wiki): page model with frontmatter, sections, and guards"
```

---

### Task 2: File store (`store.py`)

**Files:**
- Create: `src/memory/wiki/store.py`
- Test: `tests/test_wiki_store.py`

**Interfaces:**
- Consumes: Task 1 (`Page`, `parse_page`, `emit_page`, `PAGE_ID_RE`, `has_redaction`, `unsourced_steps`).
- Produces: `class WikiStore(root: Path)` with
  - `path_for(page_id, status="live"|"draft") -> Path` (rejects ids failing `PAGE_ID_RE`)
  - `read(page_id, status="live") -> Page | None`
  - `write_draft(page: Page) -> Path` (sets `status: draft`)
  - `list_pages(status) -> list[Page]`
  - `approve(page_id, *, verified_by="human") -> Page` (raises `ValueError` on redaction or unsourced process steps; snapshots existing live to `_history/<page_id>/<revision>.md`; bumps `revision`; sets `status: live`, `last_verified` = today, `updated` = today; removes the draft; rebuilds `index.md`; appends `log.md`)
  - `reject(page_id, reason) -> None` (removes draft, appends log)
  - `index_entries() -> list[dict]` parsed from `index.md` (`page_id, title, type, project, scope, status, last_verified, summary`)
  - `rebuild_index() -> None` (from live pages, grouped `project → type`, one line per page: `- [title](live/<path>.md) — <description> <!-- {json meta} -->`)
  - `append_log(kind, title) -> None` (`## [YYYY-MM-DD] <kind> | <title>`)
  - `SCHEMA_TEXT: str` written to `SCHEMA.md` on first use if absent.
  - Index rebuild and approve take a `threading.Lock` held on the store instance.

- [ ] **Step 1: Write the failing tests**

```python
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
    store.write_draft(Page(frontmatter=dict(FM), body=BODY.replace(" [source: 2026-09-19_requirement_9b9a3e83]", "")))
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_wiki_store.py -v`
Expected: FAIL with `ModuleNotFoundError: memory.wiki.store`.

- [ ] **Step 3: Implement `store.py`**

```python
"""File-backed wiki store: drafts, live pages, history, index, log."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

from memory.wiki.pages import PAGE_ID_RE, Page, emit_page, has_redaction, parse_page, unsourced_steps

SCHEMA_TEXT = """# Rekall wiki schema

Pages are Docusaurus-compatible markdown with Rekall frontmatter.
Types: process, policy, reference, entity. Every H2 carries a stable `{#id}`.
Live pages change only through approve. `[REDACTED]` never ships. Process
steps end with `[source: <memory_id>]`.
"""


class WikiStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        for sub in ("live", "drafts", "_history", "_cache"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        schema = self.root / "SCHEMA.md"
        if not schema.exists():
            schema.write_text(SCHEMA_TEXT, encoding="utf-8")
        for name in ("index.md", "log.md"):
            path = self.root / name
            if not path.exists():
                path.write_text("", encoding="utf-8")

    def path_for(self, page_id: str, status: str = "live") -> Path:
        if not PAGE_ID_RE.match(page_id):
            raise ValueError("invalid page_id")
        base = self.root / ("live" if status == "live" else "drafts")
        path = (base / f"{page_id}.md").resolve()
        if base.resolve() not in path.parents:
            raise ValueError("page_id escapes wiki root")
        return path

    def read(self, page_id: str, status: str = "live") -> Page | None:
        path = self.path_for(page_id, status)
        if not path.exists():
            return None
        return parse_page(path.read_text(encoding="utf-8"))

    def write_draft(self, page: Page) -> Path:
        fm = dict(page.frontmatter, status="draft")
        path = self.path_for(fm["page_id"], "draft")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(emit_page(Page(frontmatter=fm, body=page.body)), encoding="utf-8")
        return path

    def list_pages(self, status: str = "live") -> list[Page]:
        base = self.root / ("live" if status == "live" else "drafts")
        pages = []
        for path in sorted(base.rglob("*.md")):
            try:
                pages.append(parse_page(path.read_text(encoding="utf-8")))
            except ValueError:
                continue  # a broken file never hides the rest of the wiki
        return pages

    def approve(self, page_id: str, *, verified_by: str = "human") -> Page:
        draft = self.read(page_id, "draft")
        if draft is None:
            raise ValueError("no draft for page_id")
        if has_redaction(draft.body) or has_redaction(json.dumps(draft.frontmatter)):
            raise ValueError("page contains redacted text")
        if unsourced_steps(draft):
            raise ValueError("process page has steps without a source")
        with self._lock:
            live_path = self.path_for(page_id, "live")
            existing = self.read(page_id, "live")
            revision = 1
            if existing is not None:
                revision = int(existing.frontmatter.get("revision") or 0) + 1
                hist = self.root / "_history" / page_id
                hist.mkdir(parents=True, exist_ok=True)
                (hist / f"{existing.frontmatter.get('revision', 0)}.md").write_text(emit_page(existing), encoding="utf-8")
            today = date.today().isoformat()
            fm = dict(draft.frontmatter, status="live", revision=revision, updated=today, last_verified=today)
            fm.setdefault("human_edited", False)
            live = Page(frontmatter=fm, body=draft.body)
            live_path.parent.mkdir(parents=True, exist_ok=True)
            live_path.write_text(emit_page(live), encoding="utf-8")
            self.path_for(page_id, "draft").unlink(missing_ok=True)
            self._rebuild_index_locked()
            self._append_log_locked("approve", str(fm.get("title") or page_id))
        return live

    def reject(self, page_id: str, reason: str) -> None:
        draft = self.read(page_id, "draft")
        if draft is None:
            raise ValueError("no draft for page_id")
        with self._lock:
            self.path_for(page_id, "draft").unlink(missing_ok=True)
            self._append_log_locked("reject", f"{draft.frontmatter.get('title') or page_id} — {reason}")

    def rebuild_index(self) -> None:
        with self._lock:
            self._rebuild_index_locked()

    def _rebuild_index_locked(self) -> None:
        lines = ["# Wiki index", ""]
        current = None
        for page in sorted(self.list_pages("live"), key=lambda p: (p.project, p.type, p.page_id)):
            group = f"## {page.project} / {page.type}"
            if group != current:
                lines += [group, ""]
                current = group
            meta = {
                "page_id": page.page_id,
                "title": page.frontmatter.get("title"),
                "type": page.type,
                "project": page.project,
                "scope": page.frontmatter.get("scope"),
                "status": page.status,
                "last_verified": page.frontmatter.get("last_verified"),
                "summary": page.frontmatter.get("description") or "",
            }
            lines.append(f"- [{meta['title']}](live/{page.page_id}.md) — {meta['summary']} <!-- {json.dumps(meta)} -->")
        (self.root / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def index_entries(self) -> list[dict]:
        out = []
        for line in (self.root / "index.md").read_text(encoding="utf-8").splitlines():
            if "<!-- " in line and line.startswith("- "):
                try:
                    out.append(json.loads(line.split("<!-- ", 1)[1].rsplit(" -->", 1)[0]))
                except ValueError:
                    continue
        return out

    def append_log(self, kind: str, title: str) -> None:
        with self._lock:
            self._append_log_locked(kind, title)

    def _append_log_locked(self, kind: str, title: str) -> None:
        with (self.root / "log.md").open("a", encoding="utf-8") as fh:
            fh.write(f"## [{date.today().isoformat()}] {kind} | {title}\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_wiki_store.py tests/test_wiki_pages.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memory/wiki/store.py tests/test_wiki_store.py
git commit -m "feat(wiki): file store with draft/approve lifecycle, history, index, log"
```

---

### Task 3: Validity at read time (`validity.py`)

**Files:**
- Create: `src/memory/wiki/validity.py`
- Test: `tests/test_wiki_validity.py`

**Interfaces:**
- Consumes: `Page` (Task 1); `manager.store.get_many(ids) -> list[dict]` (payload has `memory_id`, optional `disputed: bool`); `manager.knowledge_graph.get_edges(memory_id, direction="in") -> list[Edge]` with `.relation`, `.source`, `.target`.
- Produces: `compute_validity(page: Page, *, store, graph) -> dict` → `{"validity": "ok"|"stale"|"withdrawn", "reasons": [str]}`. Rules: any source missing from the store → stale (`source X not found`); any source payload `disputed` truthy → stale; any incoming `supersedes` edge whose `.source` memory id is not in `page.sources` → stale; a `process` page that is stale → `withdrawn`.

- [ ] **Step 1: Write the failing tests**

```python
"""Validity computed from the graph at read time (spec: Read path)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from memory.wiki.pages import Page

SRC = "2026-09-19_requirement_9b9a3e83"


def _page(page_type="policy", sources=(SRC,)):
    return Page(frontmatter={"page_id": f"p/{page_type}/x", "type": page_type, "title": "x", "sources": list(sources)}, body="")


def _env(points, edges):
    store = MagicMock()
    store.get_many.return_value = points
    graph = MagicMock()
    graph.get_edges.side_effect = lambda mid, direction="both": edges.get(mid, [])
    return store, graph


def test_clean_sources_are_ok():
    from memory.wiki.validity import compute_validity

    store, graph = _env([{"memory_id": SRC}], {})
    assert compute_validity(_page(), store=store, graph=graph) == {"validity": "ok", "reasons": []}


def test_disputed_source_is_stale():
    from memory.wiki.validity import compute_validity

    store, graph = _env([{"memory_id": SRC, "disputed": True}], {})
    out = compute_validity(_page(), store=store, graph=graph)
    assert out["validity"] == "stale" and "disputed" in out["reasons"][0]


def test_superseded_source_is_stale_unless_successor_is_a_source():
    from memory.wiki.validity import compute_validity

    edge = SimpleNamespace(relation="supersedes", source="2026-10-01_fact_deadbeef", target=SRC)
    store, graph = _env([{"memory_id": SRC}], {SRC: [edge]})
    assert compute_validity(_page(), store=store, graph=graph)["validity"] == "stale"
    store2, graph2 = _env([{"memory_id": SRC}, {"memory_id": edge.source}], {SRC: [edge]})
    assert compute_validity(_page(sources=(SRC, edge.source)), store=store2, graph=graph2)["validity"] == "ok"


def test_missing_source_is_stale_not_crash():
    from memory.wiki.validity import compute_validity

    store, graph = _env([], {})
    out = compute_validity(_page(), store=store, graph=graph)
    assert out["validity"] == "stale" and "not found" in out["reasons"][0]


def test_stale_process_is_withdrawn():
    from memory.wiki.validity import compute_validity

    store, graph = _env([{"memory_id": SRC, "disputed": True}], {})
    assert compute_validity(_page("process"), store=store, graph=graph)["validity"] == "withdrawn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_wiki_validity.py -v`
Expected: FAIL with `ModuleNotFoundError: memory.wiki.validity`.

- [ ] **Step 3: Implement `validity.py`**

```python
"""Page validity derived from the graph at read time; no background job."""

from __future__ import annotations

from memory.wiki.pages import Page


def compute_validity(page: Page, *, store, graph) -> dict:
    reasons: list[str] = []
    sources = page.sources
    found = {p.get("memory_id"): p for p in (store.get_many(sources) if sources else [])}
    for mid in sources:
        point = found.get(mid)
        if point is None:
            reasons.append(f"source {mid} not found")
            continue
        if point.get("disputed"):
            reasons.append(f"source {mid} disputed")
        for edge in graph.get_edges(mid, direction="in"):
            if getattr(edge, "relation", "") == "supersedes" and getattr(edge, "source", "") not in sources:
                reasons.append(f"source {mid} superseded by {edge.source}")
    if not reasons:
        return {"validity": "ok", "reasons": []}
    # A stale procedure is worse than none: withdraw it from default results.
    return {"validity": "withdrawn" if page.type == "process" else "stale", "reasons": reasons}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_wiki_validity.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memory/wiki/validity.py tests/test_wiki_validity.py
git commit -m "feat(wiki): validity from disputed and superseded sources at read time"
```

---

### Task 4: Index search (`search.py`)

**Files:**
- Create: `src/memory/wiki/search.py`
- Test: `tests/test_wiki_search.py`

**Interfaces:**
- Consumes: `WikiStore.index_entries()`, `WikiStore.read(page_id)`, `split_sections`, `token_estimate` (Tasks 1–2).
- Produces: `search_index(store: WikiStore, query: str, *, project: str | None = None, limit: int = 3, budget_tokens: int = 600, validity_fn=None) -> list[dict]`. Each hit: `{page_id, revision, section_id, title, excerpt, scope, status, last_verified, validity, validity_reasons, sources, score}`. Ranking: in-module BM25 (k1=1.5, b=0.75) over documents = one per live page section: `title + heading + section text`; the best section per page wins; hits with `validity == "withdrawn"` are dropped; results trimmed so the summed token estimate of `excerpt` fields ≤ `budget_tokens` (excerpt = first 300 chars of the section). An empty or all-stopword query returns `[]`.
- Design note (ruling): the Qdrant `BM25Encoder` is bound to the memory collection's fitted vocabulary and sparse vectors; the wiki index is a few hundred short documents, so a 30-line in-memory BM25 is the right tool. No new dependency.

- [ ] **Step 1: Write the failing tests**

```python
"""BM25 over the wiki index with validity filtering and token budget (spec: Read path)."""

import pytest

from memory.wiki.pages import Page
from memory.wiki.store import WikiStore

POLICY = "## Rule {#rule}\n{rule}\n## Why {#why}\nw\n## Exceptions {#exceptions}\ne\n## Sources {#sources}\ns"


def _live(store, pid, title, rule, page_type="policy"):
    fm = {"title": title, "description": title, "page_id": pid, "type": page_type, "project": pid.split("/")[0], "sources": []}
    body = POLICY.format(rule=rule) if page_type == "policy" else (
        "## When {#when}\n" + rule + "\n## Preconditions {#preconditions}\np\n## Steps {#steps}\n1. s [source: 2026-01-01_fact_abcdef12]\n"
        "## Expected output {#expected}\ne\n## Verify {#verify}\nv\n## Stop conditions {#stop}\ns\n## Rollback {#rollback}\nr\n## Known limitations {#limits}\nl"
    )
    store.write_draft(Page(frontmatter=fm, body=body))
    store.approve(pid)


@pytest.fixture
def store(tmp_path):
    s = WikiStore(tmp_path / "wiki")
    _live(s, "demo/policy/prod-go", "Prod go rule", "Never deploy to prod without an explicit go from the owner.")
    _live(s, "demo/policy/commits", "Commit trailer", "Always add the co-author trailer to commits.")
    _live(s, "demo/process/rotate-key", "Rotate gateway key", "Rotate the gateway key when it expires.", page_type="process")
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
    hits = search_index(store, "rule gateway commits", budget_tokens=20)
    assert sum(len(h["excerpt"]) // 4 for h in hits) <= 20


def test_withdrawn_pages_are_dropped(store):
    from memory.wiki.search import search_index

    withdrawn = lambda page: {"validity": "withdrawn", "reasons": ["source disputed"]} if page.type == "process" else {"validity": "ok", "reasons": []}
    hits = search_index(store, "rotate gateway key", validity_fn=withdrawn)
    assert all(h["page_id"] != "demo/process/rotate-key" for h in hits)


def test_empty_or_stopword_query_returns_nothing(store):
    from memory.wiki.search import search_index

    assert search_index(store, "???") == []
    assert search_index(store, "the a of") == []


def test_project_filter(store):
    from memory.wiki.search import search_index

    assert search_index(store, "rule", project="other") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_wiki_search.py -v`
Expected: FAIL with `ModuleNotFoundError: memory.wiki.search`.

- [ ] **Step 3: Implement `search.py`**

```python
"""Small in-memory BM25 over live wiki sections. No model, no Qdrant."""

from __future__ import annotations

import math
import re
from collections import Counter

from memory.wiki.pages import split_sections, token_estimate
from memory.wiki.store import WikiStore

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{1,}")
_STOP = {"the", "a", "an", "of", "to", "and", "or", "is", "in", "on", "for", "with", "how", "do", "we", "i"}
_K1, _B = 1.5, 0.75


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def _documents(store: WikiStore, project: str | None) -> list[dict]:
    docs = []
    for page in store.list_pages("live"):
        if project and page.project != project:
            continue
        title = str(page.frontmatter.get("title") or "")
        for section_id, heading, text in split_sections(page.body):
            docs.append({"page": page, "section_id": section_id, "text": text, "tokens": _tokens(f"{title} {heading} {text}")})
    return docs


def _bm25(query: list[str], docs: list[dict]) -> list[float]:
    n = len(docs)
    avg = (sum(len(d["tokens"]) for d in docs) / n) if n else 0.0
    df = Counter()
    for d in docs:
        for t in set(d["tokens"]):
            df[t] += 1
    scores = []
    for d in docs:
        tf = Counter(d["tokens"])
        s = 0.0
        for q in query:
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * (tf[q] * (_K1 + 1)) / (tf[q] + _K1 * (1 - _B + _B * len(d["tokens"]) / (avg or 1)))
        scores.append(s)
    return scores


def search_index(store: WikiStore, query: str, *, project=None, limit=3, budget_tokens=600, validity_fn=None) -> list[dict]:
    q = _tokens(query)
    if not q:
        return []
    docs = _documents(store, project)
    scores = _bm25(q, docs)
    best: dict[str, tuple[float, dict]] = {}
    for d, s in zip(docs, scores):
        pid = d["page"].page_id
        if s > 0 and (pid not in best or s > best[pid][0]):
            best[pid] = (s, d)
    hits, used = [], 0
    for s, d in sorted(best.values(), key=lambda x: -x[0]):
        page = d["page"]
        validity = validity_fn(page) if validity_fn else {"validity": "ok", "reasons": []}
        if validity["validity"] == "withdrawn":
            continue
        excerpt = d["text"][:300]
        cost = token_estimate(excerpt)
        if hits and used + cost > budget_tokens:
            break
        used += cost
        hits.append({
            "page_id": page.page_id,
            "revision": page.frontmatter.get("revision"),
            "section_id": d["section_id"],
            "title": page.frontmatter.get("title"),
            "excerpt": excerpt,
            "scope": page.frontmatter.get("scope"),
            "status": page.status,
            "last_verified": page.frontmatter.get("last_verified"),
            "validity": validity["validity"],
            "validity_reasons": validity["reasons"],
            "sources": page.sources,
            "score": round(s, 4),
        })
        if len(hits) >= limit:
            break
    return hits
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_wiki_search.py -v`
Expected: 5 PASS. If `test_limit_and_budget_are_enforced` fails on the budget assertion because the first hit alone exceeds 20 tokens, that is by design (the first hit always returns); change the test's budget to 90 and assert `len(hits) < 3`.

- [ ] **Step 5: Commit**

```bash
git add src/memory/wiki/search.py tests/test_wiki_search.py
git commit -m "feat(wiki): in-memory BM25 lookup over live sections with validity and budget"
```

---

### Task 5: Compile step (`compile.py`): worthiness + drafting

**Files:**
- Create: `src/memory/wiki/compile.py`
- Modify: `src/memory/publish.py` (add `llm_config()` returning `(model, base_url, token) | None`, factored out of `_build_synth`; `_build_synth` calls it)
- Test: `tests/test_wiki_compile.py`

**Interfaces:**
- Consumes: `publish._llm_complete(prompt, *, model, base_url, token) -> str`; `publish.llm_config()`; `Page`, `missing_sections`, `has_redaction`, `PAGE_ID_RE`, `slugify` (Task 1).
- Produces:
  - `classify_candidates(memories: list[dict], *, llm: Callable[[str], str], cache: dict) -> list[dict]`: for each memory not in cache (keyed by `memory_id`), prompt the rubric, parse JSON `{"verdict","question","page_type","scope","reasons"}`, store in cache; skip memories whose payload has `disputed` or whose content has a redaction marker (verdict `skip`, reason recorded, no model call). Returns worthy entries `{memory_id, question, page_type, scope, reasons, content}`.
  - `draft_page(memories: list[dict], *, page_type: str, project: str, title: str | None, llm) -> Page`: prompt per type with the required section headings and `{#id}`s, ask for `[source: id]` on every process step; parse to `Page` with frontmatter (`page_id = f"{project}/{page_type}/{slugify(title)}"`, `status: draft`, `revision: 0`, `sources` = memory ids, `scope` from the classifier when all agree else `{"env": "unknown"}`, `confidence`: `high` if ≥2 sources else `medium`); if `missing_sections` non-empty, set frontmatter `needs: [...]`.
  - `RUBRIC_PROMPT`, `DRAFT_PROMPTS: dict[page_type, str]` module constants.
  - `make_llm() -> Callable[[str], str] | None` using `llm_config()`.

- [ ] **Step 1: Write the failing tests**

```python
"""Worthiness classification and page drafting with a fake LLM (spec: Worthiness, Pipeline)."""

import json


def _mem(mid, content, **extra):
    return {"memory_id": mid, "content": content, "project": "demo", **extra}


def test_classify_skips_disputed_and_redacted_without_calling_llm():
    from memory.wiki.compile import classify_candidates

    calls = []
    llm = lambda prompt: (calls.append(prompt), json.dumps({"verdict": "worthy", "question": "q", "page_type": "policy", "scope": {}, "reasons": ["r"]}))[1]
    cache = {}
    out = classify_candidates(
        [_mem("2026-01-01_fact_a1", "never deploy without go", ), _mem("2026-01-02_fact_b2", "pack [REDACTED] rotate"), _mem("2026-01-03_fact_c3", "x", disputed=True)],
        llm=llm, cache=cache,
    )
    assert [o["memory_id"] for o in out] == ["2026-01-01_fact_a1"]
    assert len(calls) == 1
    assert cache["2026-01-02_fact_b2"]["verdict"] == "skip" and cache["2026-01-03_fact_c3"]["verdict"] == "skip"


def test_classify_uses_cache_and_tolerates_bad_json():
    from memory.wiki.compile import classify_candidates

    cache = {"2026-01-01_fact_a1": {"verdict": "worthy", "question": "q", "page_type": "reference", "scope": {}, "reasons": []}}
    llm = lambda prompt: "not json"
    out = classify_candidates([_mem("2026-01-01_fact_a1", "x"), _mem("2026-01-04_fact_d4", "y")], llm=llm, cache=cache)
    assert [o["memory_id"] for o in out] == ["2026-01-01_fact_a1"]
    assert cache["2026-01-04_fact_d4"]["verdict"] == "skip" and "unparseable" in cache["2026-01-04_fact_d4"]["reasons"][0]


def test_draft_process_page_has_sections_sources_and_page_id():
    from memory.wiki.compile import draft_page

    body = (
        "## When {#when}\nkey expired [source: 2026-01-01_fact_a1]\n## Preconditions {#preconditions}\nadmin\n"
        "## Steps {#steps}\n1. export key [source: 2026-01-01_fact_a1]\n## Expected output {#expected}\nok\n"
        "## Verify {#verify}\ncurl 200\n## Stop conditions {#stop}\n401\n## Rollback {#rollback}\nrestore\n## Known limitations {#limits}\nnone\n"
    )
    llm = lambda prompt: "TITLE: Rotate the gateway key\n" + body
    page = draft_page([_mem("2026-01-01_fact_a1", "rotate key when expired")], page_type="process", project="demo", title=None, llm=llm)
    assert page.page_id == "demo/process/rotate-the-gateway-key"
    assert page.status == "draft" and page.sources == ["2026-01-01_fact_a1"]
    assert "needs" not in page.frontmatter
    assert page.frontmatter["sidebar_position"] == 10 and page.frontmatter["tags"] == ["process"]


def test_draft_with_missing_sections_marks_needs():
    from memory.wiki.compile import draft_page

    llm = lambda prompt: "TITLE: Half\n## Rule {#rule}\nr\n### extra\nignored\n## Why {#why}\nw\n"
    page = draft_page([_mem("2026-01-01_fact_a1", "x")], page_type="policy", project="demo", title=None, llm=llm)
    assert page.frontmatter["needs"] == ["exceptions", "sources"]


def test_make_llm_is_none_when_unconfigured(monkeypatch):
    from memory.wiki.compile import make_llm

    for k in ("REKALL_PUBLISH_MODEL", "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert make_llm() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_wiki_compile.py -v`
Expected: FAIL with `ModuleNotFoundError: memory.wiki.compile`.

- [ ] **Step 3: Factor `llm_config()` out of `publish._build_synth`**

In `src/memory/publish.py`, above `_build_synth`:

```python
def llm_config() -> tuple[str, str, str] | None:
    """(model, base_url, token) for the Anthropic-compatible endpoint, or None when unconfigured."""
    model = os.getenv("REKALL_PUBLISH_MODEL") or os.getenv("ANTHROPIC_MODEL")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    token = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
    if not (model and base_url and token):
        return None
    return model, base_url, token
```

and replace the three lookups plus the `if not (...)` in `_build_synth` with `cfg = llm_config(); if cfg is None: return None, "raw"; model, base_url, token = cfg`. Run `uv run --extra dev pytest tests/test_server_publish.py -q` to confirm nothing changed.

- [ ] **Step 4: Implement `compile.py`**

```python
"""Compile step: worthiness classification and page drafting. The only module that calls a model."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from memory.publish import _llm_complete, llm_config
from memory.wiki.pages import Page, has_redaction, missing_sections, required_sections, slugify

RUBRIC_PROMPT = """You decide whether ONE saved memory is worth compiling into a team wiki page.
Worthy only if ALL hold: (1) it answers a concrete future question someone would ask; write that question;
(2) it holds an actionable lesson, a standing rule with its reason, or a fact people look up; status updates,
changelog, tool traces and victory logs are never worthy; (3) its evidence is identifiable; (4) its applicability
(machine, version, environment) is stated or inferable; (5) it is complete enough to act on.
Answer with JSON only: {{"verdict": "worthy"|"skip", "question": "...", "page_type": "process"|"policy"|"reference"|"entity",
"scope": {{"env": "...", "versions": "..."}}, "reasons": ["..."]}}
MEMORY:
{content}"""

_SECTION_TEMPLATES = {
    "process": "## When {#when}\n## Preconditions {#preconditions}\n## Steps {#steps}\n## Expected output {#expected}\n## Verify {#verify}\n## Stop conditions {#stop}\n## Rollback {#rollback}\n## Known limitations {#limits}",
    "policy": "## Rule {#rule}\n## Why {#why}\n## Exceptions {#exceptions}\n## Sources {#sources}",
    "reference": "## Facts {#facts}\n## Sources {#sources}",
    "entity": "## What it is {#what}\n## Related pages {#related}\n## Sources {#sources}",
}
DRAFT_PROMPTS = {
    t: (
        "Write ONE markdown wiki page of type {page_type} from the memories below. First line: `TITLE: <title>`. "
        "Then exactly these H2 sections with their ids, in order:\n" + tmpl + "\n"
        "Every claim and every step ends with `[source: <memory_id>]` using only the ids given. Never invent steps. "
        "If the memories cannot support a section, write `Unknown.` in it. No preamble, no closing remarks.\n"
        "MEMORIES:\n{memories}"
    )
    for t, tmpl in _SECTION_TEMPLATES.items()
}
_SIDEBAR = {"process": 10, "policy": 20, "reference": 30, "entity": 40}
_TITLE_RE = re.compile(r"^TITLE:\s*(.+)$", re.M)


def make_llm() -> Callable[[str], str] | None:
    cfg = llm_config()
    if cfg is None:
        return None
    model, base_url, token = cfg
    return lambda prompt: _llm_complete(prompt, model=model, base_url=base_url, token=token)


def _parse_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def classify_candidates(memories: list[dict], *, llm: Callable[[str], str], cache: dict) -> list[dict]:
    worthy = []
    for m in memories:
        mid = m.get("memory_id")
        content = str(m.get("content") or "")
        if not mid:
            continue
        if mid not in cache:
            if m.get("disputed"):
                cache[mid] = {"verdict": "skip", "reasons": ["disputed"]}
            elif has_redaction(content):
                cache[mid] = {"verdict": "skip", "reasons": ["redacted content"]}
            else:
                data = _parse_json(llm(RUBRIC_PROMPT.format(content=content[:4000])))
                if data is None or data.get("verdict") not in ("worthy", "skip") or data.get("page_type") not in (*_SECTION_TEMPLATES, None):
                    data = {"verdict": "skip", "reasons": ["unparseable classifier output"]}
                cache[mid] = data
        entry = cache[mid]
        if entry.get("verdict") == "worthy":
            worthy.append({"memory_id": mid, "content": content, "question": entry.get("question"),
                           "page_type": entry.get("page_type") or "reference", "scope": entry.get("scope") or {}, "reasons": entry.get("reasons") or []})
    return worthy


def draft_page(memories: list[dict], *, page_type: str, project: str, title: str | None, llm: Callable[[str], str], scopes: list[dict] | None = None) -> Page:
    if page_type not in _SECTION_TEMPLATES:
        raise ValueError("invalid page_type")
    notes = "\n".join(f"- [{m['memory_id']}] {str(m.get('content') or '').strip()}" for m in memories)
    text = llm(DRAFT_PROMPTS[page_type].format(page_type=page_type, memories=notes))
    found = _TITLE_RE.search(text)
    final_title = title or (found.group(1).strip() if found else f"{page_type} page")
    body = _TITLE_RE.sub("", text, count=1).strip()
    scope = scopes[0] if scopes and all(s == scopes[0] for s in scopes) else {"env": "unknown"}
    fm = {
        "title": final_title,
        "description": final_title,
        "sidebar_position": _SIDEBAR[page_type],
        "tags": [page_type],
        "page_id": f"{project}/{page_type}/{slugify(final_title)}",
        "type": page_type,
        "project": project,
        "scope": scope,
        "status": "draft",
        "revision": 0,
        "updated": None,
        "last_verified": None,
        "confidence": "high" if len(memories) >= 2 else "medium",
        "human_edited": False,
        "sources": [m["memory_id"] for m in memories],
    }
    page = Page(frontmatter=fm, body=body)
    missing = missing_sections(page)
    if missing:
        page = Page(frontmatter=dict(fm, needs=missing), body=body)
    return page
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_wiki_compile.py tests/test_server_publish.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/memory/wiki/compile.py src/memory/publish.py tests/test_wiki_compile.py
git commit -m "feat(wiki): worthiness classifier and page drafting on the publish LLM client"
```

---

### Task 6: REST routes and the lifecycle test

**Files:**
- Modify: `src/memory/manager.py` (add `wiki` property), `src/server.py` (routes after the `/api/memory/publish/status` route), `README.md` (REST table rows)
- Test: `tests/test_server_wiki.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces (all under `_ok`/`_bad_request`/`_server_error`, manager via `_get_memory_manager()`; `manager.wiki -> WikiStore` lazily built at `manager.memory_dir / "wiki"`):
  - `GET /api/wiki/index?project=` → `{"entries": [...]}` (index entries, filtered by project; each entry also gains `validity` via `compute_validity` on the live page)
  - `GET /api/wiki/search?q=&project=&limit=3` → `{"hits": [...]}` (`search_index` with `validity_fn=lambda p: compute_validity(p, store=manager.store, graph=manager.knowledge_graph)`)
  - `GET /api/wiki/page/{page_id:path}?section=&full=` → `{"page_id","revision","title","type","project","scope","status","last_verified","validity","validity_reasons","sections":[ids],"section_id","body","token_estimate","over_budget"}`; default section: `steps` for process, else first; `full=1` returns the whole body; body over the budget (1,500 section / 3,000 full) is truncated at a paragraph boundary with `over_budget: true`, except `process` pages which are returned whole with `over_budget: true`.
  - `GET /api/wiki/drafts` → `{"drafts": [{page_id,title,type,project,needs,unsourced_steps,has_redaction}]}`
  - `POST /api/wiki/drafts/{page_id:path}/approve` → `{"page": {...frontmatter}}`; 400 with the `ValueError` message on refusal
  - `POST /api/wiki/drafts/{page_id:path}/reject` body `{"reason": str}` → `{"status": "rejected"}`
  - `PUT /api/wiki/drafts/{page_id:path}` body `{"body": str, "frontmatter"?: {...}}` → writes the draft with `human_edited: true` → `{"page": {...}}`
  - `GET /api/wiki/candidates?project=&limit=200` → `{"status": "unconfigured"}` when `make_llm()` is None; else `{"candidates": [...]}` using `classify_candidates` over `manager.store.scroll(filters={"project": project}, limit=limit)` with the cache persisted at `wiki/_cache/worthiness.json`
  - `POST /api/wiki/draft` body `{"memory_ids": [...], "page_type": str, "title"?: str, "project"?: str}` → `{"status": "unconfigured"}` or `{"page": {...frontmatter}, "needs": [...]}`; project defaults to the first memory's project; memories loaded with `manager.store.get_many`.

- [ ] **Step 1: Write the failing tests**

```python
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
    from memory.wiki.store import WikiStore
    import server

    manager = MagicMock()
    manager.memory_dir = tmp_path
    manager.wiki = WikiStore(tmp_path / "wiki")
    manager.store.get_many.side_effect = lambda ids, **kw: [{"memory_id": i, "content": f"content {i}", "project": "demo"} for i in ids]
    manager.store.scroll.return_value = [{"memory_id": "2026-01-01_fact_a1", "content": "never deploy without go", "project": "demo"}]
    manager.knowledge_graph.get_edges.return_value = []
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def _fake_llm(monkeypatch, body=PROCESS_BODY, title="Rotate the gateway key"):
    monkeypatch.setattr("server.make_wiki_llm", lambda: (lambda prompt: (
        json.dumps({"verdict": "worthy", "question": "how to rotate", "page_type": "process", "scope": {"env": "all"}, "reasons": ["r"]})
        if "Answer with JSON" in prompt else f"TITLE: {title}\n{body}")))


def test_candidates_and_draft_are_unconfigured_without_llm(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr("server.make_wiki_llm", lambda: None)
    assert tc.get("/api/wiki/candidates?project=demo").json()["status"] == "unconfigured"
    assert tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"}).json()["status"] == "unconfigured"


def test_lifecycle_candidates_draft_approve_search_read_and_stale(client, monkeypatch):
    tc, manager = client
    _fake_llm(monkeypatch)
    cands = tc.get("/api/wiki/candidates?project=demo").json()["candidates"]
    assert cands[0]["memory_id"] == "2026-01-01_fact_a1" and cands[0]["page_type"] == "process"
    r = tc.post("/api/wiki/draft", json={"memory_ids": ["2026-01-01_fact_a1"], "page_type": "process"})
    assert r.status_code == 200 and r.json()["page"]["page_id"] == "demo/process/rotate-the-gateway-key"
    drafts = tc.get("/api/wiki/drafts").json()["drafts"]
    assert drafts[0]["unsourced_steps"] == 0 and drafts[0]["needs"] == []
    assert tc.post("/api/wiki/drafts/demo/process/rotate-the-gateway-key/approve").status_code == 200
    hits = tc.get("/api/wiki/search?q=rotate gateway key").json()["hits"]
    assert hits[0]["page_id"] == "demo/process/rotate-the-gateway-key" and hits[0]["validity"] == "ok"
    page = tc.get("/api/wiki/page/demo/process/rotate-the-gateway-key").json()
    assert page["section_id"] == "steps" and "export key" in page["body"] and page["over_budget"] is False
    manager.store.get_many.side_effect = lambda ids, **kw: [{"memory_id": i, "content": "c", "project": "demo", "disputed": True} for i in ids]
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
    r = tc.put("/api/wiki/drafts/demo/process/rotate-the-gateway-key", json={"body": PROCESS_BODY.replace("admin", "root")})
    assert r.json()["page"]["human_edited"] is True
    assert tc.post("/api/wiki/drafts/demo/process/rotate-the-gateway-key/reject", json={"reason": "dup"}).json()["status"] == "rejected"
    assert tc.get("/api/wiki/drafts").json()["drafts"] == []


def test_page_404_and_bad_id(client):
    tc, _ = client
    assert tc.get("/api/wiki/page/demo/process/nope").status_code == 404
    assert tc.get("/api/wiki/page/../x").status_code in (400, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_server_wiki.py -v`
Expected: FAIL (404s for every route, `AttributeError: server.make_wiki_llm`).

- [ ] **Step 3: Add the `wiki` property to `MemoryManager`**

In `src/memory/manager.py`, next to the `knowledge_graph` property (around line 368):

```python
    @property
    def wiki(self):
        """Lazily built file store under the memory dir; tests may replace it."""
        if getattr(self, "_wiki", None) is None:
            from memory.wiki.store import WikiStore

            self._wiki = WikiStore(self.memory_dir / "wiki")
        return self._wiki
```

- [ ] **Step 4: Add the routes to `src/server.py`**

After the `/api/memory/publish/status` route:

```python
# ---- wiki (phase 1) -------------------------------------------------------
from memory.wiki.compile import classify_candidates, draft_page, make_llm as make_wiki_llm  # noqa: E402
from memory.wiki.pages import PAGE_ID_RE, Page, has_redaction, missing_sections, split_sections, token_estimate, unsourced_steps  # noqa: E402
from memory.wiki.search import search_index  # noqa: E402
from memory.wiki.validity import compute_validity  # noqa: E402

_WIKI_SECTION_BUDGET, _WIKI_FULL_BUDGET = 1500, 3000


def _wiki_validity_fn(manager):
    return lambda page: compute_validity(page, store=manager.store, graph=manager.knowledge_graph)


def _wiki_page_id(request) -> str | None:
    page_id = request.path_params.get("page_id", "")
    return page_id if PAGE_ID_RE.match(page_id) else None


def _wiki_header(page: Page, validity: dict) -> dict:
    fm = page.frontmatter
    return {"page_id": page.page_id, "revision": fm.get("revision"), "title": fm.get("title"), "type": page.type,
            "project": page.project, "scope": fm.get("scope"), "status": page.status, "last_verified": fm.get("last_verified"),
            "validity": validity["validity"], "validity_reasons": validity["reasons"], "sources": page.sources}


def _trim(text: str, budget: int) -> tuple[str, bool]:
    if token_estimate(text) <= budget:
        return text, False
    cut = text[: budget * 4]
    boundary = cut.rfind("\n\n")
    return (cut[:boundary] if boundary > 0 else cut), True


@mcp.custom_route("/api/wiki/index", methods=["GET"])
async def api_wiki_index(request):
    try:
        project = _safe_project(request.query_params.get("project"))
        manager = _get_memory_manager()
        vf = _wiki_validity_fn(manager)
        entries = []
        for entry in manager.wiki.index_entries():
            if project and entry.get("project") != project:
                continue
            page = manager.wiki.read(entry["page_id"], "live")
            entry["validity"] = vf(page)["validity"] if page else "stale"
            entries.append(entry)
        return _ok({"entries": entries})
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/search", methods=["GET"])
async def api_wiki_search(request):
    try:
        q = request.query_params.get("q", "")
        project = _safe_project(request.query_params.get("project"))
        limit = _read_int(request.query_params, "limit", 3, lo=1, hi=10)
        manager = _get_memory_manager()
        hits = search_index(manager.wiki, q, project=project, limit=limit, validity_fn=_wiki_validity_fn(manager))
        return _ok({"hits": hits})
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/page/{page_id:path}", methods=["GET"])
async def api_wiki_page(request):
    from starlette.responses import JSONResponse

    page_id = _wiki_page_id(request)
    if page_id is None:
        return _bad_request("invalid page_id")
    try:
        manager = _get_memory_manager()
        page = manager.wiki.read(page_id, "live")
        if page is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        validity = _wiki_validity_fn(manager)(page)
        sections = split_sections(page.body)
        ids = [s[0] for s in sections]
        full = request.query_params.get("full", "").lower() in ("1", "true")
        wanted = request.query_params.get("section") or ("steps" if page.type == "process" else (ids[0] if ids else None))
        if full:
            body, over = _trim(page.body, _WIKI_FULL_BUDGET) if page.type != "process" else (page.body, token_estimate(page.body) > _WIKI_FULL_BUDGET)
            section_id = None
        else:
            chosen = next((s for s in sections if s[0] == wanted), sections[0] if sections else ("", "", ""))
            section_id = chosen[0] or None
            text = f"## {chosen[1]}\n{chosen[2]}" if chosen[1] else page.body
            body, over = _trim(text, _WIKI_SECTION_BUDGET) if page.type != "process" else (text, token_estimate(text) > _WIKI_SECTION_BUDGET)
        header = _wiki_header(page, validity)
        if validity["validity"] == "withdrawn":
            body = "> WARNING: this procedure is withdrawn: " + "; ".join(validity["reasons"]) + "\n\n" + body
        return _ok({**header, "sections": ids, "section_id": section_id, "body": body, "token_estimate": token_estimate(body), "over_budget": over})
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/drafts", methods=["GET"])
async def api_wiki_drafts(request):
    try:
        manager = _get_memory_manager()
        drafts = [{"page_id": p.page_id, "title": p.frontmatter.get("title"), "type": p.type, "project": p.project,
                   "needs": list(p.frontmatter.get("needs") or missing_sections(p)), "unsourced_steps": unsourced_steps(p),
                   "has_redaction": has_redaction(p.body)} for p in manager.wiki.list_pages("draft")]
        return _ok({"drafts": drafts})
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/drafts/{page_id:path}/approve", methods=["POST"])
async def api_wiki_approve(request):
    page_id = _wiki_page_id(request)
    if page_id is None:
        return _bad_request("invalid page_id")
    try:
        page = _get_memory_manager().wiki.approve(page_id)
        return _ok({"page": page.frontmatter})
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/drafts/{page_id:path}/reject", methods=["POST"])
async def api_wiki_reject(request):
    page_id = _wiki_page_id(request)
    if page_id is None:
        return _bad_request("invalid page_id")
    try:
        body = await request.json()
        reason = str((body or {}).get("reason") or "").strip() or "no reason given"
        _get_memory_manager().wiki.reject(page_id, reason)
        return _ok({"status": "rejected"})
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/drafts/{page_id:path}", methods=["PUT"])
async def api_wiki_edit_draft(request):
    page_id = _wiki_page_id(request)
    if page_id is None:
        return _bad_request("invalid page_id")
    try:
        body = await request.json()
        manager = _get_memory_manager()
        draft = manager.wiki.read(page_id, "draft")
        if draft is None:
            return _bad_request("no draft for page_id")
        fm = dict(draft.frontmatter, **((body or {}).get("frontmatter") or {}), human_edited=True)
        page = Page(frontmatter=fm, body=str((body or {}).get("body", draft.body)))
        manager.wiki.write_draft(page)
        return _ok({"page": page.frontmatter})
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/candidates", methods=["GET"])
async def api_wiki_candidates(request):
    try:
        llm = make_wiki_llm()
        if llm is None:
            return _ok({"status": "unconfigured"})
        project = _safe_project(request.query_params.get("project"))
        limit = _read_int(request.query_params, "limit", 200, lo=1, hi=2000)
        manager = _get_memory_manager()
        cache_path = manager.wiki.root / "_cache" / "worthiness.json"
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        points = manager.store.scroll(filters={"project": project} if project else None, limit=limit)
        candidates = classify_candidates(points, llm=llm, cache=cache)
        cache_path.write_text(json.dumps(cache, indent=0))
        return _ok({"candidates": candidates})
    except Exception as e:
        return _server_error(str(e))


@mcp.custom_route("/api/wiki/draft", methods=["POST"])
async def api_wiki_draft(request):
    try:
        llm = make_wiki_llm()
        if llm is None:
            return _ok({"status": "unconfigured"})
        body = await request.json()
        ids = body.get("memory_ids") or []
        if not isinstance(ids, list) or not ids:
            return _bad_request("memory_ids must be a non-empty list")
        manager = _get_memory_manager()
        memories = manager.store.get_many(ids)
        if not memories:
            return _bad_request("no memories found")
        project = _safe_project(body.get("project")) or memories[0].get("project") or "general"
        page = draft_page(memories, page_type=str(body.get("page_type") or "reference"), project=project, title=body.get("title"), llm=llm)
        manager.wiki.write_draft(page)
        return _ok({"page": page.frontmatter, "needs": list(page.frontmatter.get("needs") or [])})
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _server_error(str(e))
```

Make sure `json` is imported at the top of `server.py` (it is used by other routes; verify with `grep -n "^import json" src/server.py`).

- [ ] **Step 5: README rows**

In the REST API table add, in the same style as the kb row:

```
| `/api/wiki/index` | GET | Wiki index entries with read-time validity (`project=` filter) |
| `/api/wiki/search` | GET | BM25 lookup over live sections, ≤3 hits, ≤600 tokens (`q=`, `project=`, `limit=`) |
| `/api/wiki/page/{page_id}` | GET | One section (default) or `full=1`; process pages never truncated |
| `/api/wiki/drafts` | GET | Pending drafts with `needs`, unsourced steps, redaction flags |
| `/api/wiki/drafts/{page_id}` | PUT, POST `/approve`, POST `/reject` | Edit, approve (history + live + index + log), reject with reason |
| `/api/wiki/candidates` | GET | Worthiness classifier over a project's memories (`unconfigured` without a model) |
| `/api/wiki/draft` | POST | Draft a page from `memory_ids` and `page_type` (`unconfigured` without a model) |
```

- [ ] **Step 6: Run tests**

Run: `uv run --extra dev pytest tests/test_server_wiki.py tests/test_server_events.py tests/test_server_publish.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/memory/manager.py src/server.py README.md tests/test_server_wiki.py
git commit -m "feat(wiki): REST routes for index, search, page, drafts, candidates, draft"
```

---

### Task 7: MCP tools `wiki_lookup` / `wiki_read` with `wiki_delivered` events

**Files:**
- Modify: `src/tools/builtin/memory.py` (register two tools after `recall_memories`), `claude/hooks/rekall-provenance.sh` (allowlist), `tests/test_provenance_hook.py`
- Test: `tests/test_tools_wiki.py`

**Interfaces:**
- Consumes: `manager.wiki`, `search_index`, `compute_validity`, `split_sections`, `token_estimate`; `manager.record_event(event_type=, project=, agent=, source=, memory_ids=, payload=, session_id=)`.
- Produces:
  - `wiki_lookup(query: str, project: str | None = None, limit: int = 3, cwd: str | None = None, session_id: str | None = None, agent: str | None = None) -> str`: compact markdown, one hit per line: `- [{title}](wiki:{page_id}#{section_id}) rev {revision} · {validity}{" (" + "; ".join(reasons) + ")" if reasons} · verified {last_verified}\n  {excerpt}`; "No wiki match." when empty. Emits one `wiki_delivered` event with `payload={"query", "page_ids": [...], "token_estimate", "session_id", "surface": "wiki_lookup"}`.
  - `wiki_read(page_id: str, section: str | None = None, full: bool = False, cwd=None, session_id=None, agent=None) -> str`: header line `# {title} ({page_id} rev {revision}) · {validity}` then the warning when withdrawn, then the body; emits `wiki_delivered` with `{"page_id", "revision", "section_id", "token_estimate", "session_id", "surface": "wiki_read"}`.
  - Provenance hook allowlist gains `mcp__memory__wiki_lookup|mcp__rekall__wiki_lookup|mcp__memory__wiki_read|mcp__rekall__wiki_read`.

- [ ] **Step 1: Write the failing tests**

```python
"""wiki_lookup / wiki_read MCP tools emit wiki_delivered events (spec: Read path, Measurement)."""

from unittest.mock import MagicMock

import pytest

from memory.wiki.pages import Page
from memory.wiki.store import WikiStore

BODY = (
    "## When {#when}\nkey expired [source: 2026-01-01_fact_a1]\n## Preconditions {#preconditions}\nadmin\n"
    "## Steps {#steps}\n1. export key [source: 2026-01-01_fact_a1]\n## Expected output {#expected}\nok\n"
    "## Verify {#verify}\ncurl 200\n## Stop conditions {#stop}\n401\n## Rollback {#rollback}\nrestore\n## Known limitations {#limits}\nnone\n"
)


def _bind(provider, tool_registry):
    capture_tool, registered = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider.register(FakeMCP())
    return registered


@pytest.fixture
def tools(tmp_path, tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    manager = MagicMock()
    manager.wiki = WikiStore(tmp_path / "wiki")
    manager.store.get_many.side_effect = lambda ids, **kw: [{"memory_id": i} for i in ids]
    manager.knowledge_graph.get_edges.return_value = []
    fm = {"title": "Rotate gateway key", "description": "d", "page_id": "demo/process/rotate-key", "type": "process", "project": "demo", "sources": ["2026-01-01_fact_a1"]}
    manager.wiki.write_draft(Page(frontmatter=fm, body=BODY))
    manager.wiki.approve("demo/process/rotate-key")
    provider = OptimizedMemoryTools()
    provider._manager = manager
    return _bind(provider, tool_registry), manager


@pytest.mark.asyncio
async def test_wiki_lookup_returns_hits_and_emits_event(tools):
    registered, manager = tools
    out = await registered["wiki_lookup"](query="rotate gateway key", session_id="s1", agent="codex")
    assert "wiki:demo/process/rotate-key#" in out and "rev 1" in out and "ok" in out
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "wiki_delivered" and kw["payload"]["surface"] == "wiki_lookup"
    assert kw["payload"]["page_ids"] == ["demo/process/rotate-key"] and kw["payload"]["session_id"] == "s1" and kw["agent"] == "codex"


@pytest.mark.asyncio
async def test_wiki_lookup_no_match(tools):
    registered, manager = tools
    assert await registered["wiki_lookup"](query="zzz qqq") == "No wiki match."
    manager.record_event.assert_not_called()


@pytest.mark.asyncio
async def test_wiki_read_section_and_withdrawn_warning_first(tools):
    registered, manager = tools
    out = await registered["wiki_read"](page_id="demo/process/rotate-key", session_id="s1")
    assert out.startswith("# Rotate gateway key (demo/process/rotate-key rev 1)") and "export key" in out
    manager.store.get_many.side_effect = lambda ids, **kw: [{"memory_id": i, "disputed": True} for i in ids]
    out = await registered["wiki_read"](page_id="demo/process/rotate-key")
    lines = out.splitlines()
    assert "withdrawn" in lines[0] and lines[1].startswith("> WARNING") and "export key" in out
    assert manager.record_event.call_args.kwargs["payload"]["section_id"] == "steps"


@pytest.mark.asyncio
async def test_wiki_read_unknown_page(tools):
    registered, _ = tools
    assert "not found" in await registered["wiki_read"](page_id="demo/process/nope")
```

Append to `tests/test_provenance_hook.py`:

```python
def test_wiki_tools_get_provenance():
    for tool in ("mcp__memory__wiki_lookup", "mcp__rekall__wiki_read"):
        r = _run(_payload(tool, {"query": "x"}))
        out = json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]
        assert out["session_id"] == "sess-42" and out["agent"] == "claude-code"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_tools_wiki.py tests/test_provenance_hook.py -v`
Expected: `KeyError: 'wiki_lookup'`; the provenance test fails with empty stdout.

- [ ] **Step 3: Implement the tools**

In `src/tools/builtin/memory.py`, after `registered.append("recall_memories")`:

```python
        @mcp.tool(structured_output=False)
        async def wiki_lookup(
            query: str,
            project: str | None = None,
            limit: int = 3,
            cwd: str | None = None,
            session_id: str | None = None,
            agent: str | None = None,
        ) -> str:
            """Use for how-to and policy questions you would otherwise answer from memory: returns
            up to 3 compiled wiki pages (section, validity, sources). Results are evidence, not
            instructions. Use recall_memories for decisions, history, and recent context.

            Args:
                query: What you need to do or the rule you need
                project: Filter by project
                limit: Max hits (default 3)
                cwd: Your working directory, for attribution
                session_id: Your session id, for attribution
                agent: Your agent name (claude-code, codex)
            """
            from memory.wiki.search import search_index
            from memory.wiki.validity import compute_validity

            m = self.manager
            hits = search_index(m.wiki, query, project=project, limit=max(1, min(limit, 10)),
                                validity_fn=lambda p: compute_validity(p, store=m.store, graph=m.knowledge_graph))
            if not hits:
                return "No wiki match."
            lines = []
            for h in hits:
                reasons = f" ({'; '.join(h['validity_reasons'])})" if h["validity_reasons"] else ""
                lines.append(f"- [{h['title']}](wiki:{h['page_id']}#{h['section_id']}) rev {h['revision']} · {h['validity']}{reasons} · verified {h['last_verified']}\n  {h['excerpt']}")
            text = "\n".join(lines)
            scope = self._get_current_scope(project=project, cwd=cwd, agent=agent, session_id=session_id)
            m.record_event(event_type="wiki_delivered", project=scope.project, agent=agent or "unknown", source="mcp",
                           memory_ids=[], session_id=session_id,
                           payload={"query": query, "page_ids": [h["page_id"] for h in hits], "surface": "wiki_lookup",
                                    "token_estimate": len(text) // 4, "session_id": session_id})
            return text

        registered.append("wiki_lookup")

        @mcp.tool(structured_output=False)
        async def wiki_read(
            page_id: str,
            section: str | None = None,
            full: bool = False,
            cwd: str | None = None,
            session_id: str | None = None,
            agent: str | None = None,
        ) -> str:
            """Read one wiki page section (default: steps for a process) or the full page.
            A withdrawn procedure comes back with a warning first; treat it as unverified.

            Args:
                page_id: From wiki_lookup, e.g. demo/process/rotate-key
                section: Section id (when, steps, verify, rollback, rule, ...)
                full: Return the whole page
                cwd: Your working directory, for attribution
                session_id: Your session id, for attribution
                agent: Your agent name (claude-code, codex)
            """
            from memory.wiki.pages import split_sections
            from memory.wiki.validity import compute_validity

            m = self.manager
            page = m.wiki.read(page_id, "live")
            if page is None:
                return f"Wiki page not found: {page_id}"
            validity = compute_validity(page, store=m.store, graph=m.knowledge_graph)
            sections = split_sections(page.body)
            wanted = section or ("steps" if page.type == "process" else (sections[0][0] if sections else None))
            if full or not sections:
                body, section_id = page.body, None
            else:
                chosen = next((s for s in sections if s[0] == wanted), sections[0])
                body, section_id = f"## {chosen[1]}\n{chosen[2]}", chosen[0]
            header = f"# {page.frontmatter.get('title')} ({page.page_id} rev {page.frontmatter.get('revision')}) · {validity['validity']}"
            if validity["validity"] == "withdrawn":
                body = "> WARNING: this procedure is withdrawn: " + "; ".join(validity["reasons"]) + "\n" + body
            text = f"{header}\n{body}"
            scope = self._get_current_scope(project=page.project, cwd=cwd, agent=agent, session_id=session_id)
            m.record_event(event_type="wiki_delivered", project=scope.project, agent=agent or "unknown", source="mcp",
                           memory_ids=[], session_id=session_id,
                           payload={"page_id": page.page_id, "revision": page.frontmatter.get("revision"), "section_id": section_id,
                                    "surface": "wiki_read", "token_estimate": len(text) // 4, "session_id": session_id})
            return text

        registered.append("wiki_read")
```

Provenance hook: extend the `case` in `claude/hooks/rekall-provenance.sh`:

```bash
  mcp__memory__wiki_lookup|mcp__rekall__wiki_lookup) ;;
  mcp__memory__wiki_read|mcp__rekall__wiki_read) ;;
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest tests/test_tools_wiki.py tests/test_provenance_hook.py tests/test_tools_provenance.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/builtin/memory.py claude/hooks/rekall-provenance.sh tests/test_tools_wiki.py tests/test_provenance_hook.py
git commit -m "feat(wiki): wiki_lookup and wiki_read MCP tools with wiki_delivered events"
```

---

### Task 8: Measurement: hooks, fold, report count wiki deliveries

**Files:**
- Modify: `claude/hooks/rekall-session-end.sh` (embedded Python), `codex/hooks/rekall_hook.py` (`summarize_session`), `src/memory/sessions.py` (no change expected; verify), `scripts/utility_report.py` (per-surface coverage)
- Test: `tests/test_hooks_session.py`, `tests/test_codex_hooks.py`, `tests/test_utility_report.py`

**Interfaces:**
- Consumes: Task 7 output formats (`wiki:<page_id>#<section>` links in lookup; `(<page_id> rev N)` header in read).
- Produces: `session_summary.delivered.wiki: [page_id...]` (ids only, no revision), `referenced` may contain page ids; `compute_citation_coverage_by_surface(summaries) -> dict[surface, {delivered, referenced, coverage}]` in the report, printed as one line per surface after the existing total.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_session.py` (reuse `_run_session_end`, `_transcript_lines` helpers from the earlier branch; `PAGE = "demo/process/rotate-key"`):

```python
PAGE = "demo/process/rotate-key"


def test_session_end_counts_wiki_deliveries_and_page_references(tmp_path):
    lookup_use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "w1", "name": "mcp__memory__wiki_lookup", "input": {"query": "rotate"}}]}}
    lookup_result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "w1", "content": [{"type": "text", "text": f"- [Rotate](wiki:{PAGE}#steps) rev 1 · ok · verified 2026-10-09\n  export key"}]}]}}
    cites = {"type": "assistant", "message": {"content": [{"type": "text", "text": f"Following {PAGE} step 1."}]}}
    r, body = _run_session_end(tmp_path, [lookup_use, lookup_result, cites])
    assert r.returncode == 0
    assert body["delivered"]["wiki"] == [PAGE] and body["delivered"]["explicit"] == []
    assert body["referenced"] == [PAGE]
    assert body["recalled_ids"] == []
```

Append to `tests/test_codex_hooks.py` (same fixture style as the earlier `test_summarize_session_reports_delivered_and_referenced`):

```python
def test_summarize_session_counts_wiki_pages(hook_module):
    page = "demo/process/rotate-key"
    lines = [
        json.dumps({"type": "tool_call", "call_id": "w", "tool_name": "wiki_lookup", "arguments": {"query": "rotate"}}),
        json.dumps({"type": "tool_result", "call_id": "w", "content": f"- [Rotate](wiki:{page}#steps) rev 1 · ok"}),
        json.dumps({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": f"Per {page}, export the key."}]}),
    ]
    summary = hook_module.summarize_session({"session_id": "s", "cwd": "/repo"}, lines)
    assert summary["delivered"]["wiki"] == [page] and summary["referenced"] == [page]
```

Append to `tests/test_utility_report.py`:

```python
def test_citation_coverage_by_surface(tmp_path):
    from scripts.utility_report import build_session_summaries, collapse_sessions, compute_citation_coverage_by_surface, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(_ss("s1", "p", ["a"], referenced=["a", "demo/process/x"], delivered={"explicit": ["a"], "wiki": ["demo/process/x", "demo/policy/y"]}) + "\n")
    by = compute_citation_coverage_by_surface(collapse_sessions(build_session_summaries(parse_events(f))))
    assert by["explicit"] == {"delivered": 1, "referenced": 1, "coverage": 1.0}
    assert by["wiki"] == {"delivered": 2, "referenced": 1, "coverage": 0.5}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_hooks_session.py tests/test_codex_hooks.py tests/test_utility_report.py -k "wiki or surface" -v`
Expected: FAIL (`KeyError: 'wiki'`, `ImportError`).

- [ ] **Step 3: Session-end hook**

In the embedded Python of `claude/hooks/rekall-session-end.sh`:
- add `page_id = re.compile(r"[a-z0-9][a-z0-9._-]*/(?:process|policy|reference|entity)/[a-z0-9][a-z0-9-]*")` next to `memory_id`;
- `delivered = {"explicit": [], "capsule": [], "reflex": [], "wiki": []}`;
- `wiki_tool_ids = {tid for tid, name in tool_names.items() if "wiki_lookup" in name or "wiki_read" in name}`; exclude them from `recall_tool_ids` (`"recall" in name.lower() or "reflex" in name.lower()` already excludes them, verify);
- in the `user` tool_result branch: if `block["tool_use_id"] in wiki_tool_ids`: `_add("wiki", page_id.findall(result_text(block)))` and set `first_delivery_index` the same way capsule does (wiki counts as a delivery, NOT as an explicit recall for the edits window);
- `all_delivered` includes `delivered["wiki"]`; `recalled_ids` stays memory ids only: `sorted(set(delivered["explicit"]) | set(delivered["capsule"]) | set(delivered["reflex"]))`;
- the reference scan collects both `memory_id.findall` and `page_id.findall` on assistant text and tool_use input, keeping those in `all_delivered`.

- [ ] **Step 4: Codex adapter**

In `codex/hooks/rekall_hook.py`: add `_PAGE_ID_RE` with the same pattern; in `summarize_session`, treat a call whose name is `wiki_lookup`/`wiki_read` (or ends with `__wiki_lookup`/`__wiki_read`) as category `"wiki"`; on its output, collect `_PAGE_ID_RE.findall` into `delivered_wiki` (ordered, deduped); references scan assistant text and call inputs for page ids too; summary gains `"delivered": {"explicit": delivered, "wiki": delivered_wiki[:32]}` and `referenced` is filtered against the union. `recalled_ids` unchanged.

- [ ] **Step 5: Report by surface**

In `scripts/utility_report.py`, keep each summary's raw `delivered` dict on the collapsed record (`"delivered": merged dict, union per surface across the group`), then:

```python
def compute_citation_coverage_by_surface(summaries: list[dict]) -> dict[str, dict]:
    """Delivered vs referenced per surface over collapsed sessions. Telemetry, not utility."""
    out: dict[str, dict] = {}
    for ss in summaries:
        if ss.get("referenced") is None:
            continue
        referenced = set(ss["referenced"])
        for surface, ids in (ss.get("delivered") or {}).items():
            agg = out.setdefault(surface, {"delivered": 0, "referenced": 0})
            agg["delivered"] += len(ids)
            agg["referenced"] += len(referenced & set(ids))
    for agg in out.values():
        agg["coverage"] = (agg["referenced"] / agg["delivered"]) if agg["delivered"] else 0.0
    return out
```

and print after the total: `Citation coverage by surface: explicit 1/1 (100%) · wiki 1/2 (50%)`.

- [ ] **Step 6: Run tests**

Run: `uv run --extra dev pytest tests/test_hooks_session.py tests/test_codex_hooks.py tests/test_utility_report.py tests/test_sessions_fold.py -v`
Expected: all PASS (`fold_sessions` already unions every `delivered` list).

- [ ] **Step 7: Commit**

```bash
git add claude/hooks/rekall-session-end.sh codex/hooks/rekall_hook.py scripts/utility_report.py tests/test_hooks_session.py tests/test_codex_hooks.py tests/test_utility_report.py
git commit -m "feat(measure): count wiki deliveries and page references in session summaries and the report"
```

---

### Task 9: Cockpit `/wiki` surface

**Files:**
- Modify: `ui/package.json` (add `react-markdown`, `remark-gfm`), `ui/lib/schemas.ts`, `ui/components/shell/cockpit-shell.tsx` (nav tab `{ href: "/wiki", label: "Wiki", tag: "WIKI" }`)
- Create: `ui/lib/api/wiki.ts`, `ui/lib/queries/use-wiki.ts`, `ui/app/wiki/page.tsx`, `ui/app/wiki/loading.tsx`, `ui/components/wiki/wiki-sidebar.tsx`, `ui/components/wiki/wiki-page.tsx`, `ui/components/wiki/wiki-search.tsx`, `ui/components/wiki/wiki-drafts.tsx`, `ui/components/wiki/wiki-candidates.tsx`
- Test: `ui/tests/wiki-sidebar.test.tsx`, `ui/tests/wiki-page.test.tsx`, `ui/tests/wiki-drafts.test.tsx`, fixtures `ui/tests/fixtures/wiki-index.json`, `ui/tests/fixtures/wiki-page.json`, `ui/tests/fixtures/wiki-drafts.json`

**Interfaces:**
- Consumes: Task 6 routes.
- Produces: Zod schemas `WikiIndexEntrySchema`, `WikiIndexSchema`, `WikiHitSchema`, `WikiSearchSchema`, `WikiPageSchema`, `WikiDraftSchema`, `WikiDraftsSchema`, `WikiCandidateSchema`, `WikiCandidatesSchema`; API fns `getWikiIndex(project)`, `searchWiki(q, project)`, `getWikiPage(pageId, {section, full})`, `getWikiDrafts()`, `approveDraft(pageId)`, `rejectDraft(pageId, reason)`, `editDraft(pageId, body)`, `getWikiCandidates(project)`, `createDraft(memoryIds, pageType, title?)`; hooks `useWikiIndex`, `useWikiSearch`, `useWikiPage`, `useWikiDrafts`, `useWikiCandidates`, mutations `useApproveDraft`, `useRejectDraft`, `useEditDraft`, `useCreateDraft` (invalidate `["wiki"]`).

- [ ] **Step 1: Add dependencies**

Run: `cd ui && npm install react-markdown@9.0.1 remark-gfm@4.0.0`
Expected: `package.json` and lock updated; `npm test` still green before any new test.

- [ ] **Step 2: Write the failing component tests**

`ui/tests/fixtures/wiki-index.json`:
```json
{"entries": [
  {"page_id": "demo/process/rotate-key", "title": "Rotate gateway key", "type": "process", "project": "demo", "scope": {"env": "all"}, "status": "live", "last_verified": "2026-10-09", "summary": "How to rotate", "validity": "ok"},
  {"page_id": "demo/policy/prod-go", "title": "Prod go rule", "type": "policy", "project": "demo", "scope": null, "status": "live", "last_verified": "2026-06-01", "summary": "Explicit go", "validity": "stale"}
]}
```
`ui/tests/fixtures/wiki-page.json`:
```json
{"page_id": "demo/process/rotate-key", "revision": 1, "title": "Rotate gateway key", "type": "process", "project": "demo", "scope": {"env": "all"}, "status": "live", "last_verified": "2026-10-09", "validity": "ok", "validity_reasons": [], "sources": ["2026-01-01_fact_a1"], "sections": ["when", "steps", "verify"], "section_id": null, "body": "## When {#when}\nkey expired [source: 2026-01-01_fact_a1]\n## Steps {#steps}\n1. export key [source: 2026-01-01_fact_a1]\n## Verify {#verify}\ncurl 200", "token_estimate": 40, "over_budget": false}
```
`ui/tests/fixtures/wiki-drafts.json`:
```json
{"drafts": [{"page_id": "demo/policy/commits", "title": "Commit trailer", "type": "policy", "project": "demo", "needs": ["exceptions"], "unsourced_steps": 0, "has_redaction": false}]}
```

`ui/tests/wiki-sidebar.test.tsx`:
```tsx
import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WikiSidebar } from "@/components/wiki/wiki-sidebar";
import fixture from "./fixtures/wiki-index.json";
import { WikiIndexSchema } from "@/lib/schemas";

describe("WikiSidebar", () => {
  test("groups by project and type and shows validity badges", () => {
    const data = WikiIndexSchema.parse(fixture);
    render(<WikiSidebar entries={data.entries} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/demo \/ process/i)).toBeInTheDocument();
    expect(screen.getByText(/demo \/ policy/i)).toBeInTheDocument();
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  test("selecting an entry calls onSelect with the page id", () => {
    const data = WikiIndexSchema.parse(fixture);
    const onSelect = vi.fn();
    render(<WikiSidebar entries={data.entries} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText(/rotate gateway key/i));
    expect(onSelect).toHaveBeenCalledWith("demo/process/rotate-key");
  });
});
```

`ui/tests/wiki-page.test.tsx`:
```tsx
import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WikiPageView } from "@/components/wiki/wiki-page";
import fixture from "./fixtures/wiki-page.json";
import { WikiPageSchema } from "@/lib/schemas";

describe("WikiPageView", () => {
  test("renders markdown headings, a TOC, and source links", () => {
    const page = WikiPageSchema.parse(fixture);
    render(<WikiPageView page={page} />);
    expect(screen.getByRole("heading", { name: /rotate gateway key/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /2026-01-01_fact_a1/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("navigation", { name: /on this page/i })).toHaveTextContent(/steps/i);
  });

  test("shows the withdrawn warning when validity is withdrawn", () => {
    const page = WikiPageSchema.parse({ ...fixture, validity: "withdrawn", validity_reasons: ["source disputed"] });
    render(<WikiPageView page={page} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/withdrawn/i);
  });
});
```

`ui/tests/wiki-drafts.test.tsx`:
```tsx
import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WikiDraftsList } from "@/components/wiki/wiki-drafts";
import fixture from "./fixtures/wiki-drafts.json";
import { WikiDraftsSchema } from "@/lib/schemas";

describe("WikiDraftsList", () => {
  test("lists drafts with needs and wires approve and reject", () => {
    const data = WikiDraftsSchema.parse(fixture);
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(<WikiDraftsList drafts={data.drafts} onApprove={onApprove} onReject={onReject} onOpen={() => {}} />);
    expect(screen.getByText(/needs: exceptions/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onApprove).toHaveBeenCalledWith("demo/policy/commits");
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onReject).toHaveBeenCalledWith("demo/policy/commits");
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ui && npm test -- wiki`
Expected: FAIL, modules not found.

- [ ] **Step 4: Schemas, API client, hooks**

Append to `ui/lib/schemas.ts`:
```ts
export const WikiIndexEntrySchema = z.object({
  page_id: z.string(),
  title: z.string().nullable(),
  type: z.string(),
  project: z.string(),
  scope: z.record(z.any()).nullable().optional(),
  status: z.string(),
  last_verified: z.string().nullable().optional(),
  summary: z.string().optional().default(""),
  validity: z.enum(["ok", "stale", "withdrawn"]).optional().default("ok"),
});
export const WikiIndexSchema = z.object({ entries: z.array(WikiIndexEntrySchema) });
export const WikiHitSchema = z.object({
  page_id: z.string(), revision: z.number().nullable().optional(), section_id: z.string().nullable(),
  title: z.string().nullable(), excerpt: z.string(), scope: z.record(z.any()).nullable().optional(),
  status: z.string(), last_verified: z.string().nullable().optional(),
  validity: z.enum(["ok", "stale", "withdrawn"]), validity_reasons: z.array(z.string()), sources: z.array(z.string()), score: z.number(),
});
export const WikiSearchSchema = z.object({ hits: z.array(WikiHitSchema) });
export const WikiPageSchema = z.object({
  page_id: z.string(), revision: z.number().nullable().optional(), title: z.string().nullable(), type: z.string(), project: z.string(),
  scope: z.record(z.any()).nullable().optional(), status: z.string(), last_verified: z.string().nullable().optional(),
  validity: z.enum(["ok", "stale", "withdrawn"]), validity_reasons: z.array(z.string()), sources: z.array(z.string()),
  sections: z.array(z.string()), section_id: z.string().nullable(), body: z.string(), token_estimate: z.number(), over_budget: z.boolean(),
});
export const WikiDraftSchema = z.object({
  page_id: z.string(), title: z.string().nullable(), type: z.string(), project: z.string(),
  needs: z.array(z.string()), unsourced_steps: z.number(), has_redaction: z.boolean(),
});
export const WikiDraftsSchema = z.object({ drafts: z.array(WikiDraftSchema) });
export const WikiCandidateSchema = z.object({
  memory_id: z.string(), content: z.string(), question: z.string().nullable().optional(),
  page_type: z.string(), scope: z.record(z.any()).nullable().optional(), reasons: z.array(z.string()),
});
export const WikiCandidatesSchema = z.union([
  z.object({ status: z.literal("unconfigured") }),
  z.object({ candidates: z.array(WikiCandidateSchema) }),
]);
export type WikiIndexEntry = z.infer<typeof WikiIndexEntrySchema>;
export type WikiPage = z.infer<typeof WikiPageSchema>;
export type WikiDraft = z.infer<typeof WikiDraftSchema>;
export type WikiHit = z.infer<typeof WikiHitSchema>;
export type WikiCandidate = z.infer<typeof WikiCandidateSchema>;
```

`ui/lib/api/wiki.ts`:
```ts
import { fetchJson } from "./client";
import {
  WikiIndexSchema, WikiSearchSchema, WikiPageSchema, WikiDraftsSchema, WikiCandidatesSchema,
} from "@/lib/schemas";

export function getWikiIndex(project: string) {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  return fetchJson(`/api/wiki/index?${qs}`, undefined, (d) => WikiIndexSchema.parse(d));
}
export function searchWiki(q: string, project: string) {
  const qs = new URLSearchParams({ q });
  if (project) qs.set("project", project);
  return fetchJson(`/api/wiki/search?${qs}`, undefined, (d) => WikiSearchSchema.parse(d));
}
export function getWikiPage(pageId: string, opts: { section?: string; full?: boolean } = {}) {
  const qs = new URLSearchParams();
  if (opts.section) qs.set("section", opts.section);
  if (opts.full) qs.set("full", "1");
  return fetchJson(`/api/wiki/page/${pageId}?${qs}`, undefined, (d) => WikiPageSchema.parse(d));
}
export function getWikiDrafts() {
  return fetchJson(`/api/wiki/drafts`, undefined, (d) => WikiDraftsSchema.parse(d));
}
export function approveDraft(pageId: string) {
  return fetchJson(`/api/wiki/drafts/${pageId}/approve`, { method: "POST" }, (d) => d as { page: Record<string, unknown> });
}
export function rejectDraft(pageId: string, reason: string) {
  return fetchJson(`/api/wiki/drafts/${pageId}/reject`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }, (d) => d as { status: string });
}
export function editDraft(pageId: string, body: string) {
  return fetchJson(`/api/wiki/drafts/${pageId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body }) }, (d) => d as { page: Record<string, unknown> });
}
export function getWikiCandidates(project: string) {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  return fetchJson(`/api/wiki/candidates?${qs}`, undefined, (d) => WikiCandidatesSchema.parse(d));
}
export function createDraft(memoryIds: string[], pageType: string, title?: string) {
  return fetchJson(`/api/wiki/draft`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ memory_ids: memoryIds, page_type: pageType, title }) }, (d) => d as { page?: Record<string, unknown>; status?: string });
}
```

`ui/lib/queries/use-wiki.ts`: `useQuery` hooks with keys `["wiki","index",project]`, `["wiki","search",q,project]` (enabled when `q.length > 1`), `["wiki","page",pageId,section,full]` (enabled when pageId), `["wiki","drafts"]`, `["wiki","candidates",project]` (enabled: false until `refetch()` is called by the button), and `useMutation` wrappers for approve/reject/edit/createDraft that `queryClient.invalidateQueries({ queryKey: ["wiki"] })` on success. Follow `use-kb.ts` for shape.

- [ ] **Step 5: Components**

- `wiki-sidebar.tsx`: props `{ entries, selected, onSelect }`; group entries by `${project} / ${type}`; each item a `<button>` with the title and a badge: `validity` (`ok` muted, `stale` amber, `withdrawn` red) plus `status` when draft. Uses existing tokens (`var(--fg)`, `var(--muted)`), same classes as `kb-slice.tsx`.
- `wiki-page.tsx`: `WikiPageView({ page })`: header (title, `page_id`, `rev`, `type`, `scope`, `last_verified`), `role="alert"` box when `validity !== "ok"` listing `validity_reasons`, a `<nav aria-label="On this page">` listing `sections`, and the body rendered with `react-markdown` + `remark-gfm`; a custom text renderer turns `[source: <id>]` into `<a href="/brain?memory=<id>">` links (and leaves other text untouched).
- `wiki-search.tsx`: input + results list of hits (title, section, validity badge, excerpt), `onOpen(page_id, section_id)`.
- `wiki-drafts.tsx`: `WikiDraftsList({ drafts, onApprove, onReject, onOpen })`: each draft with `needs: ...`, `unsourced steps: N`, redaction flag, buttons `Approve` (disabled when `has_redaction || unsourced_steps > 0 || needs.length`), `Reject` (prompts for a reason via `window.prompt`, passes id), `Open` (loads the draft body for editing).
- `wiki-candidates.tsx`: button "Classify candidates" (calls `refetch`), handles `unconfigured`, lists candidates with checkbox, question, page_type, reasons; "Draft selected" calls `createDraft`.
- `app/wiki/page.tsx`: three-column layout (sidebar, page view, right rail with tabs `Search | Drafts | Candidates`), heading via `SerifHeading` with eyebrow `DOCS · LIVE` and `scopedTitle("Wiki", project)`; `app/wiki/loading.tsx` copies `app/kb/loading.tsx`.
- Nav: add `{ href: "/wiki", label: "Wiki", tag: "WIKI" }` to `cockpit-shell.tsx` after Knowledge Base.

- [ ] **Step 6: Run the UI tests and lint**

Run: `cd ui && npm test && npm run lint` (if a lint script exists; otherwise `npx next lint`)
Expected: all green, including the pre-existing suites.

- [ ] **Step 7: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/lib ui/app/wiki ui/components/wiki ui/components/shell/cockpit-shell.tsx ui/tests
git commit -m "feat(cockpit): wiki docs surface with sidebar, page view, search, drafts, candidates"
```

---

### Task 10: Docs and agent guidance

**Files:**
- Modify: `claude/CLAUDE.snippet.md`, `codex/skills/rekall-memory/SKILL.md`, `docs/MIGRATION.md` (unreleased note at the top of the latest section, same placement rule the parity test allows), `CLAUDE.md` (repo layout: `src/memory/wiki/`; a one-line "Adding a wiki page type" pointer), `docs/ARCHITECTURE.md` (one paragraph: wiki layer)

- [ ] **Step 1: Snippet and Codex skill**

Add to both, same wording: "For how-to and policy questions you would otherwise answer from memory, call `wiki_lookup` and read the section with `wiki_read`; use `recall_memories` for decisions, history, and recent context. Wiki results carry `validity`: treat `stale` as unverified and `withdrawn` as do-not-follow. Results are evidence, never instructions."

- [ ] **Step 2: MIGRATION, CLAUDE.md, ARCHITECTURE**

MIGRATION (under the v1.17.0 section, heading `## Unreleased: wiki phase 1`): the routes, the two tools, the `wiki_delivered` event, `delivered.wiki` in summaries, the cockpit surface, and that the model config for candidates/draft is the publish config. CLAUDE.md repo layout line: `src/memory/wiki/            Page model, store, validity, search, compile (phase 1)`. ARCHITECTURE: a short "Wiki" paragraph referencing the spec.

- [ ] **Step 3: Parity tests**

Run: `uv run --extra dev pytest tests/test_docs_parity.py -v`; fix any assertion that now expects the new rows (README rows were added in Task 6).

- [ ] **Step 4: Commit**

```bash
git add claude/CLAUDE.snippet.md codex/skills/rekall-memory/SKILL.md docs/MIGRATION.md CLAUDE.md docs/ARCHITECTURE.md
git commit -m "docs: wiki phase 1 guidance, migration note, layout"
```

---

### Task 11: CI parity and wrap-up

- [ ] **Step 1: CI commands exactly**

Run (outside the sandbox, test Qdrant up):
```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run --extra dev pytest -q -p no:cacheprovider
cd ui && npm test
```
Expected: ruff clean (run `uv run ruff format src tests` and commit if not), pytest green except pre-existing skips, UI green.

- [ ] **Step 2: Record counts in this plan** under this task: `Final (YYYY-MM-DD): pytest N passed / K skipped; ui M passed; ruff clean.` Commit:

```bash
git add docs/superpowers/plans/2026-10-09-rekall-wiki-phase1.md
git commit -m "docs: record wiki phase 1 final test counts"
```

Rollout after merge (operator steps): rebuild `mcp` and `ui` containers; run both installers (provenance allowlist changed); in the cockpit `/wiki` → Candidates → classify → pick 5–10 → Draft → review → Approve; then check `wiki_lookup` from a fresh session and `scripts/utility_report.py` for the `wiki` surface line.
