"""Smoke test that the compat aliases plan_prune/apply_prune_plan still resolve.

Behavioral tests live in test_prune_safety.py.
"""

from memory.prune import apply_prune_plan, plan_prune


def test_legacy_aliases_importable():
    assert callable(plan_prune)
    assert callable(apply_prune_plan)


def test_plan_prune_excludes_unknown_salience():
    """Legacy alias must also respect the unknown-salience exemption."""
    plan = plan_prune(
        [
            {"memory_id": "a", "tier": "working", "type": "note"},  # no salience
            {"memory_id": "b", "tier": "working", "type": "note", "salience": 0.1},
        ]
    )
    assert plan["selected_count"] == 1
    assert plan["selected"][0]["memory_id"] == "b"


def test_apply_prune_plan_dry_run_lists_ids():
    from unittest.mock import MagicMock

    manager = MagicMock()
    result = apply_prune_plan(
        manager, {"selected": [{"memory_id": "a"}], "selected_count": 1}, dry_run=True
    )
    assert result["deleted_count"] == 1
    assert result["memory_ids"] == ["a"]
    manager.delete.assert_not_called()
