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
