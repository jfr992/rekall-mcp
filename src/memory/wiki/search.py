"""Small in-memory BM25 over live wiki sections. No model, no Qdrant."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable

from memory.wiki.pages import Page, split_sections, token_estimate
from memory.wiki.store import WikiStore

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{1,}")
_STOP = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "or",
    "is",
    "in",
    "on",
    "for",
    "with",
    "how",
    "do",
    "we",
    "i",
}
_K1, _B = 1.5, 0.75


def _tokens(text: str) -> list[str]:
    stripped = (t.strip("._-") for t in _TOKEN_RE.findall(text.lower()))
    return [t for t in stripped if len(t) >= 2 and t not in _STOP]


def _documents(store: WikiStore, project: str | None) -> list[dict]:
    docs = []
    for page in store.list_pages("live"):
        if project and page.project != project:
            continue
        title = str(page.frontmatter.get("title") or "")
        for section_id, heading, text in split_sections(page.body):
            docs.append(
                {
                    "page": page,
                    "section_id": section_id,
                    "text": text,
                    "tokens": _tokens(f"{title} {heading} {text}"),
                }
            )
    return docs


def _bm25(query: list[str], docs: list[dict]) -> list[float]:
    n = len(docs)
    avg = (sum(len(d["tokens"]) for d in docs) / n) if n else 0.0
    df: Counter[str] = Counter()
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
            s += (
                idf
                * (tf[q] * (_K1 + 1))
                / (tf[q] + _K1 * (1 - _B + _B * len(d["tokens"]) / (avg or 1)))
            )
        scores.append(s)
    return scores


def search_index(
    store: WikiStore,
    query: str,
    *,
    project: str | None = None,
    limit: int = 3,
    budget_tokens: int = 600,
    validity_fn: Callable[[Page], dict] | None = None,
) -> list[dict]:
    q = _tokens(query)
    if not q:
        return []
    docs = _documents(store, project)
    scores = _bm25(q, docs)
    best: dict[str, tuple[float, dict]] = {}
    for d, s in zip(docs, scores, strict=True):
        pid = d["page"].page_id
        if s > 0 and (pid not in best or s > best[pid][0]):
            best[pid] = (s, d)
    hits: list[dict] = []
    used = 0
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
        hits.append(
            {
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
            }
        )
        if len(hits) >= limit:
            break
    return hits
