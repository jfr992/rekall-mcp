"""Repair of unrefined contradicts edges (U2.5 T0c).

Tmp graphs + fake store only — never production. The script's core is pure:
it takes an open KnowledgeGraph and any object with get_many.
"""

from __future__ import annotations

from scripts.repair_contradicts import repair_contradicts

from memory.knowledge_graph import KnowledgeGraph


class _FakeStore:
    def __init__(self, contents: dict[str, str]) -> None:
        self._contents = contents

    def get_many(self, memory_ids: list[str], with_vectors: bool = False) -> list[dict]:
        return [
            {"memory_id": m, "content": self._contents[m]}
            for m in memory_ids
            if m in self._contents
        ]


def _graph_with_unrefined_edge(tmp_path, weight: float = 0.5) -> KnowledgeGraph:
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("new")
    kg.add_node("old")
    kg.add_edge("new", "old", "contradicts", weight)
    return kg


def test_dry_run_reports_counts_without_mutating(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kg = _graph_with_unrefined_edge(tmp_path, weight=0.5)
    store = _FakeStore(
        {
            "new": "Use MongoDB as primary datastore",
            "old": "Use PostgreSQL as primary datastore",
        }
    )

    result = repair_contradicts(kg, store)  # dry-run is the default

    assert result["applied"] is False
    assert result["examined"] == 1
    assert result["downgraded"] == 1
    assert result["before"]["contradicts"] == 1
    assert result["after"].get("contradicts", 0) == 0
    # no mutation, no save
    assert kg._graph.edges["new", "old"]["relation"] == "contradicts"
    assert not (tmp_path / "_graph.json").exists()


def test_apply_downgrades_unsupported_edge(tmp_path, monkeypatch):
    """No key, no negation → the edge has no supporting evidence: downgraded
    to related_to and saved."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kg = _graph_with_unrefined_edge(tmp_path, weight=0.65)
    store = _FakeStore(
        {
            "new": "Use MongoDB as primary datastore",
            "old": "Use PostgreSQL as primary datastore",
        }
    )

    result = repair_contradicts(kg, store, apply=True)

    assert result["applied"] is True
    assert result["downgraded"] == 1
    assert kg._graph.edges["new", "old"]["relation"] == "related_to"
    assert (tmp_path / "_graph.json").exists()
    assert result["after"].get("contradicts", 0) == 0


def test_apply_keeps_negation_backed_edge_with_marker(tmp_path, monkeypatch):
    """No key, weight >= 0.60, asymmetric negation → kept, negation_matched=True."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kg = _graph_with_unrefined_edge(tmp_path, weight=0.65)
    store = _FakeStore(
        {
            "new": "Do not use PostgreSQL for primary storage anymore",
            "old": "Use PostgreSQL for primary storage",
        }
    )

    result = repair_contradicts(kg, store, apply=True)

    assert result["kept_negation"] == 1
    assert result["downgraded"] == 0
    edge = kg._graph.edges["new", "old"]
    assert edge["relation"] == "contradicts"
    assert edge["negation_matched"] is True


def test_apply_llm_keep_marks_llm_refined(tmp_path, monkeypatch):
    """Key present + LLM says CONTRADICTS → kept, llm_refined=True."""
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    mock_response = SimpleNamespace(content=[SimpleNamespace(text="CONTRADICTS")])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    kg = _graph_with_unrefined_edge(tmp_path, weight=0.65)
    store = _FakeStore(
        {
            "new": "Use MongoDB as primary datastore",
            "old": "Use PostgreSQL as primary datastore",
        }
    )

    result = repair_contradicts(kg, store, apply=True)

    assert result["kept_llm"] == 1
    assert result["downgraded"] == 0
    edge = kg._graph.edges["new", "old"]
    assert edge["relation"] == "contradicts"
    assert edge["llm_refined"] is True


def test_markers_survive_save_and_reload(tmp_path, monkeypatch):
    """negation_matched must round-trip through save+reload (T0a fix) so a
    second repair pass skips already-judged edges."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kg = _graph_with_unrefined_edge(tmp_path, weight=0.65)
    store = _FakeStore(
        {
            "new": "Do not use PostgreSQL for primary storage anymore",
            "old": "Use PostgreSQL for primary storage",
        }
    )
    repair_contradicts(kg, store, apply=True)

    kg2 = KnowledgeGraph(tmp_path / "_graph.json")
    assert kg2._graph.edges["new", "old"]["negation_matched"] is True

    rerun = repair_contradicts(kg2, store, apply=True)
    assert rerun["examined"] == 0


def test_limit_caps_edges_examined(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    for n in ("a", "b", "c"):
        kg.add_node(n)
    kg.add_edge("a", "b", "contradicts", 0.5)
    kg.add_edge("a", "c", "contradicts", 0.5)
    store = _FakeStore({"a": "Use MongoDB", "b": "Use PostgreSQL", "c": "Use MySQL"})

    result = repair_contradicts(kg, store, limit=1)

    assert result["examined"] == 1
