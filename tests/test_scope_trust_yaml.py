"""Fix I2 — trust boundary must come from YAML, not hardcoded client names."""

import pathlib

from memory.scope import ScopeDetector
from memory.trust import TrustResolver, load_trust_rules


def test_no_hardcoded_client_names_in_scope_source():
    """Regression: client-specific org names must not appear in scope.py.

    Tokens are assembled from codepoints so this repo itself greps clean.
    """
    forbidden = ["".join(map(chr, t)) for t in ((121, 117, 109), (97, 117, 100, 97, 99, 121))]
    src = pathlib.Path("src/memory/scope.py").read_text().lower()
    for token in forbidden:
        assert token not in src


def test_missing_trust_file_defaults_to_personal(tmp_path, monkeypatch):
    monkeypatch.setenv("REKALL_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="anything", name="any-repo") == "personal"


def test_trust_yaml_matches_by_remote(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("""
boundaries:
  - name: acme
    match:
      remote_contains: "gitlab.acme.internal"
""")
    monkeypatch.setenv("REKALL_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="https://gitlab.acme.internal/foo.git", name="foo") == "acme"
    assert resolver.resolve(remote="https://github.com/other.git", name="other") == "personal"


def test_trust_yaml_matches_by_name(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("""
boundaries:
  - name: prototype
    match:
      name_contains: "proto-"
""")
    monkeypatch.setenv("REKALL_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="", name="proto-alpha") == "prototype"


def test_trust_yaml_list_of_match_tokens(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("""
boundaries:
  - name: work
    match:
      remote_contains:
        - "gitlab.work-a.com"
        - "gitlab.work-b.com"
""")
    monkeypatch.setenv("REKALL_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="https://gitlab.work-a.com/x.git", name="x") == "work"
    assert resolver.resolve(remote="https://gitlab.work-b.com/y.git", name="y") == "work"
    assert resolver.resolve(remote="https://gitlab.other.com/z.git", name="z") == "personal"


def test_malformed_trust_yaml_defaults_to_personal(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("this is not valid yaml: [[[")
    monkeypatch.setenv("REKALL_MEMORY_DIR", str(tmp_path))
    # Must not raise
    rules = load_trust_rules()
    assert rules == []
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="anything", name="any") == "personal"


def test_scope_detector_uses_trust_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("REKALL_MEMORY_DIR", str(tmp_path))
    scope = ScopeDetector.detect(cwd="/tmp/nowhere", project="test")
    assert scope.trust_boundary == "personal"
