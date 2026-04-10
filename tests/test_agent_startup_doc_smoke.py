from pathlib import Path


def test_agent_startup_doc_exists():
    doc = Path(__file__).resolve().parent.parent / "docs" / "AGENT_STARTUP.md"
    assert doc.exists()
    content = doc.read_text()
    assert "agent_startup" in content
    assert "resume_packet" in content
    assert "handoff_summary" in content
    assert "memory_pressure" in content
