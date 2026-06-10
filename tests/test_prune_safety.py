"""Fix C1 — prune must be plan-id gated, identity-exempt, unknown-salience-exempt."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from memory.prune import (
    _PLAN_STORE,
    MAX_DELETIONS_PER_APPLY,
    PLAN_TTL,
    PlanExpired,
    PlanIdMismatch,
    PlanNotFound,
    apply_plan,
    build_plan,
)


@pytest.fixture(autouse=True)
def clear_plan_store():
    _PLAN_STORE.clear()
    yield
    _PLAN_STORE.clear()


def _fake_manager(memories: list[dict], graph_contradicts: dict | None = None):
    mgr = MagicMock()
    mgr.store.scroll.return_value = memories
    mgr.knowledge_graph.count_contradicts.side_effect = lambda mid: (graph_contradicts or {}).get(mid, 0)
    mgr.knowledge_graph.get_neighbors.side_effect = lambda mid, hops=1: set()
    mgr.delete.return_value = True
    return mgr


def _old_date() -> str:
    return (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")


def test_identity_tier_never_in_plan():
    mgr = _fake_manager([
        {"memory_id": "id1", "tier": "identity", "salience": 0.1, "type": "preference",
         "date": _old_date(), "reinforcement_count": 0},
        {"memory_id": "w1", "tier": "working", "salience": 0.1, "type": "note",
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "id1" not in ids
    assert "w1" in ids


def test_unknown_salience_never_in_plan():
    """THE bug that would wipe JR's notes. Missing salience must be excluded."""
    mgr = _fake_manager([
        {"memory_id": "unknown", "tier": "working", "type": "note",
         "date": _old_date(), "reinforcement_count": 0},  # no salience key
        {"memory_id": "explicit", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "unknown" not in ids
    assert "explicit" in ids


def test_reinforced_memories_not_in_plan():
    mgr = _fake_manager([
        {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 3},  # reinforced
        {"memory_id": "w2", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "w1" not in ids
    assert "w2" in ids


def test_young_memories_not_in_plan():
    mgr = _fake_manager([
        {"memory_id": "young", "tier": "working", "type": "note", "salience": 0.1,
         "date": datetime.now().strftime("%Y-%m-%d"), "reinforcement_count": 0},
        {"memory_id": "old", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "young" not in ids
    assert "old" in ids


def test_apply_without_plan_id_rejects():
    mgr = _fake_manager([
        {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")

    with pytest.raises(PlanIdMismatch):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id="wrong")


def test_apply_with_unknown_plan_rejects():
    mgr = _fake_manager([])
    with pytest.raises(PlanNotFound):
        apply_plan(mgr, plan_id="nonexistent", confirm_plan_id="nonexistent")


def test_apply_with_expired_plan_rejects(monkeypatch):
    mgr = _fake_manager([
        {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")

    import memory.prune as prune_mod
    real_dt = prune_mod.datetime

    class FakeDT(real_dt):
        @classmethod
        def now(cls):
            return plan.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(prune_mod, "datetime", FakeDT)

    with pytest.raises(PlanExpired):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id=plan.plan_id)


def test_apply_hard_cap():
    candidates = [
        {"memory_id": f"w{i}", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0}
        for i in range(MAX_DELETIONS_PER_APPLY + 50)
    ]
    mgr = _fake_manager(candidates)
    plan = build_plan(mgr, project="test", limit=MAX_DELETIONS_PER_APPLY + 50)

    result = apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id=plan.plan_id)

    assert len(result["deleted"]) == MAX_DELETIONS_PER_APPLY
    assert len(result["skipped"]) == 50


def test_neighborhood_protection():
    """A low-salience memory adjacent to identity-tier is NOT prunable."""
    mgr = _fake_manager(
        [
            {"memory_id": "id1", "tier": "identity", "salience": 0.9, "type": "preference",
             "date": _old_date(), "reinforcement_count": 0},
            {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
             "date": _old_date(), "reinforcement_count": 0},
        ],
    )
    # w1 is a neighbor of id1
    mgr.knowledge_graph.get_neighbors.side_effect = lambda mid, hops=1: {"id1"} if mid == "w1" else set()

    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "w1" not in ids


def test_plan_has_uuid_and_ttl():
    mgr = _fake_manager([])
    plan = build_plan(mgr, project="test")
    assert plan.plan_id  # non-empty
    assert len(plan.plan_id) >= 16  # UUID-ish
    assert plan.expires_at > plan.generated_at
    assert plan.expires_at - plan.generated_at == PLAN_TTL


def test_plan_to_dict_is_json_serializable():
    mgr = _fake_manager([
        {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
         "date": _old_date(), "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    d = plan.to_dict()
    import json
    json.dumps(d)  # must not raise
    assert d["plan_id"] == plan.plan_id
    assert d["project"] == "test"
    assert isinstance(d["candidates"], list)
