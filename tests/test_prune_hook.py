"""memory-prune hook: daily debounce + kill-switch (pattern: test_restore_hook_status)."""

import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude" / "hooks" / "memory-prune.sh"


def _fake_curl(tmp_path: Path, log: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(f'#!/usr/bin/env bash\necho called >> "{log}"\necho \'{{"deleted": []}}\'\n')
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run(tmp_path: Path, log: Path, env_extra=None):
    env = dict(os.environ)
    env["PATH"] = f"{_fake_curl(tmp_path, log)}:{env['PATH']}"
    env["REKALL_MARKER_DIR"] = str(tmp_path)
    env.pop("REKALL_AUTOSAVE", None)
    env.update(env_extra or {})
    return subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env, timeout=10)


def test_fires_once_per_day(tmp_path):
    log = tmp_path / "calls.log"
    r1 = _run(tmp_path, log)
    r2 = _run(tmp_path, log)
    assert r1.returncode == 0 and r2.returncode == 0
    assert log.read_text().count("called") == 1


def test_kill_switch(tmp_path):
    log = tmp_path / "calls.log"
    r = _run(tmp_path, log, {"REKALL_AUTOSAVE": "0"})
    assert r.returncode == 0 and not log.exists()
