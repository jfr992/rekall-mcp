import networkx as nx

from memory.intelligence import apply_memory_promotion, changed_since_last_session


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
