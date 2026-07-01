import networkx as nx
from memory.publish import publish_from_manager


class FakeGraph:
    def __init__(self):
        self._graph = nx.DiGraph()

    def get_edges(self, mid, direction="both"):
        return []


class FakeStore:
    def scroll(self, filters=None, limit=100, with_vectors=False):
        return [
            {
                "memory_id": "a",
                "content": "a long useful learning about pods here",
                "project": "p",
                "type": "learning",
            }
        ]


class FakeManager:
    def __init__(self, tmp):
        self.store = FakeStore()
        self.knowledge_graph = FakeGraph()
        self.memory_dir = tmp


def test_publish_from_manager_slug_when_no_judge(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMENTO_JUDGE_MODEL", raising=False)
    b = publish_from_manager(FakeManager(tmp_path))
    assert b.stats["titled_by"] == "slug"
    assert b.stats["concepts"] >= 1


def test_publish_writes_and_reuses_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMENTO_JUDGE_MODEL", raising=False)
    publish_from_manager(FakeManager(tmp_path))
    assert (tmp_path / "_publish_cache.json").exists()
