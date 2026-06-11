"""Startup hints must match the concepts committed in docs/AGENT_STARTUP.md.

This replaces the old test_agent_startup_doc_smoke.py which only checked
string presence in the doc. This version verifies the live SYSTEM_HINTS
dict contains the concepts the doc promises, so they don't drift.
"""

from __future__ import annotations

import pathlib

from memory.startup import SYSTEM_HINTS


def test_doc_still_exists():
    doc = pathlib.Path("docs/AGENT_STARTUP.md")
    assert doc.exists(), "docs/AGENT_STARTUP.md must exist"


def test_every_hint_dict_has_content():
    """Each agent key must have a non-empty list of hints."""
    assert "claude-code" in SYSTEM_HINTS
    assert "codex" in SYSTEM_HINTS
    assert "unknown" in SYSTEM_HINTS
    for agent, hints in SYSTEM_HINTS.items():
        assert isinstance(hints, list), f"{agent} hints must be a list"
        assert len(hints) >= 1, f"{agent} hints must not be empty"


def test_live_hints_cover_core_concepts():
    """The live hint blob must reference the same core concepts the doc covers."""
    all_hint_text = " ".join(hint.lower() for hints in SYSTEM_HINTS.values() for hint in hints)
    doc = pathlib.Path("docs/AGENT_STARTUP.md").read_text().lower()

    required_concepts = [
        "observe",
        "resume",
    ]
    for concept in required_concepts:
        assert concept in doc, f"doc is missing concept: {concept}"
        assert concept in all_hint_text, f"live SYSTEM_HINTS missing concept: {concept}"
