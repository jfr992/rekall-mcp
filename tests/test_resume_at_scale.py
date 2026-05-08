"""Fix C2 — resume must sort by date, not by Qdrant point-id order."""

import random
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from memory.resume import build_resume_packet
from memory.scope import MemoryScope


def _fake_manager(memories):
    mgr = MagicMock()
    mgr.store.scroll.return_value = memories
    mgr.knowledge_graph.stats.return_value = {"nodes": 0, "edges": 0}
    mgr.knowledge_graph.get_importance.return_value = 0.5
    mgr.knowledge_graph.get_edges.return_value = []
    return mgr


def _scope(project="test"):
    return MemoryScope(agent="claude-code", project=project, trust_boundary="personal")


def test_resume_returns_recent_by_date_not_insertion_order():
    memories = []
    dates = [f"2026-0{(i%4)+1}-{(i%28)+1:02d}" for i in range(100)]
    random.seed(0)
    random.shuffle(dates)
    for i, d in enumerate(dates):
        memories.append({
            "memory_id": f"m{i}",
            "type": "note",
            "content": f"m{i}",
            "date": d,
            "tier": "working",
        })

    mgr = _fake_manager(memories)
    packet = build_resume_packet(mgr, scope=_scope(), limit=20)

    recent = packet["recent"]
    # recent must be non-empty and sorted descending by date
    assert len(recent) > 0
    dates_out = [r["date"] for r in recent]
    assert dates_out == sorted(dates_out, reverse=True)
    # And must include the absolute latest date from the input set
    latest = max(dates)
    assert any(r["date"] == latest for r in recent)


def test_resume_truncated_flag_on_overflow(monkeypatch):
    import memory.resume as resume_mod
    monkeypatch.setattr(resume_mod, "MAX_RESUME_SCROLL", 50)

    memories = [
        {"memory_id": f"m{i}", "type": "note", "content": f"m{i}",
         "date": "2026-01-01", "tier": "working"}
        for i in range(100)
    ]
    mgr = _fake_manager(memories)

    packet = build_resume_packet(mgr, scope=_scope(), limit=20)
    assert packet["truncated"] is True


def test_resume_not_truncated_when_under_cap():
    memories = [
        {"memory_id": f"m{i}", "type": "note", "content": f"m{i}",
         "date": "2026-01-01", "tier": "working"}
        for i in range(50)
    ]
    mgr = _fake_manager(memories)

    packet = build_resume_packet(mgr, scope=_scope(), limit=20)
    assert packet["truncated"] is False


def test_resume_handles_empty_project():
    mgr = _fake_manager([])
    packet = build_resume_packet(mgr, scope=_scope(), limit=20)
    assert packet["recent"] == []
    assert packet["important"] == []
    assert packet["truncated"] is False
