"""Spectro subsystem is gone: no registration, no config, no env hooks."""

import subprocess
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")


def test_registry_has_no_spectro():
    from tools.registry import ToolRegistry

    registry = ToolRegistry()
    assert "spectro" not in registry.discover()


def test_no_spectro_references_in_src():
    result = subprocess.run(
        ["grep", "-ri", "spectro", SRC, "--include=*.py"],
        capture_output=True,
        text=True,
    )
    assert result.stdout == "", f"spectro references remain:\n{result.stdout}"
    assert result.returncode == 1, f"grep did not run cleanly: rc={result.returncode} stderr={result.stderr}"
