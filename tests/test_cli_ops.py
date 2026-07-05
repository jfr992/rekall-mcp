"""Tests for doctor and startup-preview CLI verbs (TDD)."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from memory.cli import memory


def _urlopen_mock(data: dict) -> MagicMock:
    """Context-manager mock that streams JSON bytes."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


_HEALTHY = {
    "status": "healthy",
    "findings": [],
    "notes": [],
    "vector_health": {},
    "project": None,
    "yaml_count": 0,
    "qdrant_count": 0,
}

_DEGRADED = {
    "status": "degraded",
    "findings": ["yaml_not_indexed"],
    "notes": [],
    "vector_health": {},
    "project": None,
    "yaml_count": 1,
    "qdrant_count": 0,
}

_CAPSULE = {
    "project": "myproject",
    "entities": [],
    "standing_context": [],
    "danger_zones": [],
    "open_loops": [],
}


class TestDoctorCommand:
    def test_doctor_rest_success_healthy(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            return_value=_urlopen_mock(_HEALTHY),
        ):
            result = runner.invoke(memory, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "healthy" in result.output

    def test_doctor_rest_success_degraded(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            return_value=_urlopen_mock(_DEGRADED),
        ):
            result = runner.invoke(memory, ["doctor"])
        assert result.exit_code == 1, result.output

    def test_doctor_rest_down_fallback_warning(self):
        runner = CliRunner()
        with (
            patch(
                "memory.cli.urllib.request.urlopen",
                side_effect=urllib.error.URLError("refused"),
            ),
            patch("memory.cli.run_memory_doctor", return_value=_HEALTHY),
            patch("memory.cli.MemoryManager"),
        ):
            result = runner.invoke(memory, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "WARNING" in result.output

    def test_doctor_both_fail_exit3(self):
        runner = CliRunner()
        with (
            patch(
                "memory.cli.urllib.request.urlopen",
                side_effect=urllib.error.URLError("refused"),
            ),
            patch("memory.cli.run_memory_doctor", side_effect=Exception("local failure")),
            patch("memory.cli.MemoryManager"),
        ):
            result = runner.invoke(memory, ["doctor"])
        assert result.exit_code == 3, result.output

    def test_doctor_bad_flag_exit2(self):
        runner = CliRunner()
        with patch("memory.cli.MemoryManager"):
            result = runner.invoke(memory, ["doctor", "--bogus-flag"])
        assert result.exit_code == 2

    def test_doctor_json_flag(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            return_value=_urlopen_mock(_HEALTHY),
        ):
            result = runner.invoke(memory, ["doctor", "--json"])
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["status"] == "healthy"


class TestStartupPreviewCommand:
    def test_startup_preview_success(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            return_value=_urlopen_mock(_CAPSULE),
        ):
            result = runner.invoke(memory, ["startup-preview", "--project", "myproject"])
        assert result.exit_code == 0, result.output
        assert "approximate preview via /api/memory/capsule" in result.output.splitlines()[0]

    def test_startup_preview_backend_down_exit3(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            side_effect=urllib.error.URLError("refused"),
        ):
            result = runner.invoke(memory, ["startup-preview", "--project", "myproject"])
        assert result.exit_code == 3

    def test_startup_preview_honesty_header(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            return_value=_urlopen_mock(_CAPSULE),
        ):
            result = runner.invoke(memory, ["startup-preview", "--project", "myproject"])
        assert result.exit_code == 0, result.output
        first_line = result.output.splitlines()[0]
        assert first_line == (
            "approximate preview via /api/memory/capsule"
            " — the SessionStart hook applies its own formatting/truncation"
        )
