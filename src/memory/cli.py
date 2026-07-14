"""CLI for memory system."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import click

from .capsules import render_project_capsule
from .doctor import run_memory_doctor
from .manager import MemoryManager
from .migrate_hybrid import migrate_to_hybrid
from .types import VALID_MEMORY_TYPES


@click.group()
@click.option(
    "--memory-dir",
    default="~/.claude/memory",
    help="Memory storage directory",
)
@click.option(
    "--qdrant-url",
    default="http://localhost:6333",
    help="Qdrant server URL",
)
@click.pass_context
def memory(ctx, memory_dir: str, qdrant_url: str):
    """Memory system CLI for persistent AI context."""
    ctx.ensure_object(dict)
    ctx.obj["memory_dir"] = memory_dir
    ctx.obj["qdrant_url"] = qdrant_url


def _manager(ctx) -> MemoryManager:
    """Construct lazily — commands like --help, doctor, and backup never need one."""
    if "manager" not in ctx.obj:
        ctx.obj["manager"] = MemoryManager(
            memory_dir=ctx.obj["memory_dir"],
            qdrant_url=ctx.obj["qdrant_url"],
        )
    return ctx.obj["manager"]


@memory.command()
@click.argument("content")
@click.option(
    "--type",
    "-t",
    "memory_type",
    default="note",
    type=click.Choice(sorted(VALID_MEMORY_TYPES)),
    help="Memory type",
)
@click.option("--project", "-p", help="Project name")
@click.pass_context
def save(ctx, content: str, memory_type: str, project: str | None):
    """Save a memory.

    Examples:
        memory save "Decided to use Python" --type decision
        memory save "User prefers diagrams" --type preference --project my-app
    """
    mgr: MemoryManager = _manager(ctx)
    memory_id = mgr.save(content, type=memory_type, project=project)
    click.echo(f"✓ Saved: {memory_id}")


@memory.command()
@click.argument("query")
@click.option("--limit", "-n", default=5, help="Max results")
@click.option("--project", "-p", help="Filter by project")
@click.option(
    "--type",
    "-t",
    "memory_type",
    help="Filter by type",
)
@click.option("--days", "-d", type=int, help="Only last N days")
@click.pass_context
def recall(
    ctx,
    query: str,
    limit: int,
    project: str | None,
    memory_type: str | None,
    days: int | None,
):
    """Recall memories using semantic search.

    Examples:
        memory recall "architecture decisions"
        memory recall "user preferences" --project my-app
        memory recall "recent work" --days 7
    """
    mgr: MemoryManager = _manager(ctx)
    results = mgr.recall(
        query,
        limit=limit,
        project=project,
        type=memory_type,
        days_back=days,
    )

    if not results:
        click.echo("No relevant memories found.")
        return

    for r in results:
        click.echo(
            f"\n{'─' * 60}\n"
            f"[{r['date']}] {r['type']} | {r['project']} | score: {r['score']:.2f}\n"
            f"{'─' * 60}"
        )
        click.echo(r["content"])


@memory.command()
@click.argument("project")
@click.pass_context
def context(ctx, project: str):
    """Get project context (cache-friendly).

    Examples:
        memory context my-project
    """
    mgr: MemoryManager = _manager(ctx)
    ctx_str = mgr.get_project_context(project)

    if ctx_str:
        click.echo(ctx_str)
    else:
        click.echo(f"No stored context for project: {project}")


@memory.command()
@click.option("--tasks", "-t", help="Comma-separated tasks completed")
@click.option("--decisions", "-d", help="Comma-separated decisions")
@click.option("--learnings", "-l", help="Comma-separated learnings")
@click.option("--project", "-p", help="Project name")
@click.pass_context
def end_session(
    ctx,
    tasks: str | None,
    decisions: str | None,
    learnings: str | None,
    project: str | None,
):
    """Save end-of-session summary.

    Examples:
        memory end-session --tasks "Built API, Added tests" --project my-app
        memory end-session -t "Fixed bug" -d "Use Redis for cache" -p backend
    """
    mgr: MemoryManager = _manager(ctx)

    memory_id = mgr.save_session_summary(
        tasks_completed=[t.strip() for t in (tasks or "").split(",") if t.strip()],
        decisions_made=[d.strip() for d in (decisions or "").split(",") if d.strip()],
        learnings=[item.strip() for item in (learnings or "").split(",") if item.strip()],
        project=project,
    )

    if memory_id:
        click.echo(f"✓ Session summary saved: {memory_id}")
    else:
        click.echo("No content to save.")


@memory.command()
@click.pass_context
def stats(ctx):
    """Show memory statistics."""
    mgr: MemoryManager = _manager(ctx)
    s = mgr.get_stats()

    click.echo("\n📊 Memory System Stats")
    click.echo("─" * 40)
    click.echo(f"Total memories:  {s['total_memories']}")
    click.echo(f"Memory files:    {s['memory_files']}")
    click.echo(f"Storage:         {s['memory_dir']}")

    if s.get("by_type"):
        click.echo("\nBy type:")
        for t, count in s["by_type"].items():
            click.echo(f"  {t}: {count}")


@memory.command()
@click.argument("project")
@click.confirmation_option(prompt="Are you sure you want to clear this project's memories?")
@click.pass_context
def clear(ctx, project: str):
    """Clear all memories for a project.

    Examples:
        memory clear old-project
    """
    mgr: MemoryManager = _manager(ctx)
    result = mgr.clear_project(project)
    click.echo(
        f"✓ Cleared {result['deleted']} memories for: {project}"
        f" ({result['strays_removed']} stray YAML entries removed)"
    )


@memory.command()
@click.option("--project", "-p", help="Project name")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output raw JSON")
def doctor(project: str | None, as_json: bool):
    """Check memory system health.

    Tries the backend REST endpoint first; falls back to a local scan if the
    backend is unreachable.  Exit 0 = healthy, 1 = degraded, 3 = unreachable.
    """
    api_url = os.environ.get("REKALL_API_URL", "http://localhost:8000")
    endpoint = f"{api_url}/api/memory/doctor"
    if project:
        endpoint += f"?project={urllib.parse.quote(project)}"

    data: dict | None = None
    try:
        req = urllib.request.Request(endpoint)
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        click.echo(f"ERROR: /api/memory/doctor returned HTTP {exc.code}", err=True)
        sys.exit(1)
    except (urllib.error.URLError, OSError):
        storage_path = os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")
        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        click.echo(
            f"WARNING: backend unreachable — local scan of {storage_path} + {qdrant_url};"
            " may not match backend view",
            err=True,
        )
        try:
            mgr = MemoryManager(memory_dir=storage_path, qdrant_url=qdrant_url)
            data = run_memory_doctor(mgr, project=project)
        except Exception:
            click.echo("local scan also failed — cannot produce doctor report", err=True)
            sys.exit(3)

    if data is None:
        click.echo("No data from doctor", err=True)
        sys.exit(3)

    status = data.get("status", "unknown")
    exit_code = 0 if status == "healthy" else 1

    if as_json:
        click.echo(json.dumps(data, indent=2))
        sys.exit(exit_code)

    click.echo(f"Status: {status}")
    findings = data.get("findings") or []
    notes = data.get("notes") or []
    vector_health = data.get("vector_health") or {}
    click.echo(f"Findings: {', '.join(str(f) for f in findings) or 'none'}")
    if notes:
        click.echo(f"Notes: {', '.join(str(n) for n in notes)}")
    if vector_health:
        click.echo(f"Vector health: {vector_health}")

    sys.exit(exit_code)


@memory.command("startup-preview")
@click.option("--project", "-p", help="Project name")
@click.option(
    "--agent",
    "-a",
    default=None,
    help="Agent name (accepted for parity with the hook; not forwarded to the endpoint)",
)
def startup_preview(project: str | None, agent: str | None):
    """Preview the project capsule as the SessionStart hook receives it.

    Hits the same /api/memory/capsule endpoint the hook curls.  No local
    fallback — previewing a dead backend would be fiction.  Exit 3 if the
    backend is unreachable.
    """
    api_url = os.environ.get("REKALL_API_URL", "http://localhost:8000")
    proj = project or "default"
    endpoint = f"{api_url}/api/memory/capsule?project={urllib.parse.quote(proj)}"

    try:
        req = urllib.request.Request(endpoint)
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        click.echo(f"ERROR: capsule endpoint returned HTTP {exc.code}", err=True)
        sys.exit(1)
    except (urllib.error.URLError, OSError):
        click.echo("backend unreachable — cannot preview a dead backend", err=True)
        sys.exit(3)

    click.echo(
        "approximate preview via /api/memory/capsule"
        " \u2014 the SessionStart hook applies its own formatting/truncation"
    )
    click.echo(render_project_capsule(data))


# ---------------------------------------------------------------------------
# Backup helpers (shared by backup and migrate commands)
# ---------------------------------------------------------------------------


class _BackupError(RuntimeError):
    """Fatal backup failure; caller should exit 1."""


def _resolve_path(env_var: str, default: str) -> Path:
    """Resolve a path from an env var with a fallback default."""
    return Path(os.environ.get(env_var) or default).expanduser()


def _check_docker_container(name: str) -> tuple[bool | None, str]:
    """True=running, False=absent/stopped, None=docker unavailable.

    Returns (state, stderr_hint); stderr_hint is non-empty only when docker
    daemon returned a non-zero exit code.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None, result.stderr.strip()
        return name in result.stdout, ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None, ""


def _make_tarball(src: Path, dest: Path) -> None:
    """Create a gzip tarball of *src* at *dest*."""
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(src, arcname=src.name)


def _verify_tarball(path: Path) -> bool:
    """Return True iff the tarball exists, is non-empty, and lists >=1 entry."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with tarfile.open(path, "r:gz") as tf:
            return bool(tf.getnames())
    except Exception:
        return False


def _do_backup(out_dir: Path) -> list[Path]:
    """Execute the backup ritual and return artifact paths.

    Creates memory tarball always; Qdrant tarball when the rekall-qdrant
    container is running (stop -> tar -> always restart via try/finally).
    Degrades gracefully to memory-only when docker or container is absent.
    Raises _BackupError on any fatal failure.
    """
    memory_dir = _resolve_path("MEMORY_STORAGE_PATH", "~/.claude/memory")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []

    # Memory tarball
    mem_tar = out_dir / f"rekall-{ts}-memory.tar.gz"
    try:
        _make_tarball(memory_dir, mem_tar)
    except Exception as exc:
        raise _BackupError(f"Memory tarball failed: {exc}") from exc
    if not _verify_tarball(mem_tar):
        raise _BackupError(f"Memory tarball verification failed: {mem_tar}")
    artifacts.append(mem_tar)

    # Qdrant tarball -- optional, degrades gracefully
    container_state, docker_stderr = _check_docker_container("rekall-qdrant")

    if container_state is None:
        hint = f" ({docker_stderr})" if docker_stderr else ""
        click.echo(
            f"WARNING: docker not available -- memory-only backup (Qdrant not included){hint}",
            err=True,
        )
        return artifacts

    if not container_state:
        click.echo(
            "WARNING: rekall-qdrant container not running -- memory-only backup"
            " (Qdrant not included)",
            err=True,
        )
        return artifacts

    qdrant_data = _resolve_path("QDRANT_DATA_PATH", "~/.claude/qdrant")
    qdrant_tar = out_dir / f"rekall-{ts}-qdrant.tar.gz"

    stop_error: str | None = None
    tar_error: str | None = None
    restart_error: str | None = None

    try:
        try:
            stop_result = subprocess.run(
                ["docker", "stop", "rekall-qdrant"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            stop_error = str(exc)
        else:
            if stop_result.returncode != 0:
                stop_error = stop_result.stderr.strip() or "non-zero exit"
            else:
                try:
                    _make_tarball(qdrant_data, qdrant_tar)
                except Exception as exc:
                    tar_error = str(exc)
    finally:
        try:
            start_result = subprocess.run(
                ["docker", "start", "rekall-qdrant"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if start_result.returncode != 0:
                restart_error = (
                    start_result.stderr.strip() or start_result.stdout.strip() or "non-zero exit"
                )
        except Exception as _start_exc:
            restart_error = str(_start_exc)

    if restart_error:
        click.echo(
            f"ERROR: rekall-qdrant failed to restart after backup: {restart_error}",
            err=True,
        )
        if tar_error:
            click.echo(f"ERROR: Qdrant tarball also failed: {tar_error}", err=True)
        raise _BackupError(f"Qdrant restart failed: {restart_error}")

    if stop_error:
        raise _BackupError(f"docker stop failed: {stop_error}")

    if tar_error:
        raise _BackupError(f"Qdrant tarball failed: {tar_error}")

    if not _verify_tarball(qdrant_tar):
        raise _BackupError(f"Qdrant tarball verification failed: {qdrant_tar}")

    artifacts.append(qdrant_tar)
    return artifacts


@memory.command()
@click.option("--out", "out_dir", default=None, help="Output directory (default: ~/backups)")
def backup(out_dir: str | None):
    """Backup memory and Qdrant data to tarballs.

    Creates rekall-YYYYmmdd-HHMMSS-memory.tar.gz and (when Qdrant is running)
    rekall-YYYYmmdd-HHMMSS-qdrant.tar.gz in the output directory.
    Qdrant is stopped for consistency, then always restarted in a finally block.
    """
    dest = Path(out_dir).expanduser() if out_dir else Path.home() / "backups"
    try:
        artifacts = _do_backup(dest)
    except _BackupError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)
    for artifact in artifacts:
        click.echo(str(artifact))


@memory.command()
@click.option("--dry-run", is_flag=True, default=False, help="Preview without making changes")
@click.option(
    "--no-backup",
    is_flag=True,
    default=False,
    help="Skip automatic backup (not recommended for live data)",
)
def migrate(dry_run: bool, no_backup: bool):
    """Migrate Qdrant collection to hybrid search schema.

    By default, creates a fresh backup before migrating.
    --dry-run previews without modifying data (implies no backup).
    --no-backup skips the backup step.
    """
    backup_needed = not dry_run and not no_backup
    if backup_needed:
        dest = Path.home() / "backups"
        try:
            artifacts = _do_backup(dest)
            for artifact in artifacts:
                click.echo(f"Backup: {artifact}")
        except _BackupError as exc:
            click.echo(f"ERROR: Backup failed before migrate: {exc}", err=True)
            sys.exit(1)

    memory_dir = _resolve_path("MEMORY_STORAGE_PATH", "~/.claude/memory")
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")

    try:
        result = migrate_to_hybrid(
            memory_dir=memory_dir,
            qdrant_url=qdrant_url,
            dry_run=dry_run,
        )
    except Exception as exc:
        click.echo(f"ERROR: Migration failed: {exc}", err=True)
        sys.exit(1)

    click.echo(json.dumps(result, indent=2))

    if result.get("status") not in ("complete", "dry_run"):
        sys.exit(1)


def _find_install_sh(start_dir: Path | None = None) -> Path | None:
    """Walk up from start_dir (default: cwd) to locate claude/setup/install.sh."""
    cur = start_dir if start_dir is not None else Path.cwd()
    while True:
        candidate = cur / "claude" / "setup" / "install.sh"
        if candidate.is_file():
            return candidate
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


@memory.command("install-claude")
@click.option("--skills-only", is_flag=True, default=False)
@click.option("--hooks-only", is_flag=True, default=False)
@click.option("--skip-backend", is_flag=True, default=False)
def install_claude(skills_only: bool, hooks_only: bool, skip_backend: bool):
    """Install the Claude Code bundle (hooks, slash commands, settings)."""
    install_sh = _find_install_sh()
    if install_sh is None:
        click.echo(
            "install-claude requires a rekall-mcp repo checkout."
            " Run: bash <repo>/claude/setup/install.sh",
            err=True,
        )
        sys.exit(1)
    cmd = ["bash", str(install_sh)]
    if skills_only:
        cmd.append("--skills-only")
    if hooks_only:
        cmd.append("--hooks-only")
    if skip_backend:
        cmd.append("--skip-backend")
    proc = subprocess.run(cmd)
    sys.exit(proc.returncode)


@memory.command()
def serve():
    """Run the rekall daemon (streamable-http) over the embedded store.

    Loopback-only by default; PORT env (default 8000) picks the port.
    QDRANT_URL switches to server-backed Qdrant instead of the embedded store.
    """
    os.environ["MCP_TRANSPORT"] = "streamable-http"
    os.environ.setdefault("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    rekall_dir = Path(os.environ.get("REKALL_DIR", str(Path.home() / ".rekall"))).expanduser()

    from core import ownership

    if os.environ.get("QDRANT_URL"):
        # Server-backed Qdrant: no embedded lock to take — just refuse a taken port.
        state = ownership.probe_daemon(f"http://127.0.0.1:{port}")
        if state == "rekall":
            click.echo(
                f"ERROR: a rekall daemon is already running on port {port} — "
                "use it, or stop it first.",
                err=True,
            )
            sys.exit(2)
        if state == "foreign":
            click.echo(
                f"ERROR: something that isn't rekall answers on port {port} — set PORT.",
                err=True,
            )
            sys.exit(2)
    else:
        os.environ.setdefault("QDRANT_PATH", str(rekall_dir / "qdrant"))
        try:
            acq = ownership.acquire(rekall_dir, port=port)
        except ownership.RekallOwnershipError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            sys.exit(2)
        if acq.mode == "daemon":
            click.echo(
                f"ERROR: a rekall daemon is already running at {acq.base_url} — "
                "use it, or stop it first.",
                err=True,
            )
            sys.exit(2)

    from server import main as server_main

    server_main()


@memory.command()
@click.option(
    "--tarball-dir",
    default=None,
    help="Where to write the pre-reindex tarballs (default: ~/backups)",
)
def reindex(tarball_dir: str | None):
    """Rebuild the vector store from YAML: tarball -> rebuild -> verify -> graph.

    Embedded store by default; QDRANT_URL switches to server-backed Qdrant.
    Refuses to run while a rekall daemon owns the store.
    """
    port = int(os.environ.get("PORT", "8000"))
    rekall_dir = Path(os.environ.get("REKALL_DIR", str(Path.home() / ".rekall"))).expanduser()
    memory_dir = os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")

    from core import ownership

    daemon_msg = (
        "ERROR: rekall daemon is running — this command would bypass it; "
        "stop the daemon or use the MCP/REST interface"
    )
    if os.environ.get("QDRANT_URL"):
        if ownership.probe_daemon(f"http://127.0.0.1:{port}") == "rekall":
            click.echo(daemon_msg, err=True)
            sys.exit(2)
        mgr = MemoryManager(memory_dir=memory_dir, qdrant_url=os.environ["QDRANT_URL"])
    else:
        try:
            acq = ownership.acquire(rekall_dir, port=port)
        except ownership.RekallOwnershipError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            sys.exit(2)
        if acq.mode == "daemon":
            click.echo(daemon_msg, err=True)
            sys.exit(2)
        mgr = MemoryManager(memory_dir=memory_dir, qdrant_path=str(acq.path))

    from .reindex import reindex as run_reindex

    dest = Path(tarball_dir).expanduser() if tarball_dir else None
    result = run_reindex(mgr, tarball_dir=dest)
    click.echo(json.dumps(result, indent=2))


@memory.command()
def warmup():
    """Download and prime the embedding model (one encode)."""
    import tempfile

    from core import embeddings

    embedder = embeddings.Embedder()
    embedder.encode("warmup")

    if embedder.provider_name == "fastembed":
        # fastembed's define_cache_dir: FASTEMBED_CACHE_PATH env or <tmpdir>/fastembed_cache.
        cache = os.environ.get(
            "FASTEMBED_CACHE_PATH", str(Path(tempfile.gettempdir()) / "fastembed_cache")
        )
    else:
        cache = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    click.echo(
        f"✓ Embedder ready ({embedder.provider_name}, {embedder.model_name}) — model cache: {cache}"
    )


@memory.command()
@click.option(
    "--clean",
    "clean_flag",
    is_flag=True,
    default=False,
    help="Remove the seeded demo memories (manifest ids only)",
)
@click.option(
    "--force-into-real-store",
    is_flag=True,
    default=False,
    help="Seed into a non-empty existing store anyway",
)
def demo(clean_flag: bool, force_into_real_store: bool):
    """Seed 20 sample memories into an isolated demo store and print starter queries.

    Defaults to its own store under ~/.rekall/demo — never the real one.
    MEMORY_STORAGE_PATH redirects the target; a non-empty store that isn't a
    rekall demo is refused without --force-into-real-store.
    """
    from . import demo_seed

    env_memory = os.environ.get("MEMORY_STORAGE_PATH")
    if env_memory:
        memory_dir = Path(env_memory).expanduser()
        demo_dir = memory_dir.parent
        manager_kwargs: dict = {"memory_dir": memory_dir}  # qdrant resolves from env
    else:
        rekall_dir = Path(os.environ.get("REKALL_DIR", str(Path.home() / ".rekall"))).expanduser()
        demo_dir = rekall_dir / "demo"
        memory_dir = demo_dir / "memory"
        manager_kwargs = {"memory_dir": memory_dir, "qdrant_path": str(demo_dir / "qdrant")}

    manifest = demo_dir / demo_seed.MANIFEST_NAME

    if clean_flag:
        if not manifest.exists():
            click.echo(f"ERROR: no demo manifest at {manifest} — nothing to clean.", err=True)
            sys.exit(1)
        deleted = demo_seed.clean(MemoryManager(**manager_kwargs), manifest)
        click.echo(f"✓ Removed {deleted} demo memories (manifest: {manifest})")
        return

    non_demo_store = (
        not manifest.exists() and memory_dir.is_dir() and any(memory_dir.rglob("*.yaml"))
    )
    if non_demo_store and not force_into_real_store:
        click.echo(
            f"ERROR: {memory_dir} already holds memories that aren't a rekall demo — "
            "refusing to mix demo data in; pass --force-into-real-store to override.",
            err=True,
        )
        sys.exit(2)

    ids = demo_seed.seed(MemoryManager(**manager_kwargs), demo_dir)
    click.echo(f"✓ Seeded {len(ids)} demo memories into {memory_dir}")
    click.echo(f"  manifest: {manifest}")
    click.echo("\nTry these recall queries:")
    for query in demo_seed.SUGGESTED_QUERIES:
        click.echo(f'  • "{query}"')
    click.echo("\nClean up with: rekall demo --clean")


def main():
    """Entry point."""
    memory()


if __name__ == "__main__":
    main()
