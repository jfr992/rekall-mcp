"""Tests for the ungated session-summary section of rekall-observe.sh.

Pattern mirrors test_claude_startup_hook.py: fake curl binary captures
POST bodies; synthetic JSONL transcripts drive the Python extractor.
"""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude" / "hooks" / "rekall-observe.sh"

SESSION_ID = "test-sess-abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_curl(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (fakebin_dir, calls_log, bodies_log) and write fake curl."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    calls = tmp_path / "curl-calls.log"
    bodies = tmp_path / "curl-bodies.log"

    curl = fakebin / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
# Log all positional args as one line
printf '%s\\n' "$*" >> "{calls}"

# Extract the body passed via -d
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


def _make_fake_git(fakebin: Path) -> None:
    """Fake git that always exits 1 (no git repo → no commits signal)."""
    git = fakebin / "git"
    git.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    git.chmod(0o755)


def _make_fake_claude(fakebin: Path) -> None:
    """Fake claude that exits 0 with no output (Haiku judge path → no-op)."""
    claude = fakebin / "claude"
    claude.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    claude.chmod(0o755)


def _make_transcript(tmp_path: Path, entries: list) -> Path:
    """Write a JSONL transcript file and return its path."""
    f = tmp_path / f"{SESSION_ID}.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    return f


def _recall_transcript_entries() -> list:
    """
    Synthetic transcript that exercises the full happy path:
    - one mcp__memory__recall_memories call returning two memory IDs
    - two Edit/Write tool_use entries AFTER recall
    - one Bash pytest call with 'passed' in result AFTER recall
    """
    return [
        # 1. Assistant: recall tool_use
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_recall_001",
                        "name": "mcp__memory__recall_memories",
                        "input": {"query": "database decisions"},
                    }
                ],
            },
        },
        # 2. User: tool_result with two memory IDs in content
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_recall_001",
                        "content": (
                            "Found 2 memories:\n"
                            "- 2026-07-01_decision_aaaa1111: Use Qdrant for vector storage\n"
                            "- 2026-07-02_learning_bbbb2222: Always use rglob not glob"
                        ),
                    }
                ],
            },
        },
        # 3. Assistant: Edit tool_use #1
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_edit_001",
                        "name": "Edit",
                        "input": {
                            "file_path": "/src/foo.py",
                            "old_string": "a",
                            "new_string": "b",
                        },
                    }
                ],
            },
        },
        # 4. User: tool_result for Edit #1
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_edit_001",
                        "content": "OK",
                    }
                ],
            },
        },
        # 5. Assistant: Write tool_use #2
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_write_002",
                        "name": "Write",
                        "input": {"file_path": "/src/bar.py", "content": "x=1"},
                    }
                ],
            },
        },
        # 6. User: tool_result for Write #2
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_write_002",
                        "content": "OK",
                    }
                ],
            },
        },
        # 7. Assistant: Bash pytest tool_use
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_bash_001",
                        "name": "Bash",
                        "input": {"command": "pytest tests/ -q"},
                    }
                ],
            },
        },
        # 8. User: tool_result for Bash with "passed" output
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_bash_001",
                        "content": "15 passed, 0 failed in 2.34s",
                    }
                ],
            },
        },
    ]


def _run_hook(
    tmp_path: Path,
    transcript_path: Path,
    *,
    autosave: str = "1",
    create_marker: bool = True,
    extra_env: dict | None = None,
) -> tuple[subprocess.CompletedProcess, list[str], list[dict]]:
    """
    Run rekall-observe.sh with fake curl and return
    (result, curl_arg_lines, parsed_POST_bodies).
    """
    fakebin, calls, bodies = _make_fake_curl(tmp_path)
    _make_fake_git(fakebin)
    _make_fake_claude(fakebin)

    # Marker file: hook uses ${REKALL_MARKER_DIR:-/tmp}/rekall-restored-<sess_id>
    # We set TMPDIR=tmp_path so the hook reads from there.
    if create_marker:
        (tmp_path / f"rekall-restored-{SESSION_ID}").touch()

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env['PATH']}",
            "REKALL_API_URL": "http://rekall.test",
            "REKALL_AUTOSAVE": autosave,
            "CLAUDE_SESSION_ID": SESSION_ID,
            "REKALL_MARKER_DIR": str(tmp_path),
        }
    )
    if extra_env:
        env.update(extra_env)

    payload = {
        "transcript_path": str(transcript_path),
        "cwd": "/workspaces/rekall-mcp",
        "stop_hook_active": False,
        "session_id": SESSION_ID,
    }

    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    url_lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []

    parsed_bodies: list[dict] = []
    if bodies.exists():
        for line in bodies.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed_bodies.append(json.loads(line))
            except json.JSONDecodeError:
                parsed_bodies.append({"_raw": line})

    return result, url_lines, parsed_bodies


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_summary_with_recall_edits_and_test_pass(tmp_path):
    """Happy path: recalled ids + edits + test passes all land in POST body."""
    t = _make_transcript(tmp_path, _recall_transcript_entries())
    result, url_lines, bodies = _run_hook(tmp_path, t)

    assert result.returncode == 0, result.stderr

    # Exactly one POST to /api/memory/events
    events_posts = [u for u in url_lines if "/api/memory/events" in u]
    assert len(events_posts) == 1, f"Expected 1 events POST, got {len(events_posts)}: {url_lines}"

    assert len(bodies) == 1, f"Expected 1 POST body, got {len(bodies)}: {bodies}"
    body = bodies[0]

    assert body["event_type"] == "session_summary"
    assert body["project"] == "rekall-mcp"
    assert body["session_id"] == SESSION_ID

    # Both memory IDs must be present (order-independent)
    assert set(body["recalled_ids"]) == {
        "2026-07-01_decision_aaaa1111",
        "2026-07-02_learning_bbbb2222",
    }

    # Edit #1 + Write #2 = 2 edits after recall
    assert body["edits_after_recall"] == 2, body

    # One Bash pytest with "passed" = 1 test pass after recall
    assert body["test_passes_after_recall"] == 1, body

    # Values must be int, not bool (endpoint rejects bools)
    assert isinstance(body["edits_after_recall"], int)
    assert isinstance(body["test_passes_after_recall"], int)
    assert not isinstance(body["edits_after_recall"], bool)
    assert not isinstance(body["test_passes_after_recall"], bool)


def test_summary_no_recall_skips_post(tmp_path):
    """Transcript with no recall tool calls → natural gate → zero events POSTs."""
    entries = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_edit_only",
                        "name": "Edit",
                        "input": {"file_path": "/x.py", "old_string": "a", "new_string": "b"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_edit_only",
                        "content": "OK",
                    }
                ],
            },
        },
    ]
    t = _make_transcript(tmp_path, entries)
    result, url_lines, bodies = _run_hook(tmp_path, t)

    assert result.returncode == 0, result.stderr
    events_posts = [u for u in url_lines if "/api/memory/events" in u]
    assert events_posts == [], f"Expected no events POST, got {events_posts}"
    assert bodies == []


def test_summary_malformed_transcript_exits_clean(tmp_path):
    """Corrupted JSONL → Python extractor bails gracefully → no POST, exit 0."""
    t = tmp_path / f"{SESSION_ID}.jsonl"
    t.write_text(
        'not json\n{"type": "assistant", bad\n\x00\x01\x02\n',
        encoding="utf-8",
    )
    result, url_lines, bodies = _run_hook(tmp_path, t)

    assert result.returncode == 0, result.stderr
    events_posts = [u for u in url_lines if "/api/memory/events" in u]
    assert events_posts == []
    assert bodies == []


def test_summary_autosave_disabled_skips_all(tmp_path):
    """REKALL_AUTOSAVE=0 kills the hook before the summary section runs."""
    t = _make_transcript(tmp_path, _recall_transcript_entries())
    result, url_lines, bodies = _run_hook(tmp_path, t, autosave="0")

    assert result.returncode == 0, result.stderr
    assert url_lines == [], f"Expected no curl calls, got {url_lines}"
    assert bodies == []


def test_summary_no_marker_skips_post(tmp_path):
    """No restore-hook marker → backend probably down → summary section skipped."""
    t = _make_transcript(tmp_path, _recall_transcript_entries())
    result, url_lines, bodies = _run_hook(tmp_path, t, create_marker=False)

    assert result.returncode == 0, result.stderr
    events_posts = [u for u in url_lines if "/api/memory/events" in u]
    assert events_posts == [], f"Expected no events POST without marker, got {events_posts}"
    assert bodies == []


def test_marker_path_expression_consistent_across_hooks():
    """Both hooks must derive the marker dir from REKALL_MARKER_DIR:-/tmp — consistency guard.

    We cannot write to /tmp in tests, so instead we assert the hook source TEXT
    uses the same env variable with the same default on the rekall-restored- line.
    """
    observe_text = (REPO / "claude" / "hooks" / "rekall-observe.sh").read_text(encoding="utf-8")
    restore_text = (REPO / "claude" / "hooks" / "rekall-restore.sh").read_text(encoding="utf-8")

    observe_marker_lines = [ln for ln in observe_text.splitlines() if "rekall-restored-" in ln]
    restore_marker_lines = [ln for ln in restore_text.splitlines() if "rekall-restored-" in ln]

    assert observe_marker_lines, "rekall-observe.sh has no line referencing rekall-restored-"
    assert restore_marker_lines, "rekall-restore.sh has no line referencing rekall-restored-"

    for line in observe_marker_lines:
        assert "REKALL_MARKER_DIR:-/tmp" in line, (
            f"rekall-observe.sh marker line must use REKALL_MARKER_DIR:-/tmp, got: {line!r}"
        )
    for line in restore_marker_lines:
        assert "REKALL_MARKER_DIR:-/tmp" in line, (
            f"rekall-restore.sh marker line must use REKALL_MARKER_DIR:-/tmp, got: {line!r}"
        )


def test_summary_idless_tool_use_block_does_not_crash(tmp_path):
    """tool_use block without 'id' field must not raise KeyError — skipped gracefully."""
    entries = _recall_transcript_entries()
    # Inject an id-less tool_use block into the first assistant message
    entries.insert(
        0,
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        # deliberately omit "id"
                        "name": "SomeTool",
                        "input": {},
                    }
                ],
            },
        },
    )
    t = _make_transcript(tmp_path, entries)
    result, url_lines, bodies = _run_hook(tmp_path, t)

    # Must not crash — the id-less block is skipped, the rest of the summary still fires
    assert result.returncode == 0, result.stderr
    events_posts = [u for u in url_lines if "/api/memory/events" in u]
    assert len(events_posts) == 1, f"Expected 1 events POST, got {events_posts}"
