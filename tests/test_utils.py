"""Tests for core.utils — stable_hash_id()."""

import hashlib
from datetime import UTC, datetime

import pytest

from core.utils import parse_ts, stable_hash_id, utc_now, utc_now_iso


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


def test_utc_now_is_aware_utc():
    assert utc_now().utcoffset().total_seconds() == 0


def test_utc_now_iso_has_offset():
    assert utc_now_iso().endswith("+00:00")


def test_parse_ts_treats_naive_as_utc():
    assert parse_ts("2026-10-10T21:27:44") == datetime(2026, 10, 10, 21, 27, 44, tzinfo=UTC)


def test_parse_ts_keeps_offsets():
    assert parse_ts("2026-10-10T17:27:44-04:00") == parse_ts("2026-10-10T21:27:44")


def test_parse_ts_rejects_garbage():
    with pytest.raises(ValueError):
        parse_ts("not a time")
