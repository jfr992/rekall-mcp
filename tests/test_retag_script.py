"""Bulk retag CLI is dry-run by default and can skip ambiguous project groups."""

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retag_memories.py"


def _cli():
    spec = importlib.util.spec_from_file_location("retag_memories", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _map():
    return [
        {
            "from": "veril-clips-kick",
            "count": 2,
            "to": {
                "veril-clips": {"prefix": ["2026-11-21_decision_aaa", "2026-11-21_decision_bbb"]}
            },
        },
        {
            "from": "app",
            "count": 2,
            "to": {"capillas": {"mixed": ["2026-08-09_fact_ccc", "2026-08-09_fact_ddd"]}},
        },
        {
            "from": "clawd",
            "count": 1,
            "to": {"capillas": {"umbrella": ["2026-07-25_decision_eee"]}},
        },
        {
            "from": "memento-mcp",
            "count": 1,
            "to": {"rekall-mcp": {"alias": ["2026-04-14_fact_fff"]}},
        },
    ]


def test_plan_excludes_ambiguous_app_and_clawd_groups(tmp_path):
    path = tmp_path / "retag-map.json"
    path.write_text(json.dumps(_map()))

    plan = _cli().build_plan(path, exclude_from={"app", "clawd"})

    pairs = {(item["from"], item["to"]) for item in plan}
    assert ("veril-clips-kick", "veril-clips") in pairs
    assert ("memento-mcp", "rekall-mcp") in pairs
    assert all(item["from"] not in {"app", "clawd"} for item in plan)
    assert sum(item["count"] for item in plan) == 3


def test_dry_run_does_not_call_apply(tmp_path, capsys):
    path = tmp_path / "retag-map.json"
    path.write_text(json.dumps(_map()))
    called = []

    summary = _cli().main_with_args(
        ["--map", str(path)],
        apply_one=lambda mid, project: called.append((mid, project)),
    )

    assert called == []
    assert summary["applied"] == 0
    assert summary["dry_run"] is True
    out = capsys.readouterr().out
    assert "veril-clips-kick" in out and "veril-clips" in out
    assert "memento-mcp" in out
    # Ambiguous groups stay out of the default plan.
    assert "app ->" not in out and "clawd ->" not in out


def test_apply_flag_patches_each_id(tmp_path):
    path = tmp_path / "retag-map.json"
    path.write_text(json.dumps(_map()))
    called = []

    summary = _cli().main_with_args(
        ["--map", str(path), "--apply"],
        apply_one=lambda mid, project: called.append((mid, project)) or True,
    )

    assert summary["dry_run"] is False
    assert ("2026-11-21_decision_aaa", "veril-clips") in called
    assert ("2026-04-14_fact_fff", "rekall-mcp") in called
    assert all(not mid.endswith(("ccc", "ddd", "eee")) for mid, _ in called)
    assert summary["applied"] == 3
