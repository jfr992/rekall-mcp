from unittest.mock import MagicMock

from memory.prune import apply_prune_plan, plan_prune


def test_plan_prune_selects_only_low_salience_working_memories():
    plan = plan_prune(
        [
            {"memory_id": "a", "tier": "working", "salience": 0.2, "retention_days": 14, "date": "2026-03-01", "content": "opened file", "type": "note"},
            {"memory_id": "b", "tier": "semantic", "salience": 0.1, "retention_days": 365, "date": "2026-03-01", "content": "Use PostgreSQL", "type": "decision"},
        ]
    )

    assert plan["selected_count"] == 1
    assert plan["selected"][0]["memory_id"] == "a"


def test_apply_prune_plan_dry_run_lists_ids():
    manager = MagicMock()
    result = apply_prune_plan(manager, {"selected": [{"memory_id": "a"}], "selected_count": 1}, dry_run=True)

    assert result["deleted_count"] == 1
    assert result["memory_ids"] == ["a"]
    manager.delete.assert_not_called()
