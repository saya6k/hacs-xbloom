"""Tests for _client.XBloomClientWithEvents._scan_for_advanced_settings —
the raw pre-scan for cmd 11506/11507/11508/11509 (pour radius / vibration
amplitude GET+SET), added because these codes aren't in the vendored
XBloomResponse enum and would otherwise be silently dropped by
_parse_response's ``XBloomResponse(cmd)`` (raises ValueError, caught,
ignored). See AGENTS.md's command-id validation sweep for how these were
decompiled from the official app 2026-07-16.
"""
from __future__ import annotations

from custom_components.xbloom._client import XBloomClientWithEvents

_MARKER = 0xC1


def _client() -> XBloomClientWithEvents:
    return XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")


def _frame(cmd: int, value: int) -> bytes:
    """Synthetic frame matching the layout every other raw scan in
    _client.py relies on: header|dev_id|type|cmd(2 LE)|len(4 LE)|marker|payload|crc(2).
    total_len is real (12 + payload bytes, matching the documented wire
    convention) so tests can exercise _scan_for_advanced_settings' frame
    traversal, not just single-frame extraction. CRC is unchecked filler."""
    payload = value.to_bytes(4, "little")
    total_len = 12 + len(payload)
    header = (
        bytes([0x58, 0x07, 0x02])
        + cmd.to_bytes(2, "little")
        + total_len.to_bytes(4, "little")
    )
    return header + bytes([_MARKER]) + payload + b"\x00\x00"


def test_get_pour_radius_response_sets_status():
    client = _client()
    client._scan_for_advanced_settings(_frame(11506, 840))
    assert client._status.pour_radius == 840


def test_set_pour_radius_ack_also_updates_status():
    client = _client()
    client._scan_for_advanced_settings(_frame(11507, 760))
    assert client._status.pour_radius == 760


def test_vibration_amplitude_get_and_set():
    client = _client()
    client._scan_for_advanced_settings(_frame(11508, 1200))
    assert client._status.vibration_amplitude == 1200
    client._scan_for_advanced_settings(_frame(11509, 1300))
    assert client._status.vibration_amplitude == 1300


def test_unrelated_cmd_ignored():
    client = _client()
    client._scan_for_advanced_settings(_frame(40521, 999))
    # Attribute is never set at all (not even to None) until a real match —
    # matches coordinator.py's getattr(s, "pour_radius", None) read pattern.
    assert getattr(client._status, "pour_radius", None) is None
    assert getattr(client._status, "vibration_amplitude", None) is None


def test_missing_marker_byte_ignored():
    client = _client()
    frame = bytearray(_frame(11506, 840))
    frame[9] = 0x00  # corrupt the marker byte
    client._scan_for_advanced_settings(bytes(frame))
    assert getattr(client._status, "pour_radius", None) is None


def test_short_frame_ignored():
    client = _client()
    client._scan_for_advanced_settings(b"\x58\x07\x02\xf2\x2c")
    assert getattr(client._status, "pour_radius", None) is None


def test_frame_found_when_not_at_offset_zero():
    """Regression test for a real bug found via hardware testing
    2026-07-17: the response frame isn't guaranteed to start at byte 0 of
    the BLE notification buffer. The original implementation only checked
    offset 0 and silently missed it whenever preceded by other bytes —
    matching the reported symptom (pour_radius/vibration_amplitude
    sensors stuck `unknown` after connect)."""
    client = _client()
    prefix = b"\x11\x22\x33"  # unrelated leading bytes, no header match
    client._scan_for_advanced_settings(prefix + _frame(11506, 900))
    assert client._status.pour_radius == 900


def test_frame_found_after_a_preceding_full_frame():
    """Two real frames concatenated in one BLE notification (e.g. a
    telemetry frame immediately followed by the GET response) — the scan
    must skip past the first frame's real length, not just byte 0."""
    client = _client()
    leading = _frame(20501, 55)  # unrelated weight telemetry frame first
    client._scan_for_advanced_settings(leading + _frame(11508, 1100))
    assert client._status.vibration_amplitude == 1100
    # The leading frame's cmd isn't one we track, so pour_radius is untouched.
    assert getattr(client._status, "pour_radius", None) is None
