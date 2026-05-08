from unittest.mock import MagicMock

from memory.resume import build_resume_packet
from memory.scope import MemoryScope


def test_build_resume_packet_groups_recent_important_and_conflicts(tmp_path):
    from memory.manager import MemoryManager
    from memory.knowledge_graph import KnowledgeGraph

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
            "content": "Use PostgreSQL",
            "project": "brain",
        },
        {
            "memory_id": "b",
            "type": "decision",
            "date": "2026-04-01",
            "content": "Use MySQL",
            "project": "brain",
        },
    ]

    scope = MemoryScope(agent="claude-code", project="brain", repo_name="brain", trust_boundary="personal")
    packet = build_resume_packet(manager, scope=scope)

    assert packet["scope"]["project"] == "brain"
    assert len(packet["important"]) >= 1
    assert len(packet["unresolved"]) == 1
    assert "promotion" in packet
    assert "next_steps" in packet
    assert "handoff" in packet
    assert "pressure" in packet
    assert "pressure_report" in packet
    assert "Resume Packet" in packet["summary"]
