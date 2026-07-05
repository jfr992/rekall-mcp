"""Tests for doctor, startup-preview, backup, and migrate CLI verbs (TDD)."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
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
        mock_urlopen = MagicMock(return_value=_urlopen_mock(_HEALTHY))
        with patch("memory.cli.urllib.request.urlopen", mock_urlopen):
            result = runner.invoke(memory, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "healthy" in result.output
        called_url = mock_urlopen.call_args[0][0].full_url
        assert "/api/memory/doctor" in called_url

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
        assert "unreachable" in result.output

    def test_doctor_http_error_not_treated_as_unreachable(self):
        """HTTP 5xx from backend should give HTTP error message, not 'backend unreachable' fallback."""
        runner = CliRunner()
        http_err = urllib.error.HTTPError(
            url=None, code=500, msg="Internal Server Error", hdrs=None, fp=None
        )
        with patch("memory.cli.urllib.request.urlopen", side_effect=http_err):
            result = runner.invoke(memory, ["doctor"])
        assert result.exit_code == 1
        assert "HTTP 500" in result.output
        assert "WARNING" not in result.output

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
        mock_urlopen = MagicMock(return_value=_urlopen_mock(_CAPSULE))
        with patch("memory.cli.urllib.request.urlopen", mock_urlopen):
            result = runner.invoke(memory, ["startup-preview", "--project", "myproject"])
        assert result.exit_code == 0, result.output
        assert "approximate preview via /api/memory/capsule" in result.output.splitlines()[0]
        called_url = mock_urlopen.call_args[0][0].full_url
        assert "/api/memory/capsule?project=" in called_url

    def test_startup_preview_backend_down_exit3(self):
        runner = CliRunner()
        with patch(
            "memory.cli.urllib.request.urlopen",
            side_effect=urllib.error.URLError("refused"),
        ):
            result = runner.invoke(memory, ["startup-preview", "--project", "myproject"])
        assert result.exit_code == 3
        assert "unreachable" in result.output

    def test_startup_preview_http_error_not_treated_as_unreachable(self):
        """HTTP 5xx from backend should give HTTP error message, not 'backend unreachable'."""
        runner = CliRunner()
        http_err = urllib.error.HTTPError(
            url=None, code=500, msg="Internal Server Error", hdrs=None, fp=None
        )
        with patch("memory.cli.urllib.request.urlopen", side_effect=http_err):
            result = runner.invoke(memory, ["startup-preview", "--project", "myproject"])
        assert result.exit_code == 1
        assert "HTTP 500" in result.output
        assert "unreachable" not in result.output

    def test_startup_preview_accepts_agent_flag(self):
        """--agent is accepted for parity with the hook but must not appear in the URL."""
        runner = CliRunner()
        mock_urlopen = MagicMock(return_value=_urlopen_mock(_CAPSULE))
        with patch("memory.cli.urllib.request.urlopen", mock_urlopen):
            result = runner.invoke(
                memory,
                ["startup-preview", "--project", "myproject", "--agent", "claude-code"],
            )
        assert result.exit_code == 0, result.output
        called_url = mock_urlopen.call_args[0][0].full_url
        assert "agent=" not in called_url

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


class TestBackupCommand:
    def test_backup_command_exists(self):
        """The backup sub-command must be registered on the memory group."""
        runner = CliRunner()
        result = runner.invoke(memory, ["backup", "--help"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Helpers for backup / migrate tests
# ---------------------------------------------------------------------------


def _make_fake_tarball(path) -> None:
    """Create a minimal valid tarball with one entry (used in mock side-effects)."""
    from pathlib import Path as _Path

    p = _Path(path)
    with tarfile.open(p, "w:gz") as tf:
        info = tarfile.TarInfo("placeholder")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))


class _DockerRecorder:
    """Fake subprocess.run that records docker calls and returns controllable results."""

    def __init__(
        self,
        *,
        container_present: bool = True,
        stop_rc: int = 0,
        start_rc: int = 0,
        docker_available: bool = True,
        ps_rc: int = 0,
        ps_stderr: str = "",
        start_raises: BaseException | None = None,
    ):
        self.calls: list[list[str]] = []
        self.container_present = container_present
        self.stop_rc = stop_rc
        self.start_rc = start_rc
        self.docker_available = docker_available
        self.ps_rc = ps_rc
        self.ps_stderr = ps_stderr
        self.start_raises = start_raises

    def __call__(self, cmd, **kwargs):
        if not self.docker_available:
            raise FileNotFoundError("docker not found")
        self.calls.append(list(cmd))
        mock = MagicMock()
        sub = cmd[1] if len(cmd) > 1 else ""
        if sub == "ps":
            mock.returncode = self.ps_rc
            mock.stdout = "rekall-qdrant\n" if self.container_present and self.ps_rc == 0 else ""
            mock.stderr = self.ps_stderr
        elif sub == "stop":
            mock.returncode = self.stop_rc
            mock.stdout = ""
            mock.stderr = "" if self.stop_rc == 0 else "Error: No such container"
        elif sub == "start":
            if self.start_raises is not None:
                raise self.start_raises
            mock.returncode = self.start_rc
            mock.stdout = ""
            mock.stderr = "" if self.start_rc == 0 else "Error: No such container"
        else:
            mock.returncode = 0
            mock.stdout = ""
            mock.stderr = ""
        return mock


class TestBackupHappyPaths:
    def test_memory_only_no_docker(self, tmp_path):
        """docker absent -> memory-only backup, WARNING, exit 0."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(docker_available=False)
        runner = CliRunner()
        with patch("memory.cli.subprocess.run", recorder):
            result = runner.invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        assert "WARNING" in result.output
        tarballs = list(out_dir.glob("rekall-*-memory.tar.gz"))
        assert len(tarballs) == 1
        assert len(list(out_dir.glob("rekall-*-qdrant.tar.gz"))) == 0
        assert str(tarballs[0]) in result.output

    def test_container_absent(self, tmp_path):
        """Container not running -> memory-only backup, WARNING, exit 0."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(container_present=False)
        runner = CliRunner()
        with patch("memory.cli.subprocess.run", recorder):
            result = runner.invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        assert "WARNING" in result.output
        tarballs = list(out_dir.glob("rekall-*-memory.tar.gz"))
        assert len(tarballs) == 1
        assert str(tarballs[0]) in result.output

    def test_full_backup_both_tarballs(self, tmp_path):
        """Container running -> both tarballs created, paths printed, exit 0."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        qd_dir = tmp_path / "qdrant"
        qd_dir.mkdir()
        (qd_dir / "collection.db").write_bytes(b"qdrant data")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder()
        runner = CliRunner()
        with patch("memory.cli.subprocess.run", recorder):
            result = runner.invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_DATA_PATH": str(qd_dir),
                },
            )

        assert result.exit_code == 0, result.output
        mem_tars = list(out_dir.glob("rekall-*-memory.tar.gz"))
        qd_tars = list(out_dir.glob("rekall-*-qdrant.tar.gz"))
        assert len(mem_tars) == 1
        assert len(qd_tars) == 1
        assert str(mem_tars[0]) in result.output
        assert str(qd_tars[0]) in result.output


class TestBackupDockerContract:
    def test_stop_before_start_order(self, tmp_path):
        """docker stop must be called before docker start."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        qd_dir = tmp_path / "qdrant"
        qd_dir.mkdir()
        (qd_dir / "collection.db").write_bytes(b"x")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder()
        with patch("memory.cli.subprocess.run", recorder):
            CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_DATA_PATH": str(qd_dir),
                },
            )

        subcmds = [c[1] for c in recorder.calls if c[0] == "docker"]
        assert subcmds.index("stop") < subcmds.index("start")

    def test_start_runs_in_finally_when_tar_raises(self, tmp_path):
        """docker start is called in finally even when the tar step raises."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder()
        call_count = [0]

        def side_effect_make_tarball(src, dest):
            call_count[0] += 1
            if call_count[0] == 1:
                _make_fake_tarball(dest)
            else:
                # BaseException-adjacent: KeyboardInterrupt is NOT caught by the
                # inner `except Exception`, so only a real finally runs cleanup.
                raise KeyboardInterrupt("simulated interrupt mid-tar")

        with (
            patch("memory.cli.subprocess.run", recorder),
            patch("memory.cli._make_tarball", side_effect=side_effect_make_tarball),
        ):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_DATA_PATH": str(tmp_path / "qdrant"),
                },
            )

        assert result.exit_code == 1, result.output
        subcmds = [c[1] for c in recorder.calls if c[0] == "docker"]
        assert "start" in subcmds, "docker start must run in finally even when tar raises"

    def test_restart_failure_exit1_with_error_message(self, tmp_path):
        """Qdrant restart failure -> exit 1, ERROR in output."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        qd_dir = tmp_path / "qdrant"
        qd_dir.mkdir()
        (qd_dir / "collection.db").write_bytes(b"x")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(start_rc=1)
        with patch("memory.cli.subprocess.run", recorder):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_DATA_PATH": str(qd_dir),
                },
            )

        assert result.exit_code == 1
        assert "ERROR" in result.output

    def test_tarball_verification_failure_exit1(self, tmp_path):
        """_verify_tarball returning False -> exit 1."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        with patch("memory.cli._verify_tarball", return_value=False):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 1


class TestBackupEnvPaths:
    def test_memory_storage_path_env(self, tmp_path):
        """MEMORY_STORAGE_PATH resolves to the correct directory."""
        mem_dir = tmp_path / "custom_memory"
        mem_dir.mkdir()
        (mem_dir / "data.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(container_present=False)
        with patch("memory.cli.subprocess.run", recorder):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        tarballs = list(out_dir.glob("rekall-*-memory.tar.gz"))
        assert len(tarballs) == 1
        with tarfile.open(tarballs[0], "r:gz") as tf:
            assert any("custom_memory" in n for n in tf.getnames())

    def test_qdrant_data_path_env(self, tmp_path):
        """QDRANT_DATA_PATH resolves to the correct directory for the tarball."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        custom_qd = tmp_path / "custom_qdrant"
        custom_qd.mkdir()
        (custom_qd / "store.db").write_bytes(b"custom qdrant")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder()
        with patch("memory.cli.subprocess.run", recorder):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_DATA_PATH": str(custom_qd),
                },
            )

        assert result.exit_code == 0, result.output
        qd_tars = list(out_dir.glob("rekall-*-qdrant.tar.gz"))
        assert len(qd_tars) == 1
        with tarfile.open(qd_tars[0], "r:gz") as tf:
            assert any("custom_qdrant" in n for n in tf.getnames())


class TestMigrateCommand:
    def test_migrate_command_exists(self):
        """The migrate sub-command must be registered on the memory group."""
        runner = CliRunner()
        result = runner.invoke(memory, ["migrate", "--help"])
        assert result.exit_code == 0, result.output

    def test_dry_run_zero_subprocess_calls(self, tmp_path):
        """--dry-run skips backup entirely (zero subprocess calls)."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        _dry_result = {"status": "dry_run", "memories": 0, "vocab_size": 0, "schema_updates": 0}

        subprocess_calls = []

        def fail_if_called(*a, **kw):
            subprocess_calls.append(a)
            raise AssertionError("subprocess.run called during dry-run")

        with (
            patch("memory.cli.subprocess.run", fail_if_called),
            patch("memory.cli.migrate_to_hybrid", return_value=_dry_result) as mock_migrate,
        ):
            result = CliRunner().invoke(
                memory,
                ["migrate", "--dry-run"],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        assert subprocess_calls == []
        _, kwargs = mock_migrate.call_args
        assert kwargs.get("dry_run") is True

    def test_no_backup_skips_docker_calls(self, tmp_path):
        """--no-backup skips backup -- no subprocess calls."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        _complete = {"status": "complete", "memories": 1, "vocab_size": 10, "schema_updates": 0}

        subprocess_calls = []

        def fail_if_called(*a, **kw):
            subprocess_calls.append(a)
            raise AssertionError("subprocess called with --no-backup")

        with (
            patch("memory.cli.subprocess.run", fail_if_called),
            patch("memory.cli.migrate_to_hybrid", return_value=_complete),
        ):
            result = CliRunner().invoke(
                memory,
                ["migrate", "--no-backup"],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        assert subprocess_calls == []

    def test_backup_failure_aborts_migrate(self, tmp_path):
        """Backup failure -> exit 1, migrate_to_hybrid never called."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()

        from memory.cli import _BackupError

        with (
            patch("memory.cli._do_backup", side_effect=_BackupError("backup exploded")),
            patch("memory.cli.migrate_to_hybrid") as mock_migrate,
        ):
            result = CliRunner().invoke(
                memory,
                ["migrate"],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 1
        mock_migrate.assert_not_called()

    def test_success_status_complete_exit0(self, tmp_path):
        """status=complete -> exit 0, JSON printed."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        _complete = {"status": "complete", "memories": 5, "vocab_size": 100, "schema_updates": 2}

        with (
            patch("memory.cli._do_backup", return_value=[tmp_path / "fake.tar.gz"]),
            patch("memory.cli.migrate_to_hybrid", return_value=_complete),
        ):
            result = CliRunner().invoke(
                memory,
                ["migrate"],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        assert '"status": "complete"' in result.output

    def test_bad_status_exit1(self, tmp_path):
        """status=no_memories (not complete/dry_run) -> exit 1."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()

        with (
            patch("memory.cli._do_backup", return_value=[tmp_path / "fake.tar.gz"]),
            patch(
                "memory.cli.migrate_to_hybrid", return_value={"status": "no_memories", "count": 0}
            ),
        ):
            result = CliRunner().invoke(
                memory,
                ["migrate"],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 1

    def test_env_paths_wired_to_migrate_to_hybrid(self, tmp_path):
        """MEMORY_STORAGE_PATH and QDRANT_URL are passed through to migrate_to_hybrid."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()

        with (
            patch("memory.cli._do_backup", return_value=[tmp_path / "fake.tar.gz"]),
            patch(
                "memory.cli.migrate_to_hybrid", return_value={"status": "complete"}
            ) as mock_migrate,
        ):
            result = CliRunner().invoke(
                memory,
                ["migrate"],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_URL": "http://custom-qdrant:9999",
                },
            )

        assert result.exit_code == 0, result.output
        mock_migrate.assert_called_once()
        _, kwargs = mock_migrate.call_args
        assert str(kwargs["memory_dir"]) == str(mem_dir)
        assert kwargs["qdrant_url"] == "http://custom-qdrant:9999"

    def test_dry_run_status_exit0(self, tmp_path):
        """status=dry_run -> exit 0."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        _dry = {"status": "dry_run", "memories": 3, "vocab_size": 50, "schema_updates": 1}

        with patch("memory.cli.migrate_to_hybrid", return_value=_dry):
            result = CliRunner().invoke(
                memory,
                ["migrate", "--dry-run"],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Fix round 1 — four correctness findings (TDD: one test per cycle)
# ---------------------------------------------------------------------------


class TestBackupFindingsRound1:
    def test_docker_start_raises_in_finally_exit1_message_no_traceback(self, tmp_path):
        """Finding 1: docker start raises TimeoutExpired inside finally -> exit 1,
        stderr contains 'failed to restart', no raw traceback leaks."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        qd_dir = tmp_path / "qdrant"
        qd_dir.mkdir()
        (qd_dir / "collection.db").write_bytes(b"x")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(
            start_raises=subprocess.TimeoutExpired(
                cmd=["docker", "start", "rekall-qdrant"], timeout=30
            )
        )
        with patch("memory.cli.subprocess.run", recorder):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir), "QDRANT_DATA_PATH": str(qd_dir)},
            )

        assert result.exit_code == 1
        assert "failed to restart" in result.output
        assert "Traceback" not in result.output

    def test_docker_ps_nonzero_rc_memory_only_with_stderr_hint(self, tmp_path):
        """Finding 2: docker ps rc=1 with stderr -> memory-only backup, WARNING contains
        the stderr snippet, exit 0."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(ps_rc=1, ps_stderr="permission denied by daemon")
        with patch("memory.cli.subprocess.run", recorder):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir)},
            )

        assert result.exit_code == 0, result.output
        assert "WARNING" in result.output
        assert "permission denied by daemon" in result.output
        assert len(list(out_dir.glob("rekall-*-memory.tar.gz"))) == 1
        assert len(list(out_dir.glob("rekall-*-qdrant.tar.gz"))) == 0


class TestCheckDockerContainerUnit:
    def test_daemon_error_returncode_returns_none_with_stderr(self):
        """_check_docker_container returns (None, stderr) when docker ps exits non-zero."""
        from memory.cli import _check_docker_container

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "permission denied"

        with patch("memory.cli.subprocess.run", return_value=mock_result):
            result = _check_docker_container("test-container")

        # Currently returns bool|None; after fix returns tuple[bool|None, str]
        state, hint = result
        assert state is None
        assert "permission denied" in hint

    def test_stop_failure_message_names_docker_stop_not_tarball(self, tmp_path):
        """Finding 3: stop_rc=1 -> exit 1, error message says 'docker stop', not
        the misleading 'Qdrant tarball failed' prefix."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        qd_dir = tmp_path / "qdrant"
        qd_dir.mkdir()
        (qd_dir / "collection.db").write_bytes(b"x")
        out_dir = tmp_path / "backups"

        recorder = _DockerRecorder(stop_rc=1)
        with patch("memory.cli.subprocess.run", recorder):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={"MEMORY_STORAGE_PATH": str(mem_dir), "QDRANT_DATA_PATH": str(qd_dir)},
            )

        assert result.exit_code == 1
        assert "docker stop" in result.output
        assert "Qdrant tarball" not in result.output

    def test_both_tar_and_restart_errors_both_logged(self, tmp_path):
        """Finding 4: when tar step fails AND restart fails, both errors are logged
        to stderr (restart still dominates the exit reason)."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.yaml").write_text("memories: []")
        out_dir = tmp_path / "backups"

        call_count = [0]

        def side_effect_make_tarball(src, dest):
            call_count[0] += 1
            if call_count[0] == 1:
                _make_fake_tarball(dest)  # memory tarball succeeds
            else:
                raise RuntimeError("simulated qdrant tar write failure")

        recorder = _DockerRecorder(start_rc=1)
        with (
            patch("memory.cli.subprocess.run", recorder),
            patch("memory.cli._make_tarball", side_effect=side_effect_make_tarball),
        ):
            result = CliRunner().invoke(
                memory,
                ["backup", "--out", str(out_dir)],
                env={
                    "MEMORY_STORAGE_PATH": str(mem_dir),
                    "QDRANT_DATA_PATH": str(tmp_path / "qdrant"),
                },
            )

        assert result.exit_code == 1
        assert "failed to restart" in result.output
        assert "simulated qdrant tar write failure" in result.output


# ---------------------------------------------------------------------------
# install-claude verb (T3)
# ---------------------------------------------------------------------------


class TestInstallClaude:
    def test_install_claude_command_registered(self):
        """install-claude must be registered as a sub-command on the memory group."""
        runner = CliRunner()
        result = runner.invoke(memory, ["install-claude", "--help"])
        assert result.exit_code == 0, result.output

    def test_missing_exit1_with_message(self):
        """Not in a repo checkout -> exit 1, exact helpful message."""
        runner = CliRunner()
        with patch("memory.cli._find_install_sh", return_value=None):
            result = runner.invoke(memory, ["install-claude"])
        assert result.exit_code == 1
        assert "install-claude requires a rekall-mcp repo checkout" in result.output
        assert "bash <repo>/claude/setup/install.sh" in result.output

    def test_flags_pass_through(self, tmp_path):
        """--skills-only, --hooks-only, --skip-backend are forwarded to bash."""
        fake_sh = tmp_path / "claude" / "setup" / "install.sh"
        fake_sh.parent.mkdir(parents=True)
        fake_sh.write_text("#!/bin/bash\necho done")
        with (
            patch("memory.cli._find_install_sh", return_value=fake_sh),
            patch("memory.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = CliRunner().invoke(
                memory,
                ["install-claude", "--skills-only", "--hooks-only", "--skip-backend"],
            )
        assert result.exit_code == 0, result.output
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "bash"
        assert "--skills-only" in cmd
        assert "--hooks-only" in cmd
        assert "--skip-backend" in cmd

    def test_exit_code_propagates(self, tmp_path):
        """Exit code from install.sh is propagated."""
        fake_sh = tmp_path / "install.sh"
        with (
            patch("memory.cli._find_install_sh", return_value=fake_sh),
            patch("memory.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=42)
            result = CliRunner().invoke(memory, ["install-claude"])
        assert result.exit_code == 42

    def test_no_flags_minimal_cmd(self, tmp_path):
        """With no flags, only bash + script path are passed to subprocess."""
        fake_sh = tmp_path / "install.sh"
        with (
            patch("memory.cli._find_install_sh", return_value=fake_sh),
            patch("memory.cli.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            CliRunner().invoke(memory, ["install-claude"])
        cmd = mock_run.call_args[0][0]
        assert cmd == ["bash", str(fake_sh)]

    def test_walk_up_from_nested_cwd_finds_script(self, tmp_path):
        """_find_install_sh walks up from a nested cwd to find the script."""
        from memory.cli import _find_install_sh

        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        install_sh = tmp_path / "claude" / "setup" / "install.sh"
        install_sh.parent.mkdir(parents=True)
        install_sh.write_text("#!/bin/bash\necho done")

        found = _find_install_sh(start_dir=nested)
        assert found == install_sh

    def test_walk_up_not_found_returns_none(self, tmp_path):
        """_find_install_sh returns None when no install.sh exists in ancestors."""
        from memory.cli import _find_install_sh

        nested = tmp_path / "x" / "y"
        nested.mkdir(parents=True)
        found = _find_install_sh(start_dir=nested)
        assert found is None
