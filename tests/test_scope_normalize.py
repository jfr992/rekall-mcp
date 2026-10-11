import re

import pytest

from memory.scope import ScopeDetector, normalize_project

_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("La Gran Polla", "La-Gran-Polla"),
        ("  spaced  name ", "spaced-name"),
        ("rekall-mcp", "rekall-mcp"),
        ("a.b_c-d", "a.b_c-d"),
        ("", "general"),
        ("   ", "general"),
        ("x" * 80, "x" * 64),
    ],
)
def test_normalize_project(raw, expected):
    assert normalize_project(raw) == expected


def test_normalize_unicode_matches_safe_pattern():
    assert _SAFE.match(normalize_project("ünïcode proj"))


def test_normalize_is_idempotent():
    assert normalize_project(normalize_project("La Gran Polla")) == "La-Gran-Polla"


def test_detect_normalizes_spaced_directory(tmp_path):
    d = tmp_path / "La Gran Polla"
    d.mkdir()
    assert ScopeDetector.detect(cwd=d).project == "La-Gran-Polla"


def test_detect_normalizes_explicit_project(tmp_path):
    assert ScopeDetector.detect(project="My App", cwd=tmp_path).project == "My-App"
