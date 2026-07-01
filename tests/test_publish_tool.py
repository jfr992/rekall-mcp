"""Guards the data contract the publish_memory tool formats."""

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
                "content": "a useful long learning about pods here",
                "project": "p",
                "type": "learning",
            }
        ]


class FakeManager:
    def __init__(self, tmp):
        self.store = FakeStore()
        self.knowledge_graph = FakeGraph()
        self.memory_dir = tmp


def test_publish_from_manager_text_summary(tmp_path):
    b = publish_from_manager(FakeManager(tmp_path))
    assert b.tree
    assert b.stats["concepts"] >= 1
    assert b.stats["clusters"] >= 1
