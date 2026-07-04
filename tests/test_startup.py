from unittest.mock import MagicMock

from memory.scope import MemoryScope
from memory.startup import build_agent_startup, render_agent_startup


def test_build_agent_startup_returns_summary():
    manager = type("Manager", (), {})()
    manager.get_resume_packet = lambda **kwargs: {
        "scope": {"project": "brain", "agent": "claude-code"},
        "next_steps": ["Add Codex startup adapter"],
        "handoff": "## Handoff Summary\n",
        "summary": "# Resume Packet: brain\n",
    }
    manager.get_project_capsule = lambda project, limit=300: {
        "project": project,
        "entities": ["Codex"],
        "standing_context": [
            {"date": "2026-07-03", "content": "Codex startup adapter is planned."}
        ],
        "danger_zones": [],
        "open_loops": [],
    }
    manager.doctor = MagicMock(side_effect=AssertionError("doctor should be on-demand"))

    startup = build_agent_startup(manager, project="brain", agent="claude-code")

    assert startup["scope"]["project"] == "brain"
    assert "startup_summary" in startup
    assert "project_capsule" in startup
    assert startup["doctor"] == {}
    assert "system_hints" in startup
    assert "Agent Startup" in startup["startup_summary"]
    assert "Familiarity Capsule" in startup["startup_summary"]
    assert "Memory Doctor" not in startup["startup_summary"]
    assert "Codex startup adapter is planned" in startup["startup_summary"]
    manager.doctor.assert_not_called()


def test_build_agent_startup_degrades_when_capsule_fails():
    manager = type("Manager", (), {})()
    manager.get_resume_packet = lambda **kwargs: {
        "scope": {"project": "brain", "agent": "claude-code"},
        "next_steps": ["Add Codex startup adapter"],
        "handoff": "## Handoff Summary\n",
        "summary": "# Resume Packet: brain\n",
    }

    def _boom(*args, **kwargs):
        raise RuntimeError("capsule unavailable")

    manager.get_project_capsule = _boom
    manager.doctor = MagicMock(side_effect=AssertionError("doctor should be on-demand"))

    startup = build_agent_startup(manager, project="brain", agent="claude-code")

    assert startup["scope"]["project"] == "brain"
    assert startup["project_capsule"] == {}
    assert "startup_summary" in startup
    assert "system_hints" in startup
    assert "Agent Startup" in startup["startup_summary"]
    assert "Familiarity Capsule" not in startup["startup_summary"]
    manager.doctor.assert_not_called()


def test_render_agent_startup_includes_doctor_warning_when_supplied():
    packet = {
        "scope": {"project": "brain", "agent": "claude-code"},
        "next_steps": [],
        "handoff": "## Handoff Summary\n",
        "summary": "# Resume Packet: brain\n",
    }
    doctor = {
        "status": "degraded",
        "project": "brain",
        "findings": ["yaml_not_indexed", "missing_provenance"],
    }

    summary = render_agent_startup(
        MemoryScope(project="brain", agent="claude-code"),
        packet,
        [],
        doctor=doctor,
    )

    assert "Memory Doctor" in summary
    assert "yaml_not_indexed, missing_provenance" in summary
