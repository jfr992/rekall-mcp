import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

MERGER = Path(__file__).parents[1] / "codex" / "setup" / "merge_hooks.py"
EXAMPLE = Path(__file__).parents[1] / "codex" / "hooks.example.json"
INSTALLER = Path(__file__).parents[1] / "codex" / "setup" / "install.sh"
ADAPTER = Path(__file__).parents[1] / "codex" / "hooks" / "rekall_hook.py"
SKILL = Path(__file__).parents[1] / "codex" / "skills" / "rekall-memory" / "SKILL.md"


def load_merger():
    spec = importlib.util.spec_from_file_location("merge_hooks", MERGER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_merge(
    tmp_path: Path,
    existing: object,
    adapter: str = "/safe/home/.codex/hooks/rekall_hook.py",
    api_url: str = "http://localhost:8000",
    bearer_token_env_var: str = "",
) -> dict[str, Any]:
    source = tmp_path / "hooks.json"
    source.write_text(json.dumps(existing), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(MERGER),
            "--hooks-file",
            str(source),
            "--adapter",
            adapter,
            "--api-url",
            api_url,
            "--bearer-token-env-var",
            bearer_token_env_var,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return cast(dict[str, Any], json.loads(source.read_text(encoding="utf-8")))


def test_merge_preserves_foreign_hook_and_is_idempotent(tmp_path):
    existing = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "/custom/safety.sh"}]}
            ]
        },
        "foreign": {"keep": True},
    }
    once = run_merge(tmp_path, existing)
    twice = run_merge(tmp_path, once)
    assert once == twice
    assert once["foreign"] == {"keep": True}
    assert any(h["hooks"][0]["command"] == "/custom/safety.sh" for h in once["hooks"]["PreToolUse"])


def test_authenticated_merge_is_idempotent_and_persists_only_variable_name(tmp_path):
    once = run_merge(tmp_path, {}, bearer_token_env_var="REKALL_API_TOKEN")
    twice = run_merge(
        tmp_path,
        once,
        bearer_token_env_var="REKALL_API_TOKEN",
    )

    assert once == twice
    serialized = json.dumps(once)
    assert "REKALL_API_TOKEN_ENV_VAR=REKALL_API_TOKEN" in serialized
    assert all(len(entries) == 1 for entries in once["hooks"].values())


def test_merge_has_exactly_six_canonical_events_and_no_memories(tmp_path):
    output = run_merge(tmp_path, {})
    assert set(output["hooks"]) == {
        "SessionStart",
        "PreToolUse",
        "PreCompact",
        "PostCompact",
        "PostToolUse",
        "SessionEnd",
    }
    assert all(len(entries) == 1 for entries in output["hooks"].values())
    assert "memories" not in json.dumps(output).lower()
    context_events = {"SessionStart", "PreToolUse", "PostToolUse"}
    for event, entries in output["hooks"].items():
        hook = entries[0]["hooks"][0]
        assert event in hook["command"]
        assert "REKALL_API_URL=http://localhost:8000" in hook["command"]
        assert isinstance(hook["timeout"], int)
        if event in context_events:
            assert isinstance(hook["additionalContextLimit"], int)
        else:
            assert "additionalContextLimit" not in hook
    # Official Codex contract: SessionEnd defaults to one second and caps at three.
    assert output["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] <= 3


def test_merge_removes_legacy_but_keeps_mixed_foreign_entry(tmp_path):
    legacy = [
        "rekall-restore.sh",
        "rekall-observe.sh",
        "rekall-reflex.sh",
        "rekall-precompact.sh",
        "rekall-postcompact.sh",
        "rekall-commit-nudge.sh",
        "memory-prune.sh",
        "session-context.sh",
    ]
    existing = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "/x/rekall-observe.sh"},
                        {"type": "command", "command": "/x/foreign.sh"},
                    ],
                }
            ],
            "SessionStart": [
                {"hooks": [{"type": "command", "command": f"/x/{name}"} for name in legacy]}
            ],
        }
    }
    output = run_merge(tmp_path, existing)
    commands = json.dumps(output)
    assert not any(name in commands for name in legacy)
    assert "foreign.sh" in commands
    assert output["hooks"].get("Stop") == [
        {"matcher": "", "hooks": [{"type": "command", "command": "/x/foreign.sh"}]}
    ]


def test_merge_preserves_foreign_rekall_named_command_and_near_match_legacy(tmp_path):
    existing = {
        "hooks": {
            "PostToolUse": [
                {
                    "hooks": [
                        {"type": "command", "command": "/vendor/rekall_hook.py --custom"},
                        {"type": "command", "command": "/vendor/not-rekall-observe.sh"},
                        {"type": "command", "command": "/vendor/rekall-observe.sh"},
                    ]
                }
            ]
        }
    }
    output = run_merge(tmp_path, existing)
    commands = [
        child["command"] for entry in output["hooks"]["PostToolUse"] for child in entry["hooks"]
    ]
    assert "/vendor/rekall_hook.py --custom" in commands
    assert "/vendor/not-rekall-observe.sh" in commands
    assert "/vendor/rekall-observe.sh" not in commands


def test_canonical_example_has_builder_parity_and_quotes_spaces():
    merger = load_merger()
    expected = merger.canonical_entries("/path/to/rekall_hook.py")
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))["hooks"]
    assert example == expected
    spaced = merger.canonical_entries("/safe/home/My Hooks/rekall_hook.py")
    assert (
        "'/safe/home/My Hooks/rekall_hook.py'" in spaced["SessionStart"][0]["hooks"][0]["command"]
    )


def test_merge_replaces_managed_url_without_duplicating_hooks(tmp_path):
    first = run_merge(tmp_path, {}, api_url="http://localhost:8000")
    second = run_merge(tmp_path, first, api_url="https://memory.example.test/mcp")
    serialized = json.dumps(second)
    assert "https://memory.example.test/mcp" in serialized
    assert "http://localhost:8000" not in serialized
    assert all(len(entries) == 1 for entries in second["hooks"].values())


def test_merge_creates_nested_parent_and_retains_mode(tmp_path):
    nested = tmp_path / "nested" / "hooks.json"
    # The destination and its parent are both absent; atomic creation must still work.
    result = subprocess.run(
        [sys.executable, str(MERGER), "--hooks-file", str(nested), "--adapter", "/x.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert nested.exists()


def test_merge_rejects_malformed_root_without_overwriting(tmp_path):
    source = tmp_path / "hooks.json"
    source.write_text("[]", encoding="utf-8")
    before = source.read_bytes()
    result = subprocess.run(
        [sys.executable, str(MERGER), "--hooks-file", str(source), "--adapter", "/x.py"]
    )
    assert result.returncode != 0
    assert source.read_bytes() == before


def test_merge_atomic_replace_preserves_mode(tmp_path):
    source = tmp_path / "hooks.json"
    source.write_text("{}", encoding="utf-8")
    source.chmod(0o640)
    run_merge(tmp_path, {})
    assert stat.S_IMODE(source.stat().st_mode) == 0o640


def test_example_matches_canonical_shape():
    assert EXAMPLE.exists()
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert set(example["hooks"]) == {
        "SessionStart",
        "PreToolUse",
        "PreCompact",
        "PostCompact",
        "PostToolUse",
        "SessionEnd",
    }


def _write_fake_codex(bin_dir: Path) -> None:
    executable = bin_dir / "codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_CODEX_STATE"])
log_path = Path(os.environ["FAKE_CODEX_LOG"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]

if args == ["mcp", "get", "rekall", "--json"]:
    mode = state["mode"]
    if mode in {"missing", "missing_noop"}:
        print("Error: No MCP server named 'rekall' found.", file=sys.stderr)
        raise SystemExit(1)
    if mode == "error":
        print("configuration unreadable", file=sys.stderr)
        raise SystemExit(2)
    if mode == "stdio":
        transport = {"type": "stdio", "command": "uvx", "args": ["rekall-mcp"]}
    else:
        transport = {
            "type": "streamable_http",
            "url": state["url"],
            "bearer_token_env_var": state.get("bearer_token_env_var"),
        }
    print(json.dumps({"name": "rekall", "transport": transport}))
    raise SystemExit(0)

if (
    len(args) in {5, 7}
    and args[:4] == ["mcp", "add", "rekall", "--url"]
    and (len(args) == 5 or args[5] == "--bearer-token-env-var")
):
    with log_path.open("a") as stream:
        stream.write(json.dumps(args) + "\\n")
    if state["mode"] != "missing_noop":
        state.update(
            {
                "mode": "http",
                "url": args[4],
                "bearer_token_env_var": args[6] if len(args) == 7 else None,
            }
        )
        state_path.write_text(json.dumps(state))
    raise SystemExit(0)

if args == ["mcp", "remove", "rekall"]:
    with log_path.open("a") as stream:
        stream.write(json.dumps(args) + "\\n")
    state.update({"mode": "missing"})
    state_path.write_text(json.dumps(state))
    raise SystemExit(0)

print("unexpected argv: " + repr(args), file=sys.stderr)
raise SystemExit(64)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def _run_install(
    tmp_path: Path,
    *,
    mode: str = "missing",
    configured_url: str = "http://localhost:8000",
    configured_bearer: str | None = None,
    args: tuple[str, ...] = (),
    codex_home_name: str = "Codex Home",
    with_codex: bool = True,
    poison_stat: bool = False,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "fake bin"
    fake_bin.mkdir()
    if with_codex:
        _write_fake_codex(fake_bin)
    if poison_stat:
        fake_stat = fake_bin / "stat"
        fake_stat.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        fake_stat.chmod(0o755)
    state = tmp_path / "mcp-state.json"
    state.write_text(
        json.dumps(
            {
                "mode": mode,
                "url": configured_url,
                "bearer_token_env_var": configured_bearer,
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "mcp-argv.jsonl"
    log.write_text("", encoding="utf-8")
    codex_home = tmp_path / codex_home_name
    env = {
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(codex_home),
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "FAKE_CODEX_STATE": str(state),
        "FAKE_CODEX_LOG": str(log),
    }
    env.update(extra_env or {})
    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), *args],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    return result, codex_home, log


def test_install_preserves_hooks_mode_without_platform_specific_stat(tmp_path):
    codex_home = tmp_path / "Codex Home"
    codex_home.mkdir(parents=True)
    hooks_file = codex_home / "hooks.json"
    hooks_file.write_text("{}", encoding="utf-8")
    hooks_file.chmod(0o640)

    result, _, _ = _run_install(tmp_path, poison_stat=True)

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(hooks_file.stat().st_mode) == 0o640


def test_install_clean_and_semantically_idempotent(tmp_path):
    result, codex_home, log = _run_install(tmp_path)
    assert result.returncode == 0, result.stderr
    for line in (
        "Rekall Codex integration installed",
        "Hooks:         6 canonical entries; existing hooks preserved",
        "Native memory: unchanged",
        "Restart Codex to load the integration",
    ):
        assert line in result.stdout
    assert (codex_home / "hooks" / "rekall_hook.py").read_bytes() == ADAPTER.read_bytes()
    assert (codex_home / "skills" / "rekall-memory" / "SKILL.md").read_bytes() == SKILL.read_bytes()
    hooks_file = codex_home / "hooks.json"
    first = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert len(first["hooks"]) == 6
    assert json.loads(log.read_text().splitlines()[0]) == [
        "mcp",
        "add",
        "rekall",
        "--url",
        "http://localhost:8000",
    ]

    second = subprocess.run(
        ["/bin/bash", str(INSTALLER)],
        cwd=Path(__file__).parents[1],
        env={
            "HOME": str(tmp_path / "home"),
            "CODEX_HOME": str(codex_home),
            "PATH": f"{tmp_path / 'fake bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_CODEX_STATE": str(tmp_path / "mcp-state.json"),
            "FAKE_CODEX_LOG": str(log),
        },
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert json.loads(hooks_file.read_text(encoding="utf-8")) == first
    assert len(log.read_text().splitlines()) == 1


def test_install_preserves_foreign_config_and_backs_up_replacements(tmp_path):
    codex_home = tmp_path / "Codex Home"
    (codex_home / "hooks").mkdir(parents=True)
    (codex_home / "skills" / "rekall-memory").mkdir(parents=True)
    original_hooks = {
        "foreign": {"keep": True},
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "/safe.sh"}]}
            ]
        },
    }
    (codex_home / "hooks.json").write_text(json.dumps(original_hooks), encoding="utf-8")
    (codex_home / "hooks" / "rekall_hook.py").write_text("old adapter", encoding="utf-8")
    (codex_home / "skills" / "rekall-memory" / "SKILL.md").write_text("old skill", encoding="utf-8")

    result, _, _ = _run_install(tmp_path, codex_home_name="Codex Home")
    assert result.returncode == 0, result.stderr
    installed = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    assert installed["foreign"] == {"keep": True}
    assert "/safe.sh" in json.dumps(installed)
    backups = list((codex_home / "backups").glob("rekall-*"))
    assert len(backups) == 1
    backup = backups[0]
    assert json.loads((backup / "hooks.json").read_text()) == original_hooks
    assert (backup / "hooks" / "rekall_hook.py").read_text() == "old adapter"
    assert (backup / "skills" / "rekall-memory" / "SKILL.md").read_text() == "old skill"


def test_install_accepts_matching_mcp_without_add(tmp_path):
    result, _, log = _run_install(tmp_path, mode="http")
    assert result.returncode == 0, result.stderr
    assert log.read_text() == ""


def test_install_registers_bearer_env_name_without_persisting_token(tmp_path):
    result, codex_home, log = _run_install(
        tmp_path,
        args=("--bearer-token-env-var", "REKALL_API_TOKEN"),
        extra_env={"REKALL_API_TOKEN": "test-secret-never-persist"},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text().splitlines()[0]) == [
        "mcp",
        "add",
        "rekall",
        "--url",
        "http://localhost:8000",
        "--bearer-token-env-var",
        "REKALL_API_TOKEN",
    ]
    installed = "\n".join(
        (
            result.stdout,
            result.stderr,
            (codex_home / "hooks.json").read_text(encoding="utf-8"),
        )
    )
    assert "test-secret-never-persist" not in installed
    assert "REKALL_API_TOKEN_ENV_VAR=REKALL_API_TOKEN" in installed


def test_install_accepts_matching_bearer_and_rejects_missing_or_invalid_name(tmp_path):
    matching, _, matching_log = _run_install(
        tmp_path / "matching",
        mode="http",
        configured_bearer="REKALL_API_TOKEN",
        args=("--bearer-token-env-var", "REKALL_API_TOKEN"),
    )
    assert matching.returncode == 0, matching.stderr
    assert matching_log.read_text() == ""

    missing, missing_home, _ = _run_install(
        tmp_path / "missing",
        mode="http",
        args=("--bearer-token-env-var", "REKALL_API_TOKEN"),
    )
    assert missing.returncode != 0
    assert not missing_home.exists()

    invalid, invalid_home, _ = _run_install(
        tmp_path / "invalid",
        args=("--bearer-token-env-var", "BAD-NAME"),
    )
    assert invalid.returncode != 0
    assert not invalid_home.exists()


def test_install_refuses_mcp_conflict_before_any_mutation(tmp_path):
    for mode, url in (("http", "http://localhost:9999"), ("stdio", ""), ("error", "")):
        case = tmp_path / mode
        case.mkdir()
        result, codex_home, _ = _run_install(case, mode=mode, configured_url=url)
        assert result.returncode != 0
        assert not codex_home.exists()


def test_install_remote_url_requires_explicit_flag_and_rejects_tokens(tmp_path):
    rejected, codex_home, _ = _run_install(
        tmp_path / "rejected", args=("--mcp-url", "https://memory.example.test/mcp")
    )
    assert rejected.returncode != 0
    assert not codex_home.exists()

    ambiguous, ambiguous_home, _ = _run_install(
        tmp_path / "ambiguous",
        args=("--mcp-url", "https://memory.example.test/mcp", "--allow-remote-mcp"),
    )
    assert ambiguous.returncode != 0
    assert not ambiguous_home.exists()

    accepted, accepted_home, log = _run_install(
        tmp_path / "accepted",
        args=(
            "--mcp-url",
            "https://memory.example.test/mcp",
            "--api-url",
            "https://memory.example.test",
            "--allow-remote-mcp",
        ),
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(log.read_text().splitlines()[0])[-1] == "https://memory.example.test/mcp"
    installed_hooks = (accepted_home / "hooks.json").read_text(encoding="utf-8")
    assert "REKALL_API_URL=https://memory.example.test" in installed_hooks
    assert "REKALL_API_URL=https://memory.example.test/mcp" not in installed_hooks

    token_url = "http://user:secret@localhost:8000?token=secret"
    token, codex_home, _ = _run_install(
        tmp_path / "token", args=("--mcp-url", token_url, "--allow-remote-mcp")
    )
    assert token.returncode != 0
    assert "secret" not in token.stdout + token.stderr
    assert not codex_home.exists()


def test_cli_mcp_url_does_not_inherit_stale_api_environment(tmp_path):
    result, codex_home, log = _run_install(
        tmp_path,
        args=("--mcp-url", "http://localhost:8123"),
        extra_env={"REKALL_API_URL": "http://localhost:9999/mcp"},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text().splitlines()[0])[-1] == "http://localhost:8123"
    installed_hooks = (codex_home / "hooks.json").read_text(encoding="utf-8")
    assert "REKALL_API_URL=http://localhost:8123" in installed_hooks
    assert "localhost:9999" not in installed_hooks


def test_install_rolls_back_files_and_mcp_after_mid_install_failure(tmp_path):
    codex_home = tmp_path / "Codex Home"
    (codex_home / "hooks").mkdir(parents=True)
    original_hooks = {"foreign": {"keep": True}}
    hooks_file = codex_home / "hooks.json"
    hooks_file.write_text(json.dumps(original_hooks), encoding="utf-8")
    adapter = codex_home / "hooks" / "rekall_hook.py"
    adapter.write_text("old adapter", encoding="utf-8")
    # A file where the installer needs a directory forces a failure after the
    # adapter replacement, proving rollback rather than merely early exit.
    skill_blocker = codex_home / "skills" / "rekall-memory"
    skill_blocker.parent.mkdir(parents=True)
    skill_blocker.write_text("foreign blocker", encoding="utf-8")

    result, _, log = _run_install(tmp_path, codex_home_name="Codex Home")

    assert result.returncode != 0
    assert json.loads(hooks_file.read_text(encoding="utf-8")) == original_hooks
    assert adapter.read_text(encoding="utf-8") == "old adapter"
    assert skill_blocker.read_text(encoding="utf-8") == "foreign blocker"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls == [
        ["mcp", "add", "rekall", "--url", "http://localhost:8000"],
        ["mcp", "remove", "rekall"],
    ]
    state = json.loads((tmp_path / "mcp-state.json").read_text(encoding="utf-8"))
    assert state["mode"] == "missing"


def test_install_rolls_back_when_mcp_registration_does_not_verify(tmp_path):
    codex_home = tmp_path / "Codex Home"
    codex_home.mkdir(parents=True)
    original_hooks = {"foreign": {"keep": True}}
    hooks_file = codex_home / "hooks.json"
    hooks_file.write_text(json.dumps(original_hooks), encoding="utf-8")

    result, _, log = _run_install(
        tmp_path,
        mode="missing_noop",
        codex_home_name="Codex Home",
    )

    assert result.returncode != 0
    assert json.loads(hooks_file.read_text(encoding="utf-8")) == original_hooks
    assert not (codex_home / "hooks" / "rekall_hook.py").exists()
    assert not (codex_home / "skills" / "rekall-memory" / "SKILL.md").exists()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls == [
        ["mcp", "add", "rekall", "--url", "http://localhost:8000"],
        ["mcp", "remove", "rekall"],
    ]


def test_install_never_touches_native_memory_and_missing_dependency_fails_early(tmp_path):
    native_case = tmp_path / "native"
    native_case.mkdir()
    codex_home = native_case / "Codex Home"
    memories = codex_home / "memories"
    memories.mkdir(parents=True)
    sentinel = memories / "generated.json"
    sentinel.write_text("native", encoding="utf-8")
    before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
    result, _, _ = _run_install(native_case, mode="http")
    assert result.returncode == 0, result.stderr
    assert (sentinel.read_bytes(), sentinel.stat().st_mtime_ns) == before

    missing_case = tmp_path / "missing"
    missing_case.mkdir()
    failed, absent_home, _ = _run_install(missing_case, with_codex=False)
    assert failed.returncode != 0
    assert not absent_home.exists()


def test_codex_skill_is_mcp_first_and_keeps_native_memory_separate():
    text = SKILL.read_text(encoding="utf-8")
    assert "!curl" not in text
    for tool in ("agent_startup", "recall_memories", "observe", "memory_doctor", "close_loop"):
        assert tool in text
    assert "~/.codex/memories" in text
    assert "do not edit" in text.lower() or "never edit" in text.lower()
    assert 'project="<repo-name>"' in text
    assert "only when broad project continuity" in text.lower()
    assert "current working directory" not in text.lower()


def test_shipped_python_scripts_parse_with_macos_system_python():
    system_python = Path("/usr/bin/python3")
    if not system_python.exists():
        return
    result = subprocess.run(
        [str(system_python), "-m", "py_compile", str(ADAPTER), str(MERGER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
