"""Tests for inferred skill extraction."""

from memory.skills import extract_skills, render_skill_context


def test_extract_skills_requires_repetition():
    points = [
        {"memory_id": "a", "content": "Used PostgreSQL for query optimization and indexing"},
        {"memory_id": "b", "content": "Migrated dashboards to PostgreSQL for reporting"},
        {"memory_id": "c", "content": "Debugged Python queue worker starvation"},
    ]

    skills = extract_skills(points, min_mentions=2, max_skills=5)
    names = [skill.name for skill in skills]

    assert "postgresql" in names
    assert "python" not in names


def test_extract_skills_respects_min_mentions():
    points = [
        {"memory_id": "a", "content": "Configured Docker networking"},
        {"memory_id": "b", "content": "Investigated queue latency"},
    ]

    assert extract_skills(points, min_mentions=2, max_skills=5) == []


def test_render_skill_context_is_deterministic():
    skills = extract_skills(
        [
            {"memory_id": "a", "content": "PostgreSQL indexing pattern"},
            {"memory_id": "b", "content": "PostgreSQL query plans"},
        ],
        min_mentions=2,
        max_skills=2,
    )
    context = render_skill_context(skills, project="api")

    assert "# Skill Context: api" in context
    assert "postgresql (2 mentions)" in context
