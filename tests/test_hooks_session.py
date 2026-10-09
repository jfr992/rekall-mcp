"""Session attribution + evidence_class at the hook level (U1 Tasks 2-3).

Pattern mirrors test_observe_hook_summary.py: fake curl/git/claude binaries on
PATH log calls and -d bodies; fixture stdin payloads drive the hooks. Never
touches prod — tmp marker dirs, fake network.
"""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESTORE_HOOK = REPO / "claude" / "hooks" / "rekall-restore.sh"
OBSERVE_HOOK = REPO / "claude" / "hooks" / "rekall-observe.sh"
SESSION_START_HOOK = REPO / "claude" / "hooks" / "session-start-memory.sh"


def _make_fake_curl(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (fakebin_dir, calls_log, bodies_log) and write fake curl."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    calls = tmp_path / "curl-calls.log"
    bodies = tmp_path / "curl-bodies.log"

    curl = fakebin / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{calls}"
prev=""
for arg in "$@"; do
    if [[ "$prev" == "-d" ]]; then
        printf '%s\\n' "$arg" >> "{bodies}"
    fi
    prev="$arg"
done
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return fakebin, calls, bodies


def _run_restore(tmp_path: Path, stdin_payload: dict | None, env_session: str | None):
    fakebin, calls, _ = _make_fake_curl(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "REKALL_API_URL": "http://rekall.test",
            "REKALL_AUTOSAVE": "1",
            "REKALL_MARKER_DIR": str(tmp_path),
        }
    )
    env.pop("CLAUDE_SESSION_ID", None)
    if env_session is not None:
        env["CLAUDE_SESSION_ID"] = env_session
    return subprocess.run(
        ["bash", str(RESTORE_HOOK)],
        input=json.dumps(stdin_payload) if stdin_payload is not None else "",
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
        check=False,
    )


def test_restore_marker_named_from_stdin_session_id(tmp_path):
    """The marker must match the observe hook's payload-session lookup, not the
    (usually absent) CLAUDE_SESSION_ID env var — otherwise session_summary
    silently never fires."""
    result = _run_restore(
        tmp_path,
        {"session_id": "stdin-sess-1", "cwd": str(tmp_path)},
        env_session="env-sess-should-lose",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "rekall-restored-stdin-sess-1").exists(), sorted(
        p.name for p in tmp_path.iterdir()
    )
    assert not (tmp_path / "rekall-restored-env-sess-should-lose").exists()


def test_restore_marker_falls_back_to_env_when_stdin_has_no_session(tmp_path):
    result = _run_restore(tmp_path, {"cwd": str(tmp_path)}, env_session="env-sess-2")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "rekall-restored-env-sess-2").exists()


def test_restore_surfaces_embedder_degradation(tmp_path):
    """#57: a broken embedder must be loud in the status line, not silent."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    health = {
        "status": "degraded",
        "vectors": {"sampled": 5, "zero_vectors": 0},
        "embedder": {"error": "ImportError: sentence-transformers required"},
    }
    stats = {"total_memories": 0, "knowledge_graph": {"nodes": 0, "edges": 0}}
    (tmp_path / "health.json").write_text(json.dumps(health), encoding="utf-8")
    (tmp_path / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    curl = fakebin / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
for arg in "$@"; do
    case "$arg" in
        */health) cat "{tmp_path}/health.json"; exit 0 ;;
        */api/memory/stats) cat "{tmp_path}/stats.json"; exit 0 ;;
    esac
done
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "REKALL_API_URL": "http://rekall.test",
            "REKALL_AUTOSAVE": "1",
            "REKALL_MARKER_DIR": str(tmp_path),
        }
    )
    result = subprocess.run(
        ["bash", str(RESTORE_HOOK)],
        input=json.dumps({"session_id": "degraded-sess", "cwd": str(tmp_path)}),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "embedder DOWN" in result.stdout
    assert "ImportError: sentence-transformers required" in result.stdout


# ---------------------------------------------------------------------------
# rekall-observe.sh — judge path (session_id + evidence_class in observe POST)
# ---------------------------------------------------------------------------

OBSERVE_SESSION = "observe-sess-9"


def _judge_transcript(tmp_path: Path) -> Path:
    """Transcript whose last user message trips the keyword gate (Signal 2)."""
    entries = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Please remember that we always deploy on Fridays only.",
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Noted — Friday-only deploys, saved."}],
            },
        },
    ]
    f = tmp_path / f"{OBSERVE_SESSION}.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    return f


def _run_observe_judge(
    tmp_path: Path,
    *,
    judge_json: str,
    git_commits: int = 0,
) -> tuple[subprocess.CompletedProcess, list[str], list[dict]]:
    """Run rekall-observe.sh through the Haiku-judge path with fakes."""
    fakebin, calls, bodies = _make_fake_curl(tmp_path)

    git = fakebin / "git"
    if git_commits > 0:
        lines = "\\n".join(f"c{i} commit {i}" for i in range(git_commits))
        git.write_text(f'#!/usr/bin/env bash\nprintf "{lines}\\n"\nexit 0\n', encoding="utf-8")
    else:
        git.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    git.chmod(0o755)

    claude = fakebin / "claude"
    claude_args = tmp_path / "claude-args.log"
    claude.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_CLAUDE_ARGS"
cat >/dev/null
printf '%s\\n' '{judge_json}'
""",
        encoding="utf-8",
    )
    claude.chmod(0o755)

    transcript = _judge_transcript(tmp_path)
    # cwd must contain .git for Signal 1's repo check
    (tmp_path / ".git").mkdir(exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "REKALL_API_URL": "http://rekall.test",
            "REKALL_AUTOSAVE": "1",
            "REKALL_MARKER_DIR": str(tmp_path),
            "REKALL_OBSERVE_LOG": str(tmp_path / "observe.log"),
            "REKALL_LAST_FIRE_FILE": str(tmp_path / "last-fire"),
            "FAKE_CLAUDE_ARGS": str(claude_args),
        }
    )
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("REKALL_JUDGE_INFLIGHT", None)

    payload = {
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
        "stop_hook_active": False,
        "session_id": OBSERVE_SESSION,
    }
    result = subprocess.run(
        ["bash", str(OBSERVE_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )

    url_lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    parsed: list[dict] = []
    if bodies.exists():
        for line in bodies.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed.append(json.loads(line))
    return result, url_lines, parsed


def _observe_bodies(url_lines: list[str], bodies: list[dict]) -> list[dict]:
    assert any("/api/memory/observe" in u for u in url_lines), url_lines
    return [b for b in bodies if "summary" in b]


def test_observe_post_carries_session_id(tmp_path):
    judge = '{"observe": true, "type": "learning", "content": "Deploys are Friday-only."}'
    result, url_lines, bodies = _run_observe_judge(tmp_path, judge_json=judge)

    assert result.returncode == 0, result.stderr
    observe_bodies = _observe_bodies(url_lines, bodies)
    assert len(observe_bodies) == 1, bodies
    assert observe_bodies[0]["session_id"] == OBSERVE_SESSION


def test_observe_judge_runs_isolated_with_low_effort(tmp_path):
    judge = '{"observe": false}'

    result, _, _ = _run_observe_judge(tmp_path, judge_json=judge, git_commits=1)

    assert result.returncode == 0, result.stderr
    argv = (tmp_path / "claude-args.log").read_text(encoding="utf-8")
    assert "--safe-mode" in argv
    assert "--effort low" in argv
    assert "--tools " in argv
    assert "--no-session-persistence" in argv


def test_observe_post_carries_judge_evidence_class(tmp_path):
    """No new commits (Signal 1 quiet) -> the judge's own class is kept."""
    judge = (
        '{"observe": true, "type": "preference", '
        '"content": "User prefers Friday-only deploys.", '
        '"evidence_class": "explicit_user"}'
    )
    result, url_lines, bodies = _run_observe_judge(tmp_path, judge_json=judge, git_commits=0)

    assert result.returncode == 0, result.stderr
    observe_bodies = _observe_bodies(url_lines, bodies)
    assert len(observe_bodies) == 1, bodies
    assert observe_bodies[0]["evidence_class"] == "explicit_user"


def test_observe_shell_override_confirmed_artifact_beats_judge(tmp_path):
    """Gate Signal 1 fired (new commits) -> evidence_class=confirmed_artifact
    regardless of what the judge claimed. Objective artifact beats judgment."""
    judge = (
        '{"observe": true, "type": "learning", '
        '"content": "Shipped the session attribution feature.", '
        '"evidence_class": "inferred"}'
    )
    result, url_lines, bodies = _run_observe_judge(tmp_path, judge_json=judge, git_commits=3)

    assert result.returncode == 0, result.stderr
    observe_bodies = _observe_bodies(url_lines, bodies)
    assert len(observe_bodies) == 1, bodies
    assert observe_bodies[0]["evidence_class"] == "confirmed_artifact"


# ---------------------------------------------------------------------------
# session-start-memory.sh — session_id on capsule GET and startup fallback GET
# ---------------------------------------------------------------------------


def _run_session_start(
    tmp_path: Path, stdin_payload: dict
) -> tuple[subprocess.CompletedProcess, list[str]]:
    fakebin, calls, _ = _make_fake_curl(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "REKALL_API_URL": "http://rekall.test",
            "REKALL_AUTOSAVE": "1",
        }
    )
    env.pop("CLAUDE_PROJECT_NAME", None)
    result = subprocess.run(
        ["bash", str(SESSION_START_HOOK)],
        input=json.dumps(stdin_payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
        check=False,
    )
    url_lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, url_lines


def test_session_start_appends_session_id_to_both_gets(tmp_path):
    """Empty capsule response forces the startup fallback, so one run pins
    the session_id param on BOTH GETs."""
    result, url_lines = _run_session_start(
        tmp_path, {"cwd": str(tmp_path), "session_id": "start-sess-5"}
    )
    assert result.returncode == 0, result.stderr

    capsule_gets = [u for u in url_lines if "/api/memory/capsule?" in u]
    startup_gets = [u for u in url_lines if "/api/memory/context/startup?" in u]
    assert len(capsule_gets) == 1, url_lines
    assert len(startup_gets) == 1, url_lines
    assert "session_id=start-sess-5" in capsule_gets[0]
    assert "session_id=start-sess-5" in startup_gets[0]


def test_session_start_without_session_id_sends_no_param(tmp_path):
    """Skew pin: payloads without session_id must not fabricate one."""
    result, url_lines = _run_session_start(tmp_path, {"cwd": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    gets = [u for u in url_lines if "/api/memory/" in u]
    assert gets, url_lines
    assert all("session_id=" not in u for u in gets), url_lines


SESSION_END_HOOK = REPO / "claude" / "hooks" / "rekall-session-end.sh"
MID_A = "2026-10-09_fact_aaaa1111"
MID_B = "2026-10-09_decision_bbbb2222"
MID_C = "2026-10-09_learning_cccc3333"


def _transcript_lines():
    recall_use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "mcp__memory__recall_memories",
                    "input": {"query": "x"},
                }
            ]
        },
    }
    recall_result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": [
                        {
                            "type": "text",
                            "text": f"- port 8000 (2026-10-09) [{MID_A}]\n- other (2026-10-09) [{MID_B}]",
                        }
                    ],
                }
            ]
        },
    }
    capsule = {
        "type": "attachment",
        "attachment": {
            "type": "hook_additional_context",
            "content": [
                f"== REKALL STARTUP (p) ==\n- [2026-10-09] use uv [{MID_C}]\n== END REKALL STARTUP =="
            ],
        },
    }
    assistant_cites_a = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": f"Per memory {MID_A}, port is 8000."}]},
    }
    bash_use = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "echo hi"}}
            ]
        },
    }
    # MID_B appears only inside a later tool_result: exposure, not a reference.
    bash_result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": [{"type": "text", "text": f"log mentions {MID_B}"}],
                }
            ]
        },
    }
    return [capsule, recall_use, recall_result, assistant_cites_a, bash_use, bash_result]


def _run_session_end(tmp_path: Path, lines: list[dict], tail_bytes: str | None = None):
    fakebin, calls, bodies = _make_fake_curl(tmp_path)
    transcript = tmp_path / "sess-9.jsonl"
    transcript.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    (tmp_path / "rekall-restored-sess-9").write_text("")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "REKALL_API_URL": "http://rekall.test",
            "REKALL_AUTOSAVE": "1",
            "REKALL_MARKER_DIR": str(tmp_path),
        }
    )
    if tail_bytes:
        env["REKALL_TRANSCRIPT_TAIL_BYTES"] = tail_bytes
    payload = {
        "hook_event_name": "SessionEnd",
        "session_id": "sess-9",
        "cwd": str(tmp_path / "proj"),
        "transcript_path": str(transcript),
    }
    r = subprocess.run(
        ["bash", str(SESSION_END_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
        check=False,
    )
    body = json.loads(bodies.read_text().strip().splitlines()[-1]) if bodies.exists() else None
    return r, body


def test_session_end_reports_delivered_by_surface_and_referenced(tmp_path):
    r, body = _run_session_end(tmp_path, _transcript_lines())
    assert r.returncode == 0
    assert body["client"] == "claude-code"
    assert body["delivered"] == {"explicit": [MID_A, MID_B], "capsule": [MID_C], "reflex": []}
    assert body["referenced"] == [MID_A]
    assert body["recalled_ids"] == sorted([MID_A, MID_B, MID_C])
    assert body["coverage"] == {"transcript_tail_bytes": 1048576, "truncated": False}


def test_session_end_marks_truncated_tail(tmp_path):
    lines = _transcript_lines()
    pad = {"type": "progress", "pad": "x" * 6000}
    r, body = _run_session_end(tmp_path, [pad] + lines, tail_bytes="4096")
    assert r.returncode == 0
    assert body["coverage"]["truncated"] is True
    assert body["coverage"]["transcript_tail_bytes"] == 4096


def _tool_use(tool_id, name, tool_input=None):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input or {}}
            ]
        },
    }


def _tool_result(tool_id, text="ok"):
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": [{"type": "text", "text": text}],
                }
            ]
        },
    }


def _capsule(mid):
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_additional_context",
            "content": [f"== REKALL STARTUP (p) ==\n- note [{mid}]\n== END REKALL STARTUP =="],
        },
    }


def test_session_end_capsule_does_not_start_edit_window(tmp_path):
    cites_capsule = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": f"Following {MID_C}."}]},
    }
    lines = [
        _capsule(MID_C),
        cites_capsule,
        _tool_use("e1", "Edit"),
        _tool_result("e1"),
        _tool_use("r1", "mcp__memory__recall_memories", {"query": "x"}),
        _tool_result("r1", f"- a [{MID_A}]"),
        _tool_use("e2", "Edit"),
        _tool_result("e2"),
    ]
    r, body = _run_session_end(tmp_path, lines)
    assert r.returncode == 0
    assert body["edits_after_recall"] == 1
    assert MID_C in body["referenced"]


def test_session_end_capsule_only_session_has_no_outcome_credit(tmp_path):
    lines = [_capsule(MID_C), _tool_use("e1", "Edit"), _tool_result("e1")]
    r, body = _run_session_end(tmp_path, lines)
    assert body["edits_after_recall"] == 0
    assert body["test_passes_after_recall"] == 0


def test_session_end_survives_non_dict_hook_stdout(tmp_path):
    def success(stdout):
        return {"type": "attachment", "attachment": {"type": "hook_success", "stdout": stdout}}

    lines = [success("123"), success("[1,2]"), _capsule(MID_C)]
    r, body = _run_session_end(tmp_path, lines)
    assert r.returncode == 0
    assert body["delivered"]["capsule"] == [MID_C]
