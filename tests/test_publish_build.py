import networkx as nx
from memory.publish import build_bundle, make_title_fn, map_type
from memory.renderers import get_renderer


class FakeGraph:
    def __init__(self, edges):
        self._graph = nx.DiGraph()
        for s, t, rel in edges:
            self._graph.add_edge(s, t, relation=rel, weight=0.6)

    def get_edges(self, mid, direction="both"):
        out = []
        for s, t, d in self._graph.edges(data=True):
            if s == mid or t == mid:
                out.append(
                    type("E", (), {"source": s, "target": t, "relation": d["relation"]})
                )
        return out


def _mem(mid, content, project="byte-edge", mtype="learning"):
    return {"memory_id": mid, "content": content, "project": project, "type": mtype}


def test_build_bundle_produces_concepts():
    mems = [_mem("a", "KubeVirt stuck namespace recovery recipe long enough")]
    g = FakeGraph([])
    b = build_bundle(mems, g, title_fn=make_title_fn({}), renderer=get_renderer("okf"))
    assert b.stats["concepts"] >= 1
    assert any(p.endswith(".md") and "index" not in p for p in b.tree)


def test_map_type_learning_to_runbook():
    assert map_type("learning") == "runbook"
    assert map_type("decision") == "decision"


def test_short_notes_filtered_out():
    mems = [
        _mem("a", "hi", mtype="note"),
        _mem("b", "a genuinely long useful learning here"),
    ]
    g = FakeGraph([])
    b = build_bundle(mems, g, title_fn=make_title_fn({}), renderer=get_renderer("okf"))
    joined = "\n".join(b.files.values())
    assert "genuinely long useful" in joined
    assert "\n## hi\n" not in joined


def test_contradicts_becomes_related_link():
    mems = [
        _mem("a", "we should use approach X for the thing"),
        _mem("b", "we should NOT use approach X for the thing"),
    ]
    g = FakeGraph([("a", "b", "contradicts")])
    b = build_bundle(mems, g, title_fn=make_title_fn({}), renderer=get_renderer("okf"))
    joined = "\n".join(b.files.values())
    assert "## Related" in joined
