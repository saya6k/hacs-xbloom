"""Tests for _client._machine_mode() staying in sync after a mode switch.

Reproduces a real bug found via live-hardware testing (2026-07-04): the
firmware only ever pushes RD_MachineInfo (40521) once, at connect —
never again after a mode switch (cmd 11511, RD_EASYMODE_TYPE). Reading
_machine_mode() purely from the connect-time MachineInfo snapshot means
it never reflects a mode switch issued over BLE, even though the
firmware's own 11511 ACK echoes the newly-applied mode code back
(captured live: easy ACK ends `...c2 91 32 78 56 90 80`, pro ACK ends
`...c2 00 00 00 00 45 48` — the 4 bytes right after the 0xc2 status
byte are the mode code).
"""
from __future__ import annotations

from custom_components.xbloom._client import XBloomClientWithEvents
from xbloom.protocol import XBloomResponse

# Real ACK packets captured live against a J15 Studio (2026-07-04).
_EASY_ACK = bytes.fromhex("580207f72c10000000c2913278569080")
_PRO_ACK = bytes.fromhex("580207f72c10000000c2000000004548")


def _client() -> XBloomClientWithEvents:
    return XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")


def test_mode_defaults_to_pro_before_any_info():
    client = _client()
    assert client._machine_mode() == "pro"


def test_mode_switch_ack_updates_machine_mode_to_easy():
    client = _client()
    client._handle_response(XBloomResponse.RD_EASYMODE_TYPE, _EASY_ACK)
    assert client._machine_mode() == "easy"


def test_mode_switch_ack_updates_machine_mode_to_pro():
    client = _client()
    client._handle_response(XBloomResponse.RD_EASYMODE_TYPE, _EASY_ACK)
    assert client._machine_mode() == "easy"
    client._handle_response(XBloomResponse.RD_EASYMODE_TYPE, _PRO_ACK)
    assert client._machine_mode() == "pro"


def test_mode_switch_ack_overrides_stale_machine_info():
    # Connect-time MachineInfo said "easy" (mode bytes at the usual
    # offset); a later 11511 ACK for "pro" must win — this is the exact
    # scenario that silently failed before the fix (mode readback stuck
    # forever at whatever MachineInfo showed at connect).
    client = _client()
    stale_payload = bytearray(63)
    stale_payload[51:55] = bytes.fromhex("91327856")  # easy
    client._status._mode_bytes = bytes(stale_payload)
    assert client._machine_mode() == "easy"

    client._handle_response(XBloomResponse.RD_EASYMODE_TYPE, _PRO_ACK)
    assert client._machine_mode() == "pro"
