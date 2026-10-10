"""File-backed wiki store: drafts, live pages, history, index, log."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

from memory.wiki.pages import (
    PAGE_ID_RE,
    Page,
    cited_ids,
    emit_page,
    has_redaction,
    parse_page,
    unsourced_steps,
)

logger = logging.getLogger(__name__)

SCHEMA_TEXT = """# Rekall wiki schema

Pages are Docusaurus-compatible markdown with Rekall frontmatter.
Types: process, policy, reference, entity. Every H2 carries a stable `{#id}`.
Live pages change only through approve. `[REDACTED]` never ships. Process
steps end with `[source: <memory_id>]`.
"""


def _oneline(text: object) -> str:
    return " ".join(str(text).split())


_UNSANITIZED_FM = frozenset({"page_id", "type", "status", "project"})


def _sanitized(page: Page) -> Page:
    from memory.manager import Sanitizer

    fm = {
        k: Sanitizer.sanitize(v) if isinstance(v, str) and k not in _UNSANITIZED_FM else v
        for k, v in page.frontmatter.items()
    }
    return Page(frontmatter=fm, body=Sanitizer.sanitize(page.body))


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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

    def _write_draft_locked(self, page: Page) -> Path:
        clean = _sanitized(page)
        fm = dict(clean.frontmatter, status="draft")
        if not fm.get("page_id"):
            raise ValueError("page has no page_id")
        path = self.path_for(fm["page_id"], "draft")
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, emit_page(Page(frontmatter=fm, body=clean.body)))
        return path

    def write_draft(self, page: Page) -> Path:
        with self._lock:
            return self._write_draft_locked(page)

    def update_draft(self, page_id: str, mutate: Callable[[Page], Page]) -> Page:
        with self._lock:
            page = mutate(self._locked_draft(page_id))
            self._write_draft_locked(page)
            return page

    def list_pages(self, status: str = "live") -> list[Page]:
        base = self.root / ("live" if status == "live" else "drafts")
        pages = []
        for path in sorted(base.rglob("*.md")):
            try:
                pages.append(parse_page(path.read_text(encoding="utf-8")))
            except ValueError:
                continue  # a broken file never hides the rest of the wiki
        return pages

    def _locked_draft(self, page_id: str) -> Page:
        draft = self.read(page_id, "draft")
        if draft is None:
            raise ValueError("no draft for page_id")
        if draft.frontmatter.get("page_id") != page_id:
            raise ValueError("draft page_id mismatch")
        return draft

    def approve(
        self,
        page_id: str,
        *,
        verified_by: str = "human",
        exists: Callable[[list[str]], set[str]] | None = None,
    ) -> Page:
        with self._lock:
            draft = self._locked_draft(page_id)
            if has_redaction(draft.body) or has_redaction(json.dumps(draft.frontmatter)):
                raise ValueError("page contains redacted text")
            if unsourced_steps(draft):
                raise ValueError("process page has steps without a source")
            uncited = [i for i in cited_ids(draft.body) if i not in draft.sources]
            if uncited:
                raise ValueError(f"cited ids missing from sources: {', '.join(uncited)}")
            if exists is not None and draft.sources:
                found = exists(draft.sources)
                missing = [i for i in draft.sources if i not in found]
                if missing:
                    raise ValueError(f"sources not found in memory: {', '.join(missing)}")
            live_path = self.path_for(page_id, "live")
            existing = self.read(page_id, "live")
            revision = 1
            if existing is not None:
                revision = int(existing.frontmatter.get("revision") or 0) + 1
                hist = self.root / "_history" / page_id
                hist.mkdir(parents=True, exist_ok=True)
                _write_atomic(
                    hist / f"{existing.frontmatter.get('revision', 0)}.md", emit_page(existing)
                )
            today = date.today().isoformat()
            fm = dict(
                draft.frontmatter,
                status="live",
                revision=revision,
                updated=today,
                last_verified=today,
            )
            fm.setdefault("human_edited", False)
            live = Page(frontmatter=fm, body=draft.body)
            live_path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(live_path, emit_page(live))
            self.path_for(page_id, "draft").unlink(missing_ok=True)
            self._rebuild_index_locked()
            self._append_log_locked("approve", str(fm.get("title") or page_id))
        return live

    def reject(self, page_id: str, reason: str) -> None:
        with self._lock:
            draft = self._locked_draft(page_id)
            self.path_for(page_id, "draft").unlink(missing_ok=True)
            self._append_log_locked(
                "reject", f"{draft.frontmatter.get('title') or page_id} — {reason}"
            )

    def _cache_path(self, name: str) -> Path:
        if not name.isidentifier():
            raise ValueError("invalid cache name")
        return self.root / "_cache" / f"{name}.json"

    def read_cache(self, name: str) -> dict:
        path = self._cache_path(name)
        with self._lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}
            except (OSError, ValueError) as e:
                logger.warning("wiki cache %s unreadable, ignoring: %s", name, e)
                return {}
        return data if isinstance(data, dict) else {}

    def write_cache(self, name: str, data: dict) -> None:
        path = self._cache_path(name)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, json.dumps(data))

    def merge_cache(self, name: str, entries: dict) -> None:
        path = self._cache_path(name)
        with self._lock:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            merged = {**(current if isinstance(current, dict) else {}), **entries}
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, json.dumps(merged))

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
                "title": _oneline(page.frontmatter.get("title") or page.page_id),
                "type": page.type,
                "project": page.project,
                "scope": page.frontmatter.get("scope"),
                "status": page.status,
                "last_verified": page.frontmatter.get("last_verified"),
                "summary": _oneline(page.frontmatter.get("description") or ""),
            }
            blob = json.dumps(meta).replace("-->", "--\\u003e")  # keep the HTML comment open
            lines.append(
                f"- [{meta['title']}](live/{page.page_id}.md) — {meta['summary']} <!-- {blob} -->"
            )
        _write_atomic(self.root / "index.md", "\n".join(lines).rstrip() + "\n")

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
        log = self.root / "log.md"
        entry = f"## [{date.today().isoformat()}] {_oneline(kind)} | {_oneline(title)}\n"
        _write_atomic(log, log.read_text(encoding="utf-8") + entry)
