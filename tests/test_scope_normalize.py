import re

import pytest

from memory.scope import ScopeDetector, normalize_project

_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("My Project", "My-Project"),
        ("  spaced  name ", "spaced-name"),
        ("rekall-mcp", "rekall-mcp"),
        ("a.b_c-d", "a.b_c-d"),
        (".playwright-mcp", ".playwright-mcp"),
        ("-.x-", ".x"),
        ("...", "general"),
        ("..", "general"),
        ("-.-", "general"),
        ("", "general"),
        ("   ", "general"),
        ("x" * 80, "x" * 64),
    ],
)
def test_normalize_project(raw, expected):
    assert normalize_project(raw) == expected


def test_normalize_unicode_matches_safe_pattern():
    assert _SAFE.match(normalize_project("ünïcode proj"))


@pytest.mark.parametrize("raw", [".playwright-mcp", "...", "ünï .x", "x" * 80])
def test_normalize_matches_safe_pattern(raw):
    assert _SAFE.match(normalize_project(raw))


def test_normalize_is_idempotent():
    assert normalize_project(normalize_project("My Project")) == "My-Project"


def test_detect_normalizes_spaced_directory(tmp_path):
    d = tmp_path / "My Project"
    d.mkdir()
    assert ScopeDetector.detect(cwd=d).project == "My-Project"


def test_detect_normalizes_explicit_project(tmp_path):
    assert ScopeDetector.detect(project="My App", cwd=tmp_path).project == "My-App"
