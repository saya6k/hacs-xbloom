"""Tests for the BLE silence watchdog (_client.seconds_since_last_notification).

Mirrors the official Android app's connection-supervisor design (see
AGENTS.md's BLE connection management section): every raw notification
resets a "last seen" timestamp, and the coordinator forces a reconnect if
too much time passes without one. The coordinator-side reconnect supervisor
itself (coordinator._maybe_schedule_reconnect / _async_force_reconnect)
needs a real HomeAssistant instance to construct and is validated manually
against real hardware instead — see the Testing section in AGENTS.md.
"""
from __future__ import annotations

from custom_components.xbloom._client import XBloomClientWithEvents


def _client() -> XBloomClientWithEvents:
    return XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")


def test_seconds_since_last_notification_starts_near_zero():
    client = _client()
    assert client.seconds_since_last_notification() < 1.0


def test_seconds_since_last_notification_reflects_elapsed_time():
    client = _client()
    client._last_notification_monotonic -= 20.0
    assert client.seconds_since_last_notification() >= 20.0


def test_on_notification_resets_the_watchdog():
    client = _client()
    client._last_notification_monotonic -= 20.0
    assert client.seconds_since_last_notification() >= 20.0
    client._on_notification(None, bytearray(b"\x00"))
    assert client.seconds_since_last_notification() < 1.0
