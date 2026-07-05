"""CLI for memory system."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import click

from .capsules import render_project_capsule
from .doctor import run_memory_doctor
from .manager import MemoryManager
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
    ctx.obj["manager"] = MemoryManager(
        memory_dir=memory_dir,
        qdrant_url=qdrant_url,
    )


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
    mgr: MemoryManager = ctx.obj["manager"]
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
    mgr: MemoryManager = ctx.obj["manager"]
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
    mgr: MemoryManager = ctx.obj["manager"]
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
    mgr: MemoryManager = ctx.obj["manager"]

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
    mgr: MemoryManager = ctx.obj["manager"]
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
    mgr: MemoryManager = ctx.obj["manager"]
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


def main():
    """Entry point."""
    memory()


if __name__ == "__main__":
    main()
