"""Briefing engine - Jarvis mode.

Aggregates pending items, recent memories, and external data (Jira, GitLab)
into actionable briefings at session start.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tools.base import BaseToolProvider, ToolDefinition

# Pattern to match YYYY-MM-DD date format
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BriefingTools(BaseToolProvider):
    """Tool provider for session and daily briefings."""

    name = "briefing"
    description = "Proactive briefing engine for session start and daily summaries"
    requires: list[str] = []
    builtin = True

    def __init__(self):
        self._storage_path: Path | None = None

    @property
    def storage_path(self) -> Path:
        if self._storage_path is None:
            self._storage_path = Path(
                os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")
            ).expanduser()
        return self._storage_path

    def _load_pending(self) -> list[dict]:
        pending_file = self.storage_path / "pending.yaml"
        if not pending_file.exists():
            return []
        with open(pending_file) as f:
            data = yaml.safe_load(f) or {}
        return [i for i in data.get("items", []) if i.get("status") == "open"]

    def _get_recent_memories(self, days: int = 3) -> list[dict]:
        """Get memories from the last N days."""
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        memories = []
        for yaml_file in sorted(self.storage_path.glob("*.yaml"), reverse=True):
            # Only process files with YYYY-MM-DD date format stems
            if not _DATE_PATTERN.match(yaml_file.stem):
                continue
            if yaml_file.stem < cutoff:
                break
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                for type_key in data:
                    if type_key.endswith("s") and isinstance(data[type_key], list):
                        for mem in data[type_key]:
                            mem["_type"] = type_key[:-1]
                            memories.append(mem)
            except Exception:
                continue
        return memories

    def _run_cmd(self, cmd: list[str], timeout: int = 10) -> str | None:
        """Run a shell command, return stdout or None on failure."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _get_jira_items(self) -> str | None:
        """Pull assigned Jira tickets via acli."""
        return self._run_cmd(
            [
                "acli",
                "jira",
                "workitem",
                "list",
                "--assignee",
                "@me",
                "--status",
                "In Progress,To Do",
                "--format",
                "json",
            ],
            timeout=15,
        )

    def _get_gitlab_mrs(self) -> str | None:
        """Pull open MRs authored by me via glab."""
        return self._run_cmd(
            [
                "glab",
                "mr",
                "list",
                "--author",
                "@me",
                "--state",
                "opened",
                "--output",
                "json",
            ],
            timeout=15,
        )

    def _format_jira(self, raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            tickets = json.loads(raw)
            if not tickets:
                return []
            lines = []
            for t in tickets[:10]:
                key = t.get("key", "?")
                summary = t.get("fields", {}).get("summary", t.get("summary", "?"))
                status = t.get("fields", {}).get("status", {}).get("name", "?")
                lines.append(f"- **{key}**: {summary} ({status})")
            return lines
        except (json.JSONDecodeError, TypeError):
            return []

    def _format_mrs(self, raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            mrs = json.loads(raw)
            if not mrs:
                return []
            lines = []
            for mr in mrs[:10]:
                title = mr.get("title", "?")
                url = mr.get("web_url", "")
                state = mr.get("merge_status", mr.get("detailed_merge_status", ""))
                lines.append(f"- **{title}** ({state}) {url}")
            return lines
        except (json.JSONDecodeError, TypeError):
            return []

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="session_briefing",
                description=(
                    "Quick briefing for session start: pending items, overdue tasks, "
                    "recent findings. Fast, no external calls."
                ),
                handler=self._session_briefing,
            ),
            ToolDefinition(
                name="daily_briefing",
                description=(
                    "Full Jarvis briefing: pending items, Jira tickets, GitLab MRs, "
                    "recent memories, overdue tasks. Calls external APIs."
                ),
                handler=self._daily_briefing,
            ),
        ]

    async def _session_briefing(self, project: str | None = None) -> str:
        """Fast briefing - local data only, no external calls."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sections = []

        pending = self._load_pending()
        overdue = [i for i in pending if i.get("due_date") and i["due_date"] < today]

        if overdue:
            section = ["## OVERDUE\n"]
            for item in overdue:
                ticket = f" [{item['ticket_id']}]" if item.get("ticket_id") else ""
                section.append(f"- **{item['id']}**{ticket}: {item['title']} (was due {item['due_date']})")
            sections.append("\n".join(section))

        if pending:
            upcoming = [i for i in pending if i not in overdue][:5]
            if upcoming:
                section = ["## Pending\n"]
                for item in upcoming:
                    due = f" (due {item['due_date']})" if item.get("due_date") else ""
                    ticket = f" [{item['ticket_id']}]" if item.get("ticket_id") else ""
                    section.append(f"- **{item['id']}**{ticket}: {item['title']}{due}")
                sections.append("\n".join(section))

        recent = self._get_recent_memories(days=2)
        if recent:
            notable = [m for m in recent if m.get("_type") in ("decision", "learning", "requirement")][:5]
            if notable:
                section = ["## Recent Findings\n"]
                for mem in notable:
                    content = mem.get("content", "")[:100]
                    section.append(f"- [{mem.get('_type', '?')}] {content}")
                sections.append("\n".join(section))

        if not sections:
            return "All clear. No pending items or recent findings."

        header = f"# Session Briefing ({today})\n"
        return header + "\n\n".join(sections)

    async def _daily_briefing(self, project: str | None = None) -> str:
        """Full briefing with external integrations."""
        base = await self._session_briefing(project=project)
        sections = [base]

        jira_raw = self._get_jira_items()
        jira_lines = self._format_jira(jira_raw)
        if jira_lines:
            sections.append("## Jira Tickets (Assigned)\n\n" + "\n".join(jira_lines))

        mr_raw = self._get_gitlab_mrs()
        mr_lines = self._format_mrs(mr_raw)
        if mr_lines:
            sections.append("## Open MRs\n\n" + "\n".join(mr_lines))

        return "\n\n---\n\n".join(sections)
