import networkx as nx

from memory.publish import prewarm_synthesis, publish_from_manager


class FakeGraph:
    def __init__(self):
        self._graph = nx.DiGraph()

    def get_edges(self, mid, direction="both"):
        return []


class FakeStore:
    def scroll(self, filters=None, limit=100, with_vectors=False):
        return [
            {
                "memory_id": str(i),
                "content": f"a useful long learning number {i} here",
                "project": "p",
                "type": "learning",
            }
            for i in range(5)
        ]


class FakeManager:
    def __init__(self, tmp):
        self.store = FakeStore()
        self.knowledge_graph = FakeGraph()
        self.memory_dir = tmp


def test_preview_is_raw_and_never_calls_llm(tmp_path, monkeypatch):
    # Even with model env set, synthesize=False must NOT call the LLM.
    monkeypatch.setenv("MEMENTO_PUBLISH_MODEL", "x")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://unused")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    b = publish_from_manager(FakeManager(tmp_path), synthesize=False)
    assert b.stats["synthesized"] == "raw"
    assert b.stats["concepts"] >= 1


def test_prewarm_reports_progress():
    seen = []

    def synth(cluster):
        return (f"t{cluster[0]['memory_id']}", "brief")

    clusters = [[{"memory_id": str(i), "type": "learning", "content": f"c{i}"}] for i in range(4)]
    prewarm_synthesis(clusters, {}, synth, workers=4, progress=lambda d, t: seen.append((d, t)))
    assert seen  # progress fired
    assert seen[-1] == (4, 4)  # final done==total
