from unittest.mock import MagicMock

from memory.resume import build_resume_packet
from memory.scope import MemoryScope


def test_build_resume_packet_does_not_inject_unverified_conflicts(tmp_path):
    from memory.knowledge_graph import KnowledgeGraph
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = MagicMock()
    manager._embedder = MagicMock()
    manager._embedder.encode.return_value = [0.1] * 384

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("a", memory_type="decision")
    kg.add_node("b", memory_type="decision")
    kg.add_edge("a", "b", "contradicts", 0.8)
    manager._knowledge_graph = kg

    manager._store.scroll.return_value = [
        {
            "memory_id": "a",
            "type": "decision",
            "date": "2026-04-10",
            "content": "PR #83 merged and deployed",
            "disputed": True,
            "project": "brain",
        },
        {
            "memory_id": "b",
            "type": "decision",
            "date": "2026-04-01",
            "content": "PR #83 pending review",
            "project": "brain",
        },
    ]

    scope = MemoryScope(
        agent="claude-code", project="brain", repo_name="brain", trust_boundary="personal"
    )
    packet = build_resume_packet(manager, scope=scope)

    assert packet["scope"]["project"] == "brain"
    assert len(packet["important"]) >= 1
    assert packet["unresolved"] == []
    assert "Unresolved Conflicts" not in packet["summary"]
    assert {item["memory_id"] for item in packet["important"]} == {"a", "b"}
    assert packet["recent"][0]["memory_id"] == "a"
    assert "promotion" in packet
    assert "next_steps" in packet
    assert "handoff" in packet
    assert "pressure" in packet
    assert "pressure_report" in packet
    assert "Resume Packet" in packet["summary"]


def test_build_resume_packet_none_scope_renders_summary(tmp_path):
    """Live bug: all-scopes resume (scope=None) crashed on scope.project in the summary."""
    from memory.knowledge_graph import KnowledgeGraph
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = MagicMock()
    manager._embedder = MagicMock()
    manager._knowledge_graph = KnowledgeGraph(tmp_path / "_graph.json")
    manager._store.scroll.return_value = [
        {
            "memory_id": "a",
            "type": "decision",
            "date": "2026-04-10",
            "content": "Use PostgreSQL",
            "project": "brain",
        },
    ]

    packet = build_resume_packet(manager, scope=None)

    assert packet["scope"] is None
    assert packet["summary"].startswith("# Resume Packet: all projects")


def _conflict_packet(tmp_path, b_extra=None, extra_edges=()):
    from memory.knowledge_graph import KnowledgeGraph
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = MagicMock()
    manager._embedder = MagicMock()
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("a", memory_type="decision")
    kg.add_node("b", memory_type="decision")
    kg.add_edge("a", "b", "contradicts", 0.8, llm_refined=True)
    for src, dst, rel in extra_edges:
        kg.add_edge(src, dst, rel, 0.9)
    manager._knowledge_graph = kg
    base = {"type": "decision", "date": "2026-04-01", "project": "brain"}
    manager._store.scroll.return_value = [
        {**base, "memory_id": "a", "content": "a says X"},
        {**base, "memory_id": "b", "content": "b says Y", **(b_extra or {})},
    ]
    scope = MemoryScope(
        agent="claude-code", project="brain", repo_name="brain", trust_boundary="personal"
    )
    return build_resume_packet(manager, scope=scope)


def test_resume_lists_model_verified_conflicts(tmp_path):
    packet = _conflict_packet(tmp_path)
    assert packet["unresolved"] == [
        {"memory_id": "a", "conflicts_with": "b", "content": "a says X"}
    ]


def test_resume_skips_conflicts_with_a_disputed_side(tmp_path):
    assert _conflict_packet(tmp_path, b_extra={"disputed": True})["unresolved"] == []


def test_resume_skips_conflicts_with_a_compacted_side(tmp_path):
    assert _conflict_packet(tmp_path, b_extra={"compacted": True})["unresolved"] == []


def test_resume_skips_conflicts_with_a_superseded_side(tmp_path):
    packet = _conflict_packet(tmp_path, extra_edges=[("c", "b", "supersedes")])
    assert packet["unresolved"] == []
