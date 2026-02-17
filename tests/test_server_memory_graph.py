"""Tests for the memory graph endpoint helpers."""

from datetime import datetime, timedelta


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
