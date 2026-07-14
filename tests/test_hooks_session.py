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
    claude.write_text(
        f"#!/usr/bin/env bash\ncat >/dev/null\nprintf '%s\\n' '{judge_json}'\n",
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
