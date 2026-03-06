"""Tests for the WebSocket-to-PTY terminal relay."""
from __future__ import annotations

from terminal_relay import TerminalRelay


class TestTerminalRelay:
    def test_parse_resize_message(self):
        """Resize messages start with \x01 prefix."""
        relay = TerminalRelay.__new__(TerminalRelay)
        msg = b'\x01{"cols":120,"rows":40}'
        is_resize, data = relay._parse_input(msg)
        assert is_resize is True
        assert data["cols"] == 120
        assert data["rows"] == 40

    def test_parse_normal_input(self):
        """Normal input is just raw bytes."""
        relay = TerminalRelay.__new__(TerminalRelay)
        msg = b"ls -la\r"
        is_resize, data = relay._parse_input(msg)
        assert is_resize is False
        assert data == msg
