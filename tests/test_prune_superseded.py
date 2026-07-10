"""Gate evaluation for the superseded-prune endpoint (spec 2026-07-06 Part 2).

Every gate has a refusal test. The 99-memory incident needed: unbounded deletion,
no backup, same-day edges, silence. Gates 1-4 live here (pure); 5-7 in the endpoint.
"""

from datetime import date

from memory.prune_superseded import build_candidates

TODAY = date(2026, 7, 6)


def _edge(src, tgt, created="2026-06-01", relation="supersedes"):
    return (src, tgt, {"relation": relation, "created": created})


def _mem(d, tier="episodic", reinforcement=0, compacted=False):
    return {"date": d, "tier": tier, "reinforcement_count": reinforcement, "compacted": compacted}


def _lookup(table):
    return lambda mid: table.get(mid)


def test_gate1_only_supersedes_edges():
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01")}
    cands = build_candidates([_edge("new", "old", relation="contradicts")], _lookup(table), TODAY)
    assert cands == []


def test_gate15_reinforced_or_compacted_refused():
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01", reinforcement=2)}
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []
    table["old"] = _mem("2026-01-01", compacted=True)
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []


def test_gate2_missing_superseder_refused():
    table = {"old": _mem("2026-01-01")}  # "new" not in store
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []


def test_gate3_young_memory_refused():
    table = {"new": _mem("2026-06-20"), "old": _mem("2026-05-01")}  # old is 66 days
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []


def test_gate35_fresh_edge_refused():
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01")}
    cands = build_candidates([_edge("new", "old", created="2026-07-03")], _lookup(table), TODAY)
    assert cands == []  # edge 3 days old < 7


def test_gate35_missing_edge_created_refused():
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01")}
    assert (
        build_candidates([("new", "old", {"relation": "supersedes"})], _lookup(table), TODAY) == []
    )


def test_gate36_pair_gap_under_30d_refused():
    table = {"new": _mem("2026-01-20"), "old": _mem("2026-01-01")}  # 19-day gap
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []


def test_gate4_identity_refused():
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01", tier="identity")}
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []


def test_happy_path_yields_candidate():
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01")}
    cands = build_candidates([_edge("new", "old")], _lookup(table), TODAY)
    assert [(c.memory_id, c.superseded_by) for c in cands] == [("old", "new")]


def test_malformed_superseder_date_refused():
    table = {"new": _mem("not-a-date"), "old": _mem("2026-01-01")}
    assert build_candidates([_edge("new", "old")], _lookup(table), TODAY) == []


def test_gate_llm_refined_supersedes_refused():
    """Edge with relation=supersedes AND llm_refined=True must never be a deletion signal."""
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01")}
    edge = ("new", "old", {"relation": "supersedes", "created": "2026-06-01", "llm_refined": True})
    cands = build_candidates([edge], _lookup(table), TODAY)
    assert cands == []


def test_chain_leaf_first_ordering():
    # A supersedes B, B supersedes C — C must sort before B, so deleting B never orphans C.
    table = {"A": _mem("2026-06-01"), "B": _mem("2026-02-01"), "C": _mem("2025-12-01")}
    cands = build_candidates(
        [_edge("A", "B"), _edge("B", "C", created="2026-05-01")], _lookup(table), TODAY
    )
    assert [c.memory_id for c in cands] == ["C", "B"]


def test_gate_provisional_band_supersedes_refused():
    """Supersedes from the widened [0.85, 0.90) similarity range carries
    band='provisional' — recall-ranking signal only, never deletion evidence."""
    table = {"new": _mem("2026-06-01"), "old": _mem("2026-01-01")}
    edge = (
        "new",
        "old",
        {"relation": "supersedes", "created": "2026-06-01", "band": "provisional"},
    )
    assert build_candidates([edge], _lookup(table), TODAY) == []
