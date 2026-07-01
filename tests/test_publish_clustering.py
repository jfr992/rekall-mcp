import networkx as nx

from memory.publish import cluster_memories


class FakeGraph:
    def __init__(self, edges):
        self._graph = nx.DiGraph()
        for s, t, rel in edges:
            self._graph.add_edge(s, t, relation=rel)


def _mem(mid, mtype="learning"):
    return {"memory_id": mid, "type": mtype, "content": f"c-{mid}"}


def test_related_memories_cluster_together():
    mems = [_mem("a"), _mem("b"), _mem("c")]
    g = FakeGraph([("a", "b", "related_to"), ("b", "c", "led_to")])
    clusters = cluster_memories(mems, g)
    assert len(clusters) == 1
    assert {m["memory_id"] for m in clusters[0]} == {"a", "b", "c"}


def test_contradicts_does_not_merge():
    mems = [_mem("a"), _mem("b")]
    g = FakeGraph([("a", "b", "contradicts")])
    clusters = cluster_memories(mems, g)
    assert len(clusters) == 2


def test_singleton_is_own_cluster():
    mems = [_mem("a"), _mem("b"), _mem("c")]
    g = FakeGraph([("a", "b", "related_to")])
    clusters = cluster_memories(mems, g)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_oversized_cluster_splits_by_type():
    mems = [_mem(str(i), "learning") for i in range(20)]
    edges = [(str(i), str(i + 1), "related_to") for i in range(19)]
    g = FakeGraph(edges)
    clusters = cluster_memories(mems, g)
    assert all(len(c) <= 15 for c in clusters)
