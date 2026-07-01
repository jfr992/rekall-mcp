import networkx as nx

from memory.publish import cluster_memories


class FakeGraph:
    def __init__(self, edges):
        self._graph = nx.DiGraph()
        for s, t, rel in edges:
            self._graph.add_edge(s, t, relation=rel)


def _mem(mid, mtype="learning"):
    return {"memory_id": mid, "type": mtype, "content": f"c-{mid}"}


def test_dense_blob_splits_into_communities_not_arbitrary_chunks():
    # Two tight clusters bridged by a single edge — modularity should find 2 groups.
    mems = [_mem(str(i)) for i in range(10)]
    edges = []
    for a in range(5):
        for b in range(5):
            if a < b:
                edges.append((str(a), str(b), "related_to"))
    for a in range(5, 10):
        for b in range(5, 10):
            if a < b:
                edges.append((str(a), str(b), "related_to"))
    edges.append(("2", "7", "related_to"))  # single bridge
    g = FakeGraph(edges)
    clusters = cluster_memories(mems, g)
    # Expect ~2 communities, each a coherent group — not one blob, not 10 singletons.
    assert 2 <= len(clusters) <= 4
    assert max(len(c) for c in clusters) <= 6


def test_contradicts_still_excluded():
    mems = [_mem("a"), _mem("b")]
    g = FakeGraph([("a", "b", "contradicts")])
    clusters = cluster_memories(mems, g)
    assert len(clusters) == 2


def test_isolated_memory_is_singleton():
    mems = [_mem("a"), _mem("b"), _mem("c")]
    g = FakeGraph([("a", "b", "related_to")])
    clusters = cluster_memories(mems, g)
    assert [1, 2] == sorted(len(c) for c in clusters)
