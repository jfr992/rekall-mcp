"""Tests for cache context helpers."""

import yaml

from memory.cache_context import CacheableContext


def test_hierarchical_context_builds_topic_sections(tmp_path):
    """Hierarchical context should return topic headings from saved YAML memories."""
    storage = tmp_path / "memory"
    storage.mkdir()
    date = "2026-02-24"
    yaml_file = storage / f"{date}.yaml"

    payload = {
        "date": date,
        "decisions": [
            {
                "id": "m1",
                "content": "PostgreSQL query index strategy",
                "project": "api",
                "timestamp": f"{date}T10:00:00",
            }
        ],
        "notes": [
            {
                "id": "m2",
                "content": "API button layout defaults",
                "project": "api",
                "timestamp": f"{date}T11:00:00",
            }
        ],
    }
    yaml_file.write_text(yaml.dump(payload))

    ctx = CacheableContext(
        project="api",
        storage_path=str(storage),
        include_types=["requirement", "fact", "decision", "preference", "learning", "note"],
        max_memories=50,
    )
    context = ctx.get_hierarchical_context(similarity_threshold=0.0, max_topics=4)

    assert "##" in context
    assert "PostgreSQL query index strategy" in context
    assert "API button layout defaults" in context
