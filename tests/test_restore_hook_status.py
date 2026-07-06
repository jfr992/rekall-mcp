"""Restore-hook status line surfaces vector health (corruption tripwire).

Two prod zero-vector incidents went undetected for days because the
session status line only reported counts. The hook now appends a vector
indicator from /health so corruption is visible at next session start.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude" / "hooks" / "rekall-restore.sh"

STATS_BODY = json.dumps({"total_memories": 42, "knowledge_graph": {"nodes": 40, "edges": 100}})


def _fake_curl(tmp_path: Path, health_body: str) -> Path:
    """Fake curl serving /health and /api/memory/stats."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        f"    */health) echo '{health_body}'; exit 0;;\n"
        f"    */api/memory/stats) echo '{STATS_BODY}'; exit 0;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n"
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run_hook(tmp_path: Path, health_body: str) -> subprocess.CompletedProcess:
    bin_dir = _fake_curl(tmp_path, health_body)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["REKALL_MARKER_DIR"] = str(tmp_path)
    env["CLAUDE_SESSION_ID"] = "tripwire-test"
    env.pop("REKALL_AUTOSAVE", None)
    return subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env, timeout=10)


def test_healthy_vectors_shown_ok(tmp_path):
    body = json.dumps({"status": "healthy", "vectors": {"sampled": 256, "zero_vectors": 0}})
    result = _run_hook(tmp_path, body)
    assert result.returncode == 0
    assert "42 memories" in result.stdout
    assert "vectors OK" in result.stdout


def test_dead_vectors_flagged_loudly(tmp_path):
    body = json.dumps({"status": "degraded", "vectors": {"sampled": 256, "zero_vectors": 118}})
    result = _run_hook(tmp_path, body)
    assert result.returncode == 0
    assert "118 dead vectors" in result.stdout
    assert "vectors OK" not in result.stdout


def test_missing_vectors_block_fails_open(tmp_path):
    # Pre-1.8 backend without the vectors block: no indicator, no crash.
    body = json.dumps({"status": "healthy"})
    result = _run_hook(tmp_path, body)
    assert result.returncode == 0
    assert "42 memories" in result.stdout
    assert "dead vectors" not in result.stdout
    assert "vectors OK" not in result.stdout
