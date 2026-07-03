from memory.startup import build_agent_startup


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
        "active_workstreams": [],
        "operating_rules": [],
        "danger_zones": [],
        "open_loops": [],
    }

    startup = build_agent_startup(manager, project="brain", agent="claude-code")

    assert startup["scope"]["project"] == "brain"
    assert "startup_summary" in startup
    assert "project_capsule" in startup
    assert "system_hints" in startup
    assert "Agent Startup" in startup["startup_summary"]
    assert "Familiarity Capsule" in startup["startup_summary"]
    assert "Codex startup adapter is planned" in startup["startup_summary"]


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

    startup = build_agent_startup(manager, project="brain", agent="claude-code")

    assert startup["scope"]["project"] == "brain"
    assert startup["project_capsule"] == {}
    assert "startup_summary" in startup
    assert "system_hints" in startup
    assert "Agent Startup" in startup["startup_summary"]
    assert "Familiarity Capsule" not in startup["startup_summary"]
