"""rekall-provenance.sh: fills cwd/session_id/agent on Rekall MCP calls (spec section 4)."""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude" / "hooks" / "rekall-provenance.sh"


def _run(payload: dict, env_extra: dict | None = None):
    env = os.environ.copy()
    env["REKALL_AUTOSAVE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )


def _payload(tool, tool_input):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-42",
        "cwd": "/Users/me/Repos/proj",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def test_adds_provenance_to_recall():
    r = _run(_payload("mcp__memory__recall_memories", {"query": "ports", "limit": 3}))
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["updatedInput"] == {
        "query": "ports",
        "limit": 3,
        "cwd": "/Users/me/Repos/proj",
        "session_id": "sess-42",
        "agent": "claude-code",
    }
    assert "permissionDecision" not in out


def test_rekall_namespace_also_matches():
    r = _run(_payload("mcp__rekall__save_memory", {"content": "x"}))
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["session_id"] == "sess-42"


def test_does_not_overwrite_model_supplied_fields():
    r = _run(_payload("mcp__memory__observe", {"summary": "x", "cwd": "/elsewhere", "session_id": "mine"}))
    out = json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]
    assert out["cwd"] == "/elsewhere"
    assert out["session_id"] == "mine"
    assert out["agent"] == "claude-code"


def test_tool_outside_allowlist_emits_nothing():
    r = _run(_payload("mcp__memory__close_loop", {"memory_id": "m1"}))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_non_rekall_tool_emits_nothing():
    r = _run(_payload("Bash", {"command": "ls"}))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_kill_switch():
    r = _run(_payload("mcp__memory__recall_memories", {"query": "x"}), {"REKALL_AUTOSAVE": "0"})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_malformed_stdin_exits_zero_silently():
    env = os.environ.copy()
    r = subprocess.run(["bash", str(HOOK)], input="not json", text=True, capture_output=True, env=env, timeout=10)
    assert r.returncode == 0
    assert r.stdout.strip() == ""
