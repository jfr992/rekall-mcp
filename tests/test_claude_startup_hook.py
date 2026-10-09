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
  printf '{"project":"rekall-mcp","danger_zones":[{"memory_id":"2026-07-03_learning_ab12cd34","date":"2026-07-03","content":"Back up live files before touching Claude hooks."}]}'
  exit 0
fi

if [[ "$url" == *"/api/memory/context/startup"* ]]; then
  if [[ "${FAKE_STARTUP_FAIL:-0}" == "1" ]]; then
    exit 22
  fi
  printf '%s' '{"startup_summary":"# Agent Startup\\nFallback startup context loaded."}'
  exit 0
fi

exit 99
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return fakebin, calls


def _fake_blocking_curl(tmp_path: Path) -> tuple[Path, Path]:
    fakebin = tmp_path / "installer-fakebin"
    fakebin.mkdir(exist_ok=True)
    calls = tmp_path / "installer-curl-calls.log"
    curl = fakebin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_CURL_CALLS"
exit 7
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
    startup_fail: bool = False,
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
    if startup_fail:
        env["FAKE_STARTUP_FAIL"] = "1"
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


def _run_install(
    home: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
    detect_dirs: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    if not shutil.which("jq"):
        pytest.skip("jq is required by claude/setup/install.sh")
    if not shutil.which("curl"):
        pytest.skip("curl is required by claude/setup/install.sh")

    (home / ".claude").mkdir(parents=True, exist_ok=True)
    fakebin, calls = _fake_blocking_curl(home)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    env["FAKE_CURL_CALLS"] = str(calls)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.update(env_extra or {})
    flags = ["--no-detect"]
    if detect_dirs is not None:
        flags = []
        fake_ps = fakebin / "ps"
        fake_ps.write_text(
            "#!/bin/sh\nfor d in $FAKE_PS_DIRS; do "
            'echo "/usr/local/bin/claude --flag CLAUDE_CONFIG_DIR=$d"; done\n',
            encoding="utf-8",
        )
        fake_ps.chmod(0o755)
        env["FAKE_PS_DIRS"] = " ".join(detect_dirs)
    result = subprocess.run(
        ["bash", str(INSTALL), *flags, *args],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO,
        check=False,
    )
    urls = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, urls


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


def test_session_start_hook_silent_when_backend_down(tmp_path):
    result, urls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp"},
        capsule_fail=True,
        startup_fail=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert urls == [
        "http://rekall.test/api/memory/capsule?project=rekall-mcp",
        "http://rekall.test/api/memory/context/startup?project=rekall-mcp&agent=claude-code&limit=8",
    ]


def test_session_start_hook_caps_startup_summary(tmp_path):
    fakebin, calls = _fake_curl(tmp_path)
    curl = fakebin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url="${@: -1}"
printf '%s\\n' "$url" >> "$FAKE_CURL_CALLS"
if [[ "$url" == *"/api/memory/capsule"* ]]; then
  exit 22
fi
python3 - <<'PY'
import json
print(json.dumps({"startup_summary": "A" * 12000}))
PY
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "FAKE_CURL_CALLS": str(calls),
            "REKALL_API_URL": "http://rekall.test",
        }
    )

    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"cwd": "/workspaces/rekall-mcp"}),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    packet = json.loads(result.stdout)
    additional_context = packet["hookSpecificOutput"]["additionalContext"]
    assert len(additional_context) < 3800
    assert "A" * 3500 in additional_context
    assert "A" * 3600 not in additional_context


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

    result, curls = _run_install(home, "--hooks-only")

    assert result.returncode == 0, result.stderr + result.stdout
    assert any("localhost:8000/health" in call for call in curls)
    assert "backend not reachable" in result.stdout
    assert (home / ".claude" / "hooks" / "rekall-restore.sh").exists()
    assert (home / ".claude" / "hooks" / "rekall-observe.sh").exists()
    assert (home / ".claude" / "hooks" / "rekall-session-end.sh").exists()
    assert (home / ".claude" / "hooks" / "memory-prune.sh").exists()
    assert not (home / ".claude" / "hooks" / "session-start-memory.sh").exists()
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = _settings_commands(settings, "SessionStart")
    assert any("memory-prune.sh" in c for c in commands)
    assert not any("session-start-memory.sh" in c for c in commands)
    session_end_hooks = [
        hook
        for entry in settings["hooks"]["SessionEnd"]
        for hook in entry.get("hooks", [])
        if hook["command"].endswith("rekall-session-end.sh")
    ]
    assert session_end_hooks == [
        {
            "type": "command",
            "command": str(home / ".claude" / "hooks" / "rekall-session-end.sh"),
            "timeout": 3,
        }
    ]


def test_installer_removes_only_obsolete_rekall_entries_and_is_idempotent(tmp_path):
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    foreign_precompact = "/opt/team/hooks/preserve-precompact.sh"
    foreign_posttool = "/opt/team/hooks/preserve-posttool.sh"
    settings_path = claude_home / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "model": "keep-this-model",
                "permissions": {"defaultMode": "auto"},
                "hooks": {
                    "PreCompact": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(claude_home / "hooks" / "rekall-precompact.sh"),
                                },
                                {"type": "command", "command": foreign_precompact},
                            ]
                        }
                    ],
                    "PostCompact": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(claude_home / "hooks" / "rekall-postcompact.sh"),
                                }
                            ]
                        }
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(
                                        claude_home / "hooks" / "rekall-commit-nudge.sh"
                                    ),
                                },
                                {"type": "command", "command": foreign_posttool},
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    first, _ = _run_install(home, "--hooks-only")
    second, _ = _run_install(home, "--hooks-only")

    assert first.returncode == 0, first.stderr + first.stdout
    assert second.returncode == 0, second.stderr + second.stdout
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["model"] == "keep-this-model"
    assert settings["permissions"] == {"defaultMode": "auto"}
    all_commands = [
        command for event in settings["hooks"] for command in _settings_commands(settings, event)
    ]
    assert foreign_precompact in all_commands
    assert foreign_posttool in all_commands
    assert not any(
        command.endswith(
            ("rekall-precompact.sh", "rekall-postcompact.sh", "rekall-commit-nudge.sh")
        )
        for command in all_commands
    )
    assert "PostCompact" not in settings["hooks"]
    session_end = [
        hook
        for entry in settings["hooks"]["SessionEnd"]
        for hook in entry.get("hooks", [])
        if hook["command"].endswith("rekall-session-end.sh")
    ]
    assert len(session_end) == 1
    assert session_end[0]["timeout"] == 3


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

    result, curls = _run_install(home, "--hooks-only", "--install-startup-capsule")

    assert result.returncode == 0, result.stderr + result.stdout
    assert any("localhost:8000/health" in call for call in curls)
    assert "backend not reachable" in result.stdout
    installed = hooks / "session-start-memory.sh"
    assert installed.exists()
    assert os.access(installed, os.X_OK)
    assert "api/memory/capsule" in installed.read_text(encoding="utf-8")
    backups = list(
        (home / ".claude" / "backups").glob("rekall-live-config-*/hooks/session-start-memory.sh")
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


def test_hook_capsule_path_does_not_render_entities(tmp_path):
    """Hook must suppress Entities: from capsule output even when the JSON contains entities."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    calls = tmp_path / "curl-calls.log"
    curl = fakebin / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
url="${{@: -1}}"
printf '%s\\n' "$url" >> "{calls}"
if [[ "$url" == *"/api/memory/capsule"* ]]; then
  printf '%s' '{{"project":"rekall-mcp","entities":["Longhorn","k3s"],"danger_zones":[{{"date":"2026-07-03","content":"Back up live files before touching Claude hooks."}}]}}'
  exit 0
fi
exit 99
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "FAKE_CURL_CALLS": str(calls),
            "REKALL_API_URL": "http://rekall.test",
        }
    )

    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"cwd": "/workspaces/rekall-mcp"}),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    packet = json.loads(result.stdout)
    additional_context = packet["hookSpecificOutput"]["additionalContext"]
    assert "Entities:" not in additional_context


def test_session_start_hook_skips_subagents(tmp_path):
    result, calls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp", "session_id": "s1", "agent_id": "a1b2c3"},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert calls == []


def test_session_start_hook_treats_empty_agent_id_as_main_session(tmp_path):
    result, calls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp", "session_id": "s1", "agent_id": ""},
    )
    assert result.returncode == 0
    assert "REKALL STARTUP" in result.stdout
    assert any("/api/memory/capsule" in c for c in calls)


def test_session_start_hook_prints_memory_ids(tmp_path):
    result, _ = _run_hook(tmp_path, {"cwd": "/workspaces/rekall-mcp", "session_id": "s1"})
    assert "[2026-07-03_learning_ab12cd34]" in result.stdout


def test_installer_wires_provenance_hook(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    result, _ = _run_install(home, "--hooks-only")

    assert result.returncode == 0, result.stderr + result.stdout
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    match = [e for e in entries if e.get("matcher") == "mcp__memory__.*|mcp__rekall__.*"]
    assert match, entries
    assert any("rekall-provenance.sh" in h["command"] for h in match[0]["hooks"])
    assert (home / ".claude" / "hooks" / "rekall-provenance.sh").exists()

    result, _ = _run_install(home, "--hooks-only")
    assert result.returncode == 0, result.stderr + result.stdout
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert sum("rekall-provenance.sh" in c for c in commands) == 1, commands


PROV_MATCHER = "mcp__memory__.*|mcp__rekall__.*"


def test_installer_profile_flag_patches_second_profile_only(tmp_path):
    home = tmp_path / "home"
    work = home / ".claude-work"
    work.mkdir(parents=True)
    foreign = "/opt/foreign/hook.sh"
    (work / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": foreign}]}]}}),
        encoding="utf-8",
    )

    result, _ = _run_install(home, "--hooks-only", "--profile", str(work))

    assert result.returncode == 0, result.stderr + result.stdout
    settings = json.loads((work / "settings.json").read_text(encoding="utf-8"))
    match = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == PROV_MATCHER]
    assert match
    assert match[0]["hooks"][0]["command"] == str(
        home / ".claude" / "hooks" / "rekall-provenance.sh"
    )
    assert foreign in _settings_commands(settings, "Stop")
    assert not (work / "hooks").exists()
    assert (home / ".claude" / "hooks" / "rekall-provenance.sh").exists()


def test_installer_profile_rerun_is_byte_identical(tmp_path):
    home = tmp_path / "home"
    work = home / ".claude-work"
    work.mkdir(parents=True)
    paths = [home / ".claude" / "settings.json", work / "settings.json"]

    first, _ = _run_install(home, "--hooks-only", "--profile", str(work))
    before = [p.read_bytes() for p in paths]
    second, _ = _run_install(home, "--hooks-only", "--profile", str(work))

    assert first.returncode == 0 and second.returncode == 0, second.stderr + second.stdout
    assert [p.read_bytes() for p in paths] == before


def test_installer_profile_missing_dir_is_skipped(tmp_path):
    home = tmp_path / "home"
    missing = home / ".claude-nope"

    result, _ = _run_install(home, "--hooks-only", "--profile", str(missing))

    assert result.returncode == 0, result.stderr + result.stdout
    assert f"skipping profile {missing}" in result.stdout
    assert not missing.exists()


def test_installer_honors_claude_config_dir_env(tmp_path):
    home = tmp_path / "home"
    work = home / ".claude-work"
    work.mkdir(parents=True)

    result, _ = _run_install(home, "--hooks-only", env_extra={"CLAUDE_CONFIG_DIR": f"{work}/"})

    assert result.returncode == 0, result.stderr + result.stdout
    settings = json.loads((work / "settings.json").read_text(encoding="utf-8"))
    assert any(e.get("matcher") == PROV_MATCHER for e in settings["hooks"]["PreToolUse"])


def test_installer_refreshes_existing_startup_hook_without_wiring(tmp_path):
    home = tmp_path / "home"
    hooks = home / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    stale = hooks / "session-start-memory.sh"
    stale.write_text("#!/usr/bin/env bash\n# stale\n", encoding="utf-8")

    result, _ = _run_install(home, "--hooks-only")

    assert result.returncode == 0, result.stderr + result.stdout
    assert (
        stale.read_bytes() == (REPO / "claude" / "hooks" / "session-start-memory.sh").read_bytes()
    )
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not any(
        "session-start-memory.sh" in c for c in _settings_commands(settings, "SessionStart")
    )


def test_detected_profile_with_settings_is_patched(tmp_path):
    home = tmp_path / "home"
    work = tmp_path / "work-profile"
    work.mkdir()
    (work / "settings.json").write_text("{}", encoding="utf-8")

    result, _ = _run_install(home, "--hooks-only", detect_dirs=[str(work)])

    assert result.returncode == 0, result.stderr + result.stdout
    settings = json.loads((work / "settings.json").read_text(encoding="utf-8"))
    assert any(e.get("matcher") == PROV_MATCHER for e in settings["hooks"]["PreToolUse"])


def test_detected_unwritable_profile_is_skipped_not_fatal(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    home = tmp_path / "home"
    ro = tmp_path / "ro-profile"
    ro.mkdir()
    (ro / "settings.json").write_text("{}", encoding="utf-8")
    ro.chmod(0o555)
    (ro / "settings.json").chmod(0o444)
    try:
        result, _ = _run_install(home, "--hooks-only", detect_dirs=[str(ro)])
    finally:
        ro.chmod(0o755)

    assert result.returncode == 0, result.stderr + result.stdout
    assert f"skipping detected profile {ro}" in result.stdout
    assert (ro / "settings.json").read_text(encoding="utf-8") == "{}"
    home_settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "PreToolUse" in home_settings["hooks"]


def test_detected_profile_without_settings_or_with_bad_json_is_skipped(tmp_path):
    home = tmp_path / "home"
    bare = tmp_path / "bare"
    bad = tmp_path / "bad"
    bare.mkdir()
    bad.mkdir()
    (bad / "settings.json").write_text("{not json", encoding="utf-8")

    result, _ = _run_install(home, "--hooks-only", detect_dirs=[str(bare), str(bad)])

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (bare / "settings.json").exists()
    assert (bad / "settings.json").read_text(encoding="utf-8") == "{not json"
    assert f"skipping detected profile {bare}" in result.stdout
    assert f"skipping detected profile {bad}" in result.stdout


def test_detected_relative_profile_is_dropped(tmp_path):
    home = tmp_path / "home"
    rel = REPO / "relative-detected-profile"

    result, _ = _run_install(home, "--hooks-only", detect_dirs=["relative-detected-profile"])

    assert result.returncode == 0, result.stderr + result.stdout
    assert not rel.exists()
    assert "ignoring detected profile relative-detected-profile" in result.stdout


def test_verify_ignores_foreign_rekall_named_paths_and_flags_non_object_entries(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Notification": [
                        {"hooks": [{"type": "command", "command": "/x/rekall-mcp/hook.sh"}]}
                    ],
                    "Weird": ["not-an-object"],
                }
            }
        ),
        encoding="utf-8",
    )

    result, _ = _run_install(home, "--hooks-only")

    assert result.returncode == 0, result.stderr + result.stdout
    line = next(ln for ln in result.stdout.splitlines() if "wired events" in ln)
    assert "Notification" not in line
    assert "UserPromptSubmit" in line
    assert "non-object hook entr" in result.stdout
