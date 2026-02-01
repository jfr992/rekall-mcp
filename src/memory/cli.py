"""CLI for memory system."""

from __future__ import annotations

import click

from .manager import MemoryManager


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
    type=click.Choice(["note", "decision", "learning", "preference", "session"]),
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
    memory_id = mgr.save_memory(content, memory_type=memory_type, project=project)
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
        memory_type=memory_type,
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
    mgr.clear_project(project)
    click.echo(f"✓ Cleared memories for: {project}")


def main():
    """Entry point."""
    memory()


if __name__ == "__main__":
    main()
