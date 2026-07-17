"""Tests for _client.XBloomClientWithEvents.is_sleeping() / the sleep-state
notification handling (cmd 8009/8011/8023).

Decompiled 2026-07-17 (jadx) from com/chisalsoft/andite/manager/
AppDeviceManager.java's static ``isSleeping`` flag and its three
BaseBleModel.create() dispatch targets: MachineSleepingModel (8009 ->
setSleeping(true)), MachineNotSleepingModel (8011 -> setSleeping(false)),
MachineActivityModel (8023 -> setSleeping(false) unconditionally). All
three codes are already valid XBloomResponse enum members, so they reach
_handle_response via the normal type-1 notification path.
"""
from __future__ import annotations

from custom_components.xbloom._client import XBloomClientWithEvents
from xbloom.protocol import XBloomResponse

_MARKER = 0xC1  # type-1 response marker — see _NOTIFICATION_MARKER_BYTE


def _client() -> XBloomClientWithEvents:
    return XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")


def _frame(cmd: int) -> bytes:
    """Synthetic type-1 frame: header|dev_id|type|cmd(2 LE)|len(4 LE)|marker|crc(2).
    No payload — matches the real MachineSleeping/NotSleeping/Activity
    frames, none of which carry data this integration reads."""
    total_len = 12
    header = (
        bytes([0x58, 0x07, 0x01])
        + cmd.to_bytes(2, "little")
        + total_len.to_bytes(4, "little")
    )
    return header + bytes([_MARKER]) + b"\x00\x00"


def test_defaults_to_not_sleeping():
    client = _client()
    assert client.is_sleeping() is False


def test_machine_sleeping_sets_flag():
    client = _client()
    client._handle_response(XBloomResponse.RD_MachineSleeping, _frame(8009))
    assert client.is_sleeping() is True


def test_machine_not_sleeping_clears_flag():
    client = _client()
    client._handle_response(XBloomResponse.RD_MachineSleeping, _frame(8009))
    assert client.is_sleeping() is True
    client._handle_response(XBloomResponse.RD_MachineNotSleeping, _frame(8011))
    assert client.is_sleeping() is False


def test_machine_activity_also_clears_flag():
    """MachineActivityModel.excute() calls setSleeping(false) unconditionally,
    regardless of its payload "index" field — no index parsing needed here."""
    client = _client()
    client._handle_response(XBloomResponse.RD_MachineSleeping, _frame(8009))
    assert client.is_sleeping() is True
    client._handle_response(XBloomResponse.RD_MachineActivity, _frame(8023))
    assert client.is_sleeping() is False


def test_sleep_state_reaches_status_through_the_real_notification_pipeline():
    """Goes through _on_notification (the real BLE entry point), not
    _handle_response directly — exercises _split_and_parse's framing/marker
    gate too, same rationale as test_mode_ack.py's equivalent regression
    test."""
    client = _client()
    assert client.is_sleeping() is False
    client._on_notification(char="fake", data=bytearray(_frame(8009)))
    assert client.is_sleeping() is True
    client._on_notification(char="fake", data=bytearray(_frame(8011)))
    assert client.is_sleeping() is False
