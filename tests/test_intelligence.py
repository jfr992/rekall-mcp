from datetime import datetime, timedelta

import networkx as nx

from memory.intelligence import (
    apply_memory_promotion,
    changed_since_last_session,
    reinforce_and_reclassify,
)


class DummyGraph:
    def __init__(self):
        self._graph = nx.DiGraph()


def test_apply_memory_promotion_updates_tier():
    graph = DummyGraph()
    graph._graph.add_node("m1", access_count=4)

    result = apply_memory_promotion(
        graph,
        [{"memory_id": "m1", "type": "learning", "tier": "working", "salience": 0.4}],
    )

    assert result["promoted"] == 1
    assert result["memories"][0]["tier"] == "episodic"


def test_changed_since_last_session_limits_and_sorts():
    memories = [
        {"memory_id": "a", "date": "2026-04-01", "importance": 0.4, "tier": "working"},
        {"memory_id": "b", "date": "2026-04-10", "importance": 0.8, "tier": "semantic"},
    ]

    result = changed_since_last_session(memories, limit=1)
    assert len(result) == 1
    assert result[0]["memory_id"] == "b"


class _FakeGraph:
    def __init__(self, contradicts: dict[str, int] | None = None):
        self._contradicts = contradicts or {}

    def count_contradicts(self, memory_id: str) -> int:
        return self._contradicts.get(memory_id, 0)


def test_reinforce_increments_count_and_recomputes_tier():
    graph = _FakeGraph()
    memory = {
        "memory_id": "m1",
        "type": "note",
        "salience": 0.3,
        "reinforcement_count": 5,
        "date": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
    }

    updated = reinforce_and_reclassify(memory, graph=graph, now=datetime.now())

    assert updated is not memory  # pure function, returns new dict
    assert updated["reinforcement_count"] == 6
    assert updated["tier"] == "semantic"  # 6 reinforces + 8 days -> promoted
    assert "lifecycle_reason" in updated


def test_reinforce_does_not_promote_identity_away():
    graph = _FakeGraph()
    memory = {
        "memory_id": "m2",
        "type": "preference",
        "tier": "identity",
        "salience": 0.9,
        "reinforcement_count": 1,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    updated = reinforce_and_reclassify(memory, graph=graph, now=datetime.now())

    assert updated["tier"] == "identity"


def test_reinforce_demotes_contradicted_memory():
    graph = _FakeGraph(contradicts={"m3": 3})
    memory = {
        "memory_id": "m3",
        "type": "decision",
        "salience": 0.9,
        "reinforcement_count": 2,
        "date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
    }

    updated = reinforce_and_reclassify(memory, graph=graph, now=datetime.now())

    # decision + salience 0.9 would be semantic; 3 contradicts demote to episodic
    assert updated["tier"] == "episodic"
