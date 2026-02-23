"""Tests for the memory graph endpoint helpers."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.responses import JSONResponse


class QueryParams:
    """Minimal query param object with `.get(key)` like Starlette."""

    def __init__(self, values: dict[str, str | None]):
        self._values = values

    def get(self, key: str, default: str | None = None):
        return self._values.get(key, default)


def test_parse_graph_filters_includes_expected_fields():
    """Graph filters should include project/type and date cutoff."""
    from server import _parse_graph_filters

    now = datetime.now().strftime("%Y-%m-%d")
    query = QueryParams({"project": "api", "type": "decision", "days": "7"})

    filters = _parse_graph_filters(query)

    expected_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    assert filters["project"] == "api"
    assert filters["type"] == "decision"
    assert filters["date"]["gte"] == expected_cutoff
    assert filters["date"]["gte"] <= now


def test_parse_graph_filters_without_days_has_no_date_filter():
    """Date filter should be omitted when days is not provided."""
    from server import _parse_graph_filters

    filters = _parse_graph_filters(QueryParams({"project": "api"}))

    assert filters["project"] == "api"
    assert "date" not in filters


@pytest.mark.asyncio
async def test_api_consolidate_memories_endpoint(monkeypatch):
    """Consolidation endpoint should parse query params and return summary."""
    from server import api_consolidate_memories

    manager = MagicMock()
    manager.consolidate_memories.return_value = "## Conflicting Memories\n- none"

    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(
        query_params=QueryParams(
            {"project": "api", "limit": "50", "save_summary": "true"},
        )
    )

    response = await api_consolidate_memories(request)  # type: ignore[arg-type]
    assert isinstance(response, JSONResponse)

    payload = json.loads(response.body)
    assert payload["project"] == "api"
    assert payload["summary"] == "## Conflicting Memories\n- none"
    assert payload["limit"] == 50
    assert payload["save_summary"] is True

    manager.consolidate_memories.assert_called_once_with(project="api", limit=50, save_summary=True)


@pytest.mark.asyncio
async def test_api_proactive_context_summary_endpoint(monkeypatch):
    """Proactive summary endpoint should return summary payload."""
    from server import api_proactive_context_summary

    manager = MagicMock()
    manager.get_proactive_context_summary.return_value = "# Proactive Context"

    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(query_params=QueryParams({"project": "api", "limit": "11"}))
    response = await api_proactive_context_summary(request)  # type: ignore[arg-type]
    assert isinstance(response, JSONResponse)

    payload = json.loads(response.body)
    assert payload["project"] == "api"
    assert payload["summary"] == "# Proactive Context"
    assert payload["limit"] == 11

    manager.get_proactive_context_summary.assert_called_once_with(project="api", limit=11)


@pytest.mark.asyncio
async def test_api_skill_context_endpoint(monkeypatch):
    """Skill context endpoint should return skill summary payload."""
    from server import api_skill_context

    manager = MagicMock()
    manager.get_skill_context.return_value = "# Skill Context: api\n\n## postgresql (5 mentions)"

    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(
        query_params=QueryParams({"project": "api", "min_mentions": "3", "max_skills": "5"})
    )
    response = await api_skill_context(request)  # type: ignore[arg-type]
    assert isinstance(response, JSONResponse)

    payload = json.loads(response.body)
    assert payload["project"] == "api"
    assert payload["summary"].startswith("# Skill Context")
    assert payload["min_mentions"] == 3
    assert payload["max_skills"] == 5

    manager.get_skill_context.assert_called_once_with(
        project="api", min_mentions=3, max_skills=5
    )


@pytest.mark.asyncio
async def test_api_skill_context_defaults(monkeypatch):
    """Skill context endpoint should use sane defaults."""
    from server import api_skill_context

    manager = MagicMock()
    manager.get_skill_context.return_value = "# Skill Context: all"

    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(query_params=QueryParams({}))
    response = await api_skill_context(request)  # type: ignore[arg-type]
    payload = json.loads(response.body)
    assert payload["project"] == "all"
    assert payload["min_mentions"] == 2
    assert payload["max_skills"] == 8

    manager.get_skill_context.assert_called_once_with(
        project=None, min_mentions=2, max_skills=8
    )


@pytest.mark.asyncio
async def test_api_rebuild_graph_endpoint(monkeypatch):
    """Graph rebuild endpoint should expose rebuild stats."""
    from server import api_rebuild_memory_graph

    manager = MagicMock()
    manager.knowledge_graph.rebuild.return_value = {
        "nodes": 10,
        "edges": 3,
        "duration_ms": 42,
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace()
    response = await api_rebuild_memory_graph(request)  # type: ignore[arg-type]

    assert isinstance(response, JSONResponse)
    payload = json.loads(response.body)
    assert payload == {
        "status": "rebuilt",
        "nodes": 10,
        "edges": 3,
        "duration_ms": 42,
    }
