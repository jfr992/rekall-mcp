"""Deterministic context partition (spec 2026-07-08): post-score reorder with a
survivor floor — never a ranking-weight change, never drops below floor."""

from memory.context_match import partition_by_context


def _mems(n):
    return [
        {"memory_id": f"m{i}", "content": f"content {i}", "score": 1.0 - i * 0.01} for i in range(n)
    ]


def test_no_hint_is_identity():
    results = _mems(10)
    out = partition_by_context(results, None, 5)
    assert [m["memory_id"] for m in out] == [f"m{i}" for i in range(5)]
    assert all("_context_matched" not in m for m in out)


def test_single_token_hint_ignored():
    results = _mems(10)
    out = partition_by_context(results, "auth", 5)
    assert [m["memory_id"] for m in out] == [f"m{i}" for i in range(5)]


def test_stopword_only_hint_ignored():
    out = partition_by_context(_mems(6), "the of", 5)
    assert [m["memory_id"] for m in out] == [f"m{i}" for i in range(5)]


def test_lowercase_content_matching_promotes_from_below():
    results = _mems(10)
    results[7]["content"] = "decided auth middleware uses JWT rotation"
    out = partition_by_context(results, "auth middleware", 5)
    ids = [m["memory_id"] for m in out]
    assert "m7" in ids
    idx = ids.index("m7")
    assert out[idx].get("_context_matched") is True


def test_survivor_floor_holds_under_full_context_pressure():
    # red-team eviction case: ranks 5-9 all match; floor = ceil(5/2)=3 baseline survive
    results = _mems(10)
    for i in range(5, 10):
        results[i]["content"] = f"auth middleware note {i}"
    out = partition_by_context(results, "auth middleware", 5)
    ids = [m["memory_id"] for m in out]
    assert ids[:3] == ["m0", "m1", "m2"]
    assert set(ids[3:]) == {"m5", "m6"}


def test_entities_bonus_matching():
    results = _mems(6)
    results[4]["entities"] = ["JWTRotator", "auth_middleware"]
    results[4]["content"] = "irrelevant words only"
    out = partition_by_context(results, "auth_middleware refactor", 3)
    assert any(m["memory_id"] == "m4" and m.get("_context_matched") for m in out)


def test_stable_order_within_partitions():
    results = _mems(10)
    for i in (6, 8):
        results[i]["content"] = "billing service migration step"
    out = partition_by_context(results, "billing service", 6)
    ids = [m["memory_id"] for m in out]
    assert ids.index("m6") < ids.index("m8")
