"""Memory auto-compaction — summarize old memories using an LLM.

Groups memories older than N days by project+type, summarizes each group
into a single compact memory, marks originals as compacted in YAML (kept
for history), and removes them from Qdrant.

YAML fields added to compacted memories:
    compacted: true
    compacted_into: <summary_memory_id>

Usage:
    from memory.compact import compact_memories

    # Dry run — preview only
    result = compact_memories(memories, dry_run=True, older_than_days=30)

    # Execute with Anthropic
    result = compact_memories(
        memories,
        dry_run=False,
        older_than_days=30,
        manager=manager,
        llm_provider="anthropic",
    )
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

COMPACTION_PROMPT = """\
You are compressing old memories into concise summaries.

Project: {project}
Type: {type}
Memories (oldest first):
{memories}

Write a 1-2 sentence summary preserving:
- Key decisions and their rationale
- Important learnings and gotchas
- Critical requirements

Summary:"""


def group_memories(memories: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Group memories by (project, type).

    Args:
        memories: List of memory dicts

    Returns:
        Dict mapping (project, type) -> list of memories
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for mem in memories:
        key = (mem.get("project", "general"), mem.get("type", "note"))
        groups.setdefault(key, []).append(mem)

    return groups


def select_old_memories(
    memories: list[dict[str, Any]],
    older_than_days: int = 30,
) -> list[dict[str, Any]]:
    """Filter to memories older than threshold, excluding already-compacted and summaries.

    Args:
        memories: All memory dicts
        older_than_days: Age cutoff in days

    Returns:
        Memories eligible for compaction
    """
    cutoff = (datetime.now() - timedelta(days=older_than_days)).strftime("%Y-%m-%d")

    return [
        m
        for m in memories
        if (
            m.get("date", "9999") <= cutoff
            and not m.get("compacted")
            and m.get("type") != "summary"
        )
    ]


def build_compaction_prompt(
    memories: list[dict[str, Any]],
    project: str,
    mem_type: str,
    template: str | None = None,
) -> str:
    """Build LLM prompt for summarizing a group of memories.

    Args:
        memories: Memories to summarize (same project+type)
        project: Project name
        mem_type: Memory type
        template: Custom prompt template (must have {project}, {type}, {memories})

    Returns:
        Formatted prompt string
    """
    memories_text = "\n".join(
        f"- [{m.get('date', '')}] {m.get('content', '')}"
        for m in sorted(memories, key=lambda m: m.get("date", ""))
    )

    tmpl = template or COMPACTION_PROMPT
    return tmpl.format(project=project, type=mem_type, memories=memories_text)


def mark_compacted_in_yaml(
    memory_dir: Path | str,
    memory_ids: set[str],
    summary_id: str,
) -> None:
    """Mark memories as compacted in YAML files.

    Adds compacted=True and compacted_into=<summary_id> to each memory
    whose ID is in memory_ids. Does NOT remove them (kept for history).

    Args:
        memory_dir: Directory containing YAML files
        memory_ids: Set of memory IDs to mark as compacted
        summary_id: ID of the summary memory they were compacted into
    """
    memory_dir = Path(memory_dir)

    for yaml_file in memory_dir.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue

        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to read {yaml_file}: {e}")
            continue

        modified = False

        for key, items in data.items():
            if key == "date" or not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("id") in memory_ids:
                    item["compacted"] = True
                    item["compacted_into"] = summary_id
                    modified = True

        if modified:
            # Atomic write
            fd, tmp_path = tempfile.mkstemp(dir=memory_dir, suffix=".yaml.tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    yaml.dump(
                        data, f, default_flow_style=False, sort_keys=False, allow_unicode=True
                    )
                os.replace(tmp_path, yaml_file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise


async def _summarize_with_llm(
    prompt: str,
    llm_provider: str = "anthropic",
    model: str | None = None,
) -> str:
    """Call an LLM to produce a compaction summary.

    Args:
        prompt: Full prompt to send
        llm_provider: "anthropic" or "openai"
        model: Model override (uses provider default if None)

    Returns:
        Summary text
    """
    if llm_provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic()
        resp = await client.messages.create(
            model=model or "claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()

    elif llm_provider == "openai":
        import openai

        client = openai.AsyncOpenAI()
        resp = await client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()

    else:
        raise ValueError(f"Unknown llm_provider: {llm_provider!r}. Use 'anthropic' or 'openai'.")


def compact_memories(
    memories: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    older_than_days: int = 30,
    manager: Any | None = None,
    llm_provider: str = "anthropic",
    model: str | None = None,
    memory_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Compact old memories by summarizing groups with an LLM.

    In dry_run mode: returns preview stats without making changes.
    In execute mode: requires manager + memory_dir, calls LLM, updates YAML + Qdrant.

    Args:
        memories: All memory dicts to consider
        dry_run: If True, preview only (no changes)
        older_than_days: Age threshold for compaction
        manager: MemoryManager instance (required for execute mode)
        llm_provider: "anthropic" or "openai"
        model: LLM model override
        memory_dir: YAML directory (required for execute mode)

    Returns:
        Dict with: dry_run, groups, memories_to_compact, summaries_created
    """
    old = select_old_memories(memories, older_than_days=older_than_days)
    groups = group_memories(old)

    if dry_run:
        return {
            "dry_run": True,
            "groups": len(groups),
            "memories_to_compact": len(old),
            "summaries_created": 0,
            "older_than_days": older_than_days,
        }

    # Execute mode — requires manager and memory_dir
    if manager is None:
        raise ValueError("manager is required for execute mode")
    if memory_dir is None:
        raise ValueError("memory_dir is required for execute mode")

    import asyncio

    summaries_created = 0
    total_compacted = 0

    for (project, mem_type), group_mems in groups.items():
        if not group_mems:
            continue

        prompt = build_compaction_prompt(group_mems, project=project, mem_type=mem_type)

        try:
            summary_text = asyncio.run(
                _summarize_with_llm(prompt, llm_provider=llm_provider, model=model)
            )
        except Exception as e:
            logger.error(f"LLM summarization failed for ({project}, {mem_type}): {e}")
            continue

        # Save summary as new memory
        summary_id = manager.save(
            content=summary_text,
            type="summary",
            project=project,
            compacted_from=[m.get("memory_id", "") for m in group_mems],
        )

        # Mark originals as compacted in YAML
        compacted_ids = {m.get("memory_id", "") for m in group_mems if m.get("memory_id")}
        mark_compacted_in_yaml(
            memory_dir=memory_dir,
            memory_ids=compacted_ids,
            summary_id=summary_id,
        )

        # Remove originals from Qdrant (keep in YAML for history)
        for mem_id in compacted_ids:
            try:
                manager.store.delete(filters={"memory_id": mem_id})
            except Exception as e:
                logger.warning(f"Failed to remove {mem_id} from Qdrant: {e}")

        summaries_created += 1
        total_compacted += len(group_mems)
        logger.info(f"Compacted {len(group_mems)} ({project}/{mem_type}) → {summary_id}")

    return {
        "dry_run": False,
        "groups": len(groups),
        "memories_to_compact": len(old),
        "summaries_created": summaries_created,
        "memories_compacted": total_compacted,
        "older_than_days": older_than_days,
    }
