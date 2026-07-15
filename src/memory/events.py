from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.utils import assert_test_isolation

logger = logging.getLogger(__name__)

_READ_CHUNK = 65536


class CursorError(ValueError):
    """Cursor string is not decodable — client error, not a log rewrite."""


def _line_sig(first_line: bytes, size: int) -> str:
    return f"{hashlib.sha256(first_line).hexdigest()[:12]}:{size}"


def _encode_cursor(offset: int, sig: str) -> str:
    raw = json.dumps({"offset": offset, "sig": sig}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[int, str, int]:
    """Return (offset, first_line_hash, size_at_issue)."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        offset = int(data["offset"])
        line_hash, size_at_issue = str(data["sig"]).rsplit(":", 1)
        return offset, line_hash, int(size_at_issue)
    except Exception as e:  # noqa: BLE001
        raise CursorError(f"invalid cursor: {e}") from None


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

    def read_from(
        self, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[MemoryEvent], str, bool]:
        """Cursor-paginated read. Returns (events, next_cursor, truncated).

        The cursor is opaque: {offset, sig} where sig = sha256(first_line)[:12]
        + ":" + size_at_issue. It advances only past newline-terminated lines
        (concurrent appends are safe). A sig mismatch or shrunken file means
        the log was rewritten → fresh tail + truncated=True instead of garbage.
        Cursor reads are O(new bytes); the initial/no-cursor call reads the
        whole file to serve a bounded tail.
        """
        if cursor is None:
            return self._fresh_tail(limit, truncated=False)

        offset, line_hash, size_at_issue = _decode_cursor(cursor)
        size, first_line = self._stat_first_line()

        stale = (
            offset > size
            or size < size_at_issue
            or (size_at_issue > 0 and _line_sig(first_line, 0).split(":")[0] != line_hash)
        )
        if stale:
            return self._fresh_tail(limit, truncated=True)

        events, new_offset = self._read_complete_lines(offset, limit)
        return events, _encode_cursor(new_offset, _line_sig(first_line, size)), False

    def _stat_first_line(self) -> tuple[int, bytes]:
        if not self.path.exists():
            return 0, b""
        size = self.path.stat().st_size
        with self.path.open("rb") as file:
            return size, file.readline()

    def _read_complete_lines(self, offset: int, limit: int) -> tuple[list[MemoryEvent], int]:
        events: list[MemoryEvent] = []
        with self.path.open("rb") as file:
            file.seek(offset)
            buffer = b""
            while len(events) < limit:
                chunk = file.read(_READ_CHUNK)
                if not chunk:
                    break
                buffer += chunk
                while len(events) < limit:
                    newline = buffer.find(b"\n")
                    if newline == -1:
                        break
                    line, buffer = buffer[: newline + 1], buffer[newline + 1 :]
                    offset += len(line)
                    event = self._parse_line(line)
                    if event is not None:
                        events.append(event)
        return events, offset

    def _fresh_tail(self, limit: int, *, truncated: bool) -> tuple[list[MemoryEvent], str, bool]:
        data = self.path.read_bytes() if self.path.exists() else b""
        end = data.rfind(b"\n") + 1  # 0 when no complete line exists
        first_line = data[: data.find(b"\n") + 1] if end else data

        events: list[MemoryEvent] = []
        for line in data[:end].splitlines(keepends=True)[-limit:]:
            event = self._parse_line(line)
            if event is not None:
                events.append(event)
        return events, _encode_cursor(end, _line_sig(first_line, len(data))), truncated

    def _parse_line(self, line: bytes) -> MemoryEvent | None:
        if not line.strip():
            return None
        try:
            return MemoryEvent(**json.loads(line))
        except (ValueError, TypeError):
            logger.warning("skipping malformed event line: %r", line[:200])
            return None
