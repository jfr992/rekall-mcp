"""Compile step: worthiness classification and page drafting. The only module that calls a model."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable

from memory.publish import _llm_complete, llm_config
from memory.wiki.pages import Page, has_redaction, missing_sections, slugify

logger = logging.getLogger(__name__)

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


def page_id_for(project: str, page_type: str, title: str) -> str:
    return f"{slugify(project)}/{page_type}/{slugify(title)}"


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


def _classify(content: str, llm: Callable[[str], str], sha: str) -> dict:
    data = _parse_json(llm(RUBRIC_PROMPT.format(content=content[:4000])))
    if (
        data is None
        or data.get("verdict") not in ("worthy", "skip")
        or data.get("page_type") not in (*_SECTION_TEMPLATES, None)
    ):
        return {"verdict": "skip", "reasons": ["unparseable classifier output"], "content_sha": sha}
    reasons = data.get("reasons")
    question = data.get("question")
    return {
        **data,
        "question": question if isinstance(question, str) else None,
        "scope": data["scope"] if isinstance(data.get("scope"), dict) else {},
        "reasons": reasons
        if isinstance(reasons, list) and all(isinstance(r, str) for r in reasons)
        else [],
        "content_sha": sha,
    }


class ModelUnreachable(RuntimeError):
    pass


def _gate(m: dict, sha: str) -> dict | None:
    if m.get("disputed"):
        return {"verdict": "skip", "reasons": ["disputed"], "content_sha": sha}
    if has_redaction(str(m.get("content") or "")):
        return {"verdict": "skip", "reasons": ["redacted content"], "content_sha": sha}
    return None


def _sha(content: str) -> str:
    return hashlib.sha1(content[:4000].encode()).hexdigest()


def _candidate(m: dict, mid: str, content: str, entry: dict, used_in: list[str]) -> dict:
    return {
        "memory_id": mid,
        "content": content,
        "question": entry.get("question"),
        "page_type": entry.get("page_type") or "reference",
        "scope": entry.get("scope") or {},
        "reasons": entry.get("reasons") or [],
        "project": m.get("project") or "",
        "date": str(m.get("date") or ""),
        "used_in": used_in,
    }


def worthy_from_cache(
    memories: list[dict], cache: dict, used_in: dict[str, list[str]] | None = None
) -> list[dict]:
    used_in = used_in or {}
    worthy = []
    for m in memories:
        mid = m.get("memory_id")
        content = str(m.get("content") or "")
        if not mid:
            continue
        entry = cache.get(mid, {})
        if (
            entry.get("verdict") == "worthy"
            and entry.get("content_sha") == _sha(content)
            and _gate(m, "") is None
        ):
            worthy.append(_candidate(m, mid, content, entry, used_in.get(mid, [])))
    worthy.sort(key=lambda c: c["date"], reverse=True)
    return worthy


def classify_candidates(
    memories: list[dict],
    *,
    llm: Callable[[str], str],
    cache: dict,
    max_consecutive_failures: int = 3,
    progress: Callable[[int, int], None] | None = None,
    flush: Callable[[], None] | None = None,
    flush_every: int = 10,
) -> list[dict]:
    failures = 0
    total = len(memories)
    for done, m in enumerate(memories, 1):
        mid = m.get("memory_id")
        content = str(m.get("content") or "")
        sha = _sha(content)
        if mid:
            gated = _gate(m, sha)
            if gated:
                cache[mid] = gated
            elif cache.get(mid, {}).get("content_sha") != sha:
                try:
                    cache[mid] = _classify(content, llm, sha)
                    failures = 0
                except Exception as e:
                    logger.warning("wiki classify failed for %s, skipping: %s", mid, e)
                    failures += 1
                    if failures >= max_consecutive_failures:
                        raise ModelUnreachable(
                            f"model unreachable: {failures} consecutive failures ({e})"
                        ) from e
        if progress:
            progress(done, total)
        if flush and done % flush_every == 0:
            flush()
    return worthy_from_cache(memories, cache)


def draft_page(
    memories: list[dict],
    *,
    page_type: str,
    project: str,
    title: str | None,
    llm: Callable[[str], str],
    scopes: list[dict] | None = None,
) -> Page:
    if page_type not in _SECTION_TEMPLATES:
        raise ValueError("invalid page_type")
    notes = "\n".join(
        f"- [{m['memory_id']}] {str(m.get('content') or '').strip()}" for m in memories
    )
    # str.replace, not format: templates carry literal {#id} braces; {memories} goes last so memory text is never re-substituted
    text = llm(
        DRAFT_PROMPTS[page_type].replace("{page_type}", page_type).replace("{memories}", notes)
    )
    found = _TITLE_RE.search(text)
    final_title = title or (found.group(1).strip() if found else f"{page_type} page")
    body = _TITLE_RE.sub("", text, count=1).strip()
    scope = scopes[0] if scopes and all(s == scopes[0] for s in scopes) else {"env": "unknown"}
    fm = {
        "title": final_title,
        "description": final_title,
        "sidebar_position": _SIDEBAR[page_type],
        "tags": [page_type],
        "page_id": page_id_for(project, page_type, final_title),
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
