"""Validity computed from the graph at read time (spec: Read path)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from memory.wiki.pages import Page

SRC = "2026-09-19_requirement_9b9a3e83"


def _page(page_type="policy", sources=(SRC,)):
    return Page(
        frontmatter={
            "page_id": f"p/{page_type}/x",
            "type": page_type,
            "title": "x",
            "sources": list(sources),
        },
        body="",
    )


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
    assert (
        compute_validity(_page(sources=(SRC, edge.source)), store=store2, graph=graph2)["validity"]
        == "ok"
    )


def test_missing_source_is_stale_not_crash():
    from memory.wiki.validity import compute_validity

    store, graph = _env([], {})
    out = compute_validity(_page(), store=store, graph=graph)
    assert out["validity"] == "stale" and "not found" in out["reasons"][0]


def test_stale_process_is_withdrawn():
    from memory.wiki.validity import compute_validity

    store, graph = _env([{"memory_id": SRC, "disputed": True}], {})
    assert compute_validity(_page("process"), store=store, graph=graph)["validity"] == "withdrawn"
