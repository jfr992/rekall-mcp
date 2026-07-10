from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.utils import assert_test_isolation


@dataclass(frozen=True, slots=True)
class MemoryEvent:
    event_type: str
    project: str
    agent: str
    source: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    observed_at: str = field(default_factory=lambda: datetime.now().isoformat())


class EventLog:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        assert_test_isolation(storage_path=self.path)

    def append(self, event: MemoryEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    def tail(self, limit: int = 50) -> list[MemoryEvent]:
        if not self.path.exists():
            return []

        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        events: list[MemoryEvent] = []
        for line in lines:
            if not line.strip():
                continue
            events.append(MemoryEvent(**json.loads(line)))
        return events
