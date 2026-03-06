"""Pending items tracker - Jarvis mode.

Tracks tasks, follow-ups, tickets, and reminders with due dates.
Storage: ~/.claude/memory/pending.yaml
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tools.base import BaseToolProvider, ToolDefinition


class TrackerTools(BaseToolProvider):
    """Provider for tracking pending items and reminders."""

    name = "tracker"
    description = "Pending items tracker with due dates and status"
    requires: list[str] = []
    builtin = True

    def __init__(self):
        self._storage_path: Path | None = None

    @property
    def storage_path(self) -> Path:
        if self._storage_path is None:
            self._storage_path = Path(
                os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")
            ).expanduser() / "pending.yaml"
        return self._storage_path

    def _load_items(self) -> list[dict]:
        if not self.storage_path.exists():
            return []
        with open(self.storage_path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("items", [])

    def _save_items(self, items: list[dict]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w") as f:
            yaml.dump({"items": items}, f, default_flow_style=False, sort_keys=False)

    def _next_id(self, items: list[dict]) -> str:
        existing = [i.get("id", "") for i in items]
        n = 1
        while f"TODO-{n:03d}" in existing:
            n += 1
        return f"TODO-{n:03d}"

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="track_item",
                description=(
                    "Track a pending item (task, follow-up, reminder). "
                    "Provide title, optional due_date (YYYY-MM-DD), optional "
                    "context, optional ticket_id (e.g. TOPE-123)."
                ),
                handler=self._track_item,
            ),
            ToolDefinition(
                name="complete_item",
                description="Mark a pending item as done by its ID (e.g. TODO-001).",
                handler=self._complete_item,
            ),
            ToolDefinition(
                name="get_pending",
                description=(
                    "List all pending (open) items. "
                    "Optionally filter by overdue=true to see only overdue items."
                ),
                handler=self._get_pending,
            ),
            ToolDefinition(
                name="defer_item",
                description=(
                    "Defer a pending item to a new due date. "
                    "Provide item ID and new_date (YYYY-MM-DD)."
                ),
                handler=self._defer_item,
            ),
        ]

    async def _track_item(
        self,
        title: str,
        due_date: str | None = None,
        context: str | None = None,
        ticket_id: str | None = None,
        priority: str = "normal",
    ) -> str:
        items = self._load_items()
        item_id = self._next_id(items)
        now = datetime.now(timezone.utc).isoformat()

        item = {
            "id": item_id,
            "title": title,
            "status": "open",
            "priority": priority,
            "created": now,
        }
        if due_date:
            item["due_date"] = due_date
        if context:
            item["context"] = context
        if ticket_id:
            item["ticket_id"] = ticket_id

        items.append(item)
        self._save_items(items)
        return (
            f"Tracked: {item_id} - {title}"
            + (f" (due {due_date})" if due_date else "")
        )

    async def _complete_item(self, item_id: str) -> str:
        items = self._load_items()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "done"
                item["completed"] = datetime.now(timezone.utc).isoformat()
                self._save_items(items)
                return f"Completed: {item_id} - {item['title']}"
        return f"Item not found: {item_id}"

    async def _get_pending(self, overdue: bool = False) -> str:
        items = self._load_items()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pending = [i for i in items if i["status"] == "open"]

        if overdue:
            pending = [
                i for i in pending
                if i.get("due_date") and i["due_date"] < today
            ]

        if not pending:
            return "No pending items." if not overdue else "No overdue items."

        lines = ["# Pending Items\n"]
        for item in sorted(pending, key=lambda x: x.get("due_date", "9999-99-99")):
            marker = ""
            if item.get("due_date") and item["due_date"] < today:
                marker = " **OVERDUE**"
            due = f" (due {item['due_date']})" if item.get("due_date") else ""
            ticket = f" [{item['ticket_id']}]" if item.get("ticket_id") else ""
            lines.append(f"- **{item['id']}**{ticket}: {item['title']}{due}{marker}")
            if item.get("context"):
                lines.append(f"  _{item['context']}_")

        return "\n".join(lines)

    async def _defer_item(self, item_id: str, new_date: str) -> str:
        items = self._load_items()
        for item in items:
            if item["id"] == item_id:
                old_date = item.get("due_date", "none")
                item["due_date"] = new_date
                self._save_items(items)
                return f"Deferred: {item_id} from {old_date} to {new_date}"
        return f"Item not found: {item_id}"
