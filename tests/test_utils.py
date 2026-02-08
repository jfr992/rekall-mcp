"""Tests for core.utils — stable_hash_id()."""

import hashlib

from core.utils import stable_hash_id


class TestStableHashId:
    """stable_hash_id must be deterministic, positive, and within int63."""

    def test_returns_positive_int_within_int63(self):
        result = stable_hash_id("anything")
        assert isinstance(result, int)
        assert 0 <= result < 2**63

    def test_deterministic_across_calls(self):
        assert stable_hash_id("hello") == stable_hash_id("hello")

    def test_different_inputs_differ(self):
        assert stable_hash_id("alpha") != stable_hash_id("beta")

    def test_matches_known_sha256_derivation(self):
        text = "test-id"
        expected_bytes = hashlib.sha256(text.encode()).digest()
        expected = int.from_bytes(expected_bytes[:8], byteorder="big") % (2**63)
        assert stable_hash_id(text) == expected

    def test_handles_empty_string(self):
        result = stable_hash_id("")
        assert isinstance(result, int)
        assert 0 <= result < 2**63
