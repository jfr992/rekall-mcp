"""Agent startup semantics.

Provides one high-level startup packet that agent clients can call at the
beginning of a session instead of stitching together multiple tools manually.
"""

from __future__ import annotations

from typing import Any

from memory.scope import MemoryScope, ScopeDetector

SYSTEM_HINTS = {
    "claude-code": [
        "Load resume_packet or handoff_summary at session start.",
        "Prefer observe() for durable decisions, learnings, requirements, and preferences.",
        "Avoid saving routine command output or temporary exploration.",
    ],
    "codex": [
        "Load resume_packet before making planning decisions.",
        "Persist architectural changes, bug root causes, and user preferences.",
        "Keep project boundaries strict when switching repos or branches.",
    ],
    "unknown": [
        "Load resume_packet at startup.",
        "Save only durable, high-signal memories.",
    ],
}


def build_agent_startup(
    manager, *, project: str | None = None, agent: str | None = None, limit: int = 12
) -> dict[str, Any]:
    scope = ScopeDetector.detect(project=project, agent=agent)
    packet = manager.get_resume_packet(project=scope.project, scope=scope, limit=limit)
    try:
        capsule = manager.get_project_capsule(scope.project, limit=300)
    except Exception:
        capsule = {}
    try:
        doctor = manager.doctor(project=scope.project)
    except Exception as e:
        doctor = {
            "status": "unavailable",
            "project": scope.project,
            "findings": ["doctor_unavailable"],
            "error": str(e),
        }

    hints = SYSTEM_HINTS.get(scope.agent, SYSTEM_HINTS["unknown"])

    return {
        "scope": packet["scope"],
        "startup_summary": render_agent_startup(
            scope,
            packet,
            hints,
            capsule=capsule,
            doctor=doctor,
        ),
        "resume_packet": packet,
        "project_capsule": capsule,
        "doctor": doctor,
        "system_hints": hints,
    }


def render_agent_startup(
    scope: MemoryScope,
    packet: dict[str, Any],
    hints: list[str],
    capsule: dict[str, Any] | None = None,
    doctor: dict[str, Any] | None = None,
) -> str:
    lines = [f"# Agent Startup: {scope.project}", ""]
    lines.append(f"- agent: {scope.agent}")
    if scope.repo_name:
        lines.append(f"- repo: {scope.repo_name}")
    if scope.branch:
        lines.append(f"- branch: {scope.branch}")
    lines.append("")

    lines.append("## Startup Hints")
    for hint in hints:
        lines.append(f"- {hint}")
    lines.append("")

    if capsule:
        from memory.capsules import render_project_capsule

        lines.append("## Familiarity Capsule")
        lines.append(render_project_capsule(capsule).strip())
        lines.append("")

    if doctor and doctor.get("status") != "healthy":
        findings = doctor.get("findings") or []
        lines.append("## Memory Doctor")
        lines.append(f"- status: {doctor.get('status', 'unknown')}")
        if findings:
            lines.append(f"- findings: {', '.join(str(item) for item in findings)}")
        if doctor.get("error"):
            lines.append(f"- error: {doctor['error']}")
        lines.append("")

    if packet.get("next_steps"):
        lines.append("## Next Steps")
        for step in packet["next_steps"][:6]:
            lines.append(f"- {step}")
        lines.append("")

    lines.append(packet.get("handoff") or packet.get("summary") or "")
    return "\n".join(lines).strip() + "\n"
