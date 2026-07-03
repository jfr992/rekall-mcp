import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude" / "hooks" / "session-start-memory.sh"
INSTALL = REPO / "claude" / "setup" / "install.sh"


def _fake_curl(tmp_path: Path) -> tuple[Path, Path]:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    calls = tmp_path / "curl-calls.log"
    curl = fakebin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url="${@: -1}"
printf '%s\\n' "$url" >> "$FAKE_CURL_CALLS"

if [[ "$url" == *"/api/memory/capsule"* ]]; then
  if [[ "${FAKE_CAPSULE_FAIL:-0}" == "1" ]]; then
    exit 22
  fi
  printf '{"project":"rekall-mcp","danger_zones":[{"date":"2026-07-03","content":"Back up live files before touching Claude hooks."}]}'
  exit 0
fi

if [[ "$url" == *"/api/memory/context/startup"* ]]; then
  printf '%s' '{"startup_summary":"# Agent Startup\\nFallback startup context loaded."}'
  exit 0
fi

exit 99
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return fakebin, calls


def _run_hook(
    tmp_path: Path,
    payload: dict,
    *,
    capsule_fail: bool = False,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fakebin, calls = _fake_curl(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "FAKE_CURL_CALLS": str(calls),
            "REKALL_API_URL": "http://rekall.test",
        }
    )
    if capsule_fail:
        env["FAKE_CAPSULE_FAIL"] = "1"
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    urls = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, urls


def _settings_commands(settings: dict, event: str) -> list[str]:
    return [
        hook["command"]
        for entry in settings.get("hooks", {}).get(event, [])
        for hook in entry.get("hooks", [])
    ]


def _run_install(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    if not shutil.which("jq"):
        pytest.skip("jq is required by claude/setup/install.sh")
    if not shutil.which("curl"):
        pytest.skip("curl is required by claude/setup/install.sh")

    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(INSTALL), *args],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO,
        check=False,
    )


def test_session_start_hook_prefers_capsule_endpoint(tmp_path):
    result, urls = _run_hook(tmp_path, {"cwd": "/workspaces/rekall-mcp"})

    assert result.returncode == 0, result.stderr
    assert urls == ["http://rekall.test/api/memory/capsule?project=rekall-mcp"]
    packet = json.loads(result.stdout)
    output = packet["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "Back up live files before touching Claude hooks." in output["additionalContext"]
    assert "Save durable decisions" in output["additionalContext"]


def test_session_start_hook_falls_back_to_startup_context(tmp_path):
    result, urls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp"},
        capsule_fail=True,
    )

    assert result.returncode == 0, result.stderr
    assert urls == [
        "http://rekall.test/api/memory/capsule?project=rekall-mcp",
        "http://rekall.test/api/memory/context/startup?project=rekall-mcp&agent=claude-code&limit=8",
    ]
    packet = json.loads(result.stdout)
    assert "Fallback startup context loaded." in packet["hookSpecificOutput"]["additionalContext"]


def test_session_start_hook_infers_project_from_project_dir(tmp_path):
    result, urls = _run_hook(tmp_path, {"project_dir": "/Users/test/Agent Project"})

    assert result.returncode == 0, result.stderr
    assert urls == ["http://rekall.test/api/memory/capsule?project=Agent%20Project"]
    packet = json.loads(result.stdout)
    assert "REKALL STARTUP (Agent Project)" in packet["hookSpecificOutput"]["additionalContext"]


def test_session_start_hook_honors_autosave_disable(tmp_path):
    result, urls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp"},
        extra_env={"REKALL_AUTOSAVE": "0"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert urls == []


def test_installer_default_does_not_install_startup_capsule(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    result = _run_install(home, "--hooks-only")

    assert result.returncode == 0, result.stderr + result.stdout
    assert (home / ".claude" / "hooks" / "rekall-restore.sh").exists()
    assert (home / ".claude" / "hooks" / "rekall-observe.sh").exists()
    assert not (home / ".claude" / "hooks" / "session-start-memory.sh").exists()
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "SessionStart" not in settings.get("hooks", {})


def test_installer_opt_in_installs_startup_capsule_and_backs_up_existing_hook(tmp_path):
    home = tmp_path / "home"
    hooks = home / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    old_hook = hooks / "session-start-memory.sh"
    old_hook.write_text("#!/usr/bin/env bash\necho old-session-start\n", encoding="utf-8")
    old_hook.chmod(0o755)
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/test/.claude/hooks/preexisting-start.sh",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = _run_install(home, "--hooks-only", "--install-startup-capsule")

    assert result.returncode == 0, result.stderr + result.stdout
    installed = hooks / "session-start-memory.sh"
    assert installed.exists()
    assert os.access(installed, os.X_OK)
    assert "api/memory/capsule" in installed.read_text(encoding="utf-8")
    backups = list(
        (home / ".claude" / "backups").glob(
            "rekall-live-config-*/hooks/session-start-memory.sh"
        )
    )
    assert len(backups) == 1
    assert "old-session-start" in backups[0].read_text(encoding="utf-8")

    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = _settings_commands(settings, "SessionStart")
    assert "/Users/test/.claude/hooks/preexisting-start.sh" in commands
    assert str(installed) in commands


def test_docs_document_startup_capsule_opt_in_and_live_backup_rule():
    for path in [REPO / "claude" / "INSTALL.md", REPO / "docs" / "AGENT_STARTUP.md"]:
        text = path.read_text(encoding="utf-8")
        assert "--install-startup-capsule" in text
        assert "~/.claude/backups/rekall-live-config-<timestamp>/" in text
