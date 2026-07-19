"""Tests for the native ble/client.py — Phase 2b of the de-vendoring
refactor (see adr/001-clean-room-reimplementation-of-xbloom-ble.md).

Ports the behavior-pinning assertions from the pre-refactor
``_client.XBloomClientWithEvents`` test suite (test_sleep_state.py,
test_mode_ack.py, test_water_shortage.py, test_advanced_settings_scan.py,
test_connection_watchdog.py, test_unit_change.py,
test_pod_detection_and_weight_parity.py) onto the native
``ble.client.XBloomClient`` — the concrete proof that the clean-room
reimplementation preserves every hardware-confirmed behavior those tests
pin, per the ADR's compatibility-oracle mandate. Test bytes/scenarios are
unchanged from the originals; only the import and enum names differ.
"""
from __future__ import annotations

import struct

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.ble.constants import Response


class _FakeConnection:
    """Minimal stand-in for HABleakConnection — never actually connects.
    All tests here exercise notification handling directly, not the
    connect/write path."""

    is_connected = False

    async def connect(self, address, timeout=20.0):
        return False

    async def disconnect(self):
        pass

    async def write_command(self, char_uuid, data, response=False):
        pass

    async def start_notify(self, char_uuid, callback):
        pass

    async def stop_notify(self, char_uuid):
        pass


def _client() -> XBloomClient:
    return XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())


def _client_with_events():
    client = _client()
    events = []
    client.on_event(lambda cat, etype, attrs: events.append((cat, etype, attrs)))
    return client, events


def _frame_notag(payload: bytes) -> bytes:
    # header/dev_id/type/cmd/len fill (10 bytes) | payload | crc(2) — for
    # tests that call _handle_response directly, bypassing the marker gate.
    return b"\x58\x02\x00\x00\x00\x00\x00\x00\x00\x00" + payload + b"\x00\x00"


def _tagged_frame(cmd: int, payload: bytes = b"", marker: int = 0xC1) -> bytes:
    total_len = 12 + len(payload)
    header = bytes([0x58, 0x07, 0x01 if marker == 0xC1 else 0x02]) + cmd.to_bytes(2, "little") + total_len.to_bytes(4, "little")
    return header + bytes([marker]) + payload + b"\x00\x00"


# ---------------------------------------------------------------------
# Sleep state (cmd 8009/8011/8023)
# ---------------------------------------------------------------------


def test_defaults_to_not_sleeping():
    assert _client().is_sleeping() is False


def test_machine_sleeping_sets_flag():
    client = _client()
    client._handle_response(Response.MACHINE_SLEEPING, _tagged_frame(8009))
    assert client.is_sleeping() is True


def test_machine_not_sleeping_clears_flag():
    client = _client()
    client._handle_response(Response.MACHINE_SLEEPING, _tagged_frame(8009))
    client._handle_response(Response.MACHINE_NOT_SLEEPING, _tagged_frame(8011))
    assert client.is_sleeping() is False


def test_machine_activity_also_clears_flag():
    client = _client()
    client._handle_response(Response.MACHINE_SLEEPING, _tagged_frame(8009))
    client._handle_response(Response.MACHINE_ACTIVITY, _tagged_frame(8023))
    assert client.is_sleeping() is False


def test_sleep_state_reaches_status_through_the_real_notification_pipeline():
    client = _client()
    assert client.is_sleeping() is False
    client._on_notification(char="fake", data=bytearray(_tagged_frame(8009)))
    assert client.is_sleeping() is True
    client._on_notification(char="fake", data=bytearray(_tagged_frame(8011)))
    assert client.is_sleeping() is False


# ---------------------------------------------------------------------
# Mode-switch ACK (cmd 11511)
# ---------------------------------------------------------------------

_EASY_ACK = bytes.fromhex("580207f72c10000000c2913278569080")
_PRO_ACK = bytes.fromhex("580207f72c10000000c2000000004548")


def test_mode_defaults_to_pro_before_any_info():
    assert _client()._machine_mode() == "pro"


def test_mode_switch_ack_updates_machine_mode_to_easy():
    client = _client()
    client._handle_response(Response.EASYMODE_TYPE, _EASY_ACK)
    assert client._machine_mode() == "easy"


def test_mode_switch_ack_updates_machine_mode_to_pro():
    client = _client()
    client._handle_response(Response.EASYMODE_TYPE, _EASY_ACK)
    assert client._machine_mode() == "easy"
    client._handle_response(Response.EASYMODE_TYPE, _PRO_ACK)
    assert client._machine_mode() == "pro"


def test_mode_switch_ack_overrides_stale_machine_info():
    client = _client()
    stale_payload = bytearray(63)
    stale_payload[51:55] = bytes.fromhex("91327856")  # easy
    client._status.mode_bytes = bytes(stale_payload)
    assert client._machine_mode() == "easy"
    client._handle_response(Response.EASYMODE_TYPE, _PRO_ACK)
    assert client._machine_mode() == "pro"


def test_mode_ack_reaches_status_through_the_real_notification_pipeline():
    client = _client()
    assert client._machine_mode() == "pro"
    client._on_notification(char="fake", data=bytearray(_EASY_ACK))
    assert client._machine_mode() == "easy"
    client._on_notification(char="fake", data=bytearray(_PRO_ACK))
    assert client._machine_mode() == "pro"


# ---------------------------------------------------------------------
# Bidirectional water shortage (cmd 40522)
# ---------------------------------------------------------------------


def test_value_zero_fires_water_shortage_error():
    client, events = _client_with_events()
    client._handle_response(Response.ERROR_LACK_OF_WATER, _frame_notag((0).to_bytes(4, "little")))
    assert ("error", "water_shortage", {}) in events
    assert client._status.water_level_ok is False


def test_value_one_fires_water_refilled_notification():
    client, events = _client_with_events()
    client._handle_response(Response.ERROR_LACK_OF_WATER, _frame_notag((1).to_bytes(4, "little")))
    assert ("notification", "water_refilled", {}) in events
    assert not any(e[:2] == ("error", "water_shortage") for e in events)
    assert client._status.water_level_ok is True


def test_shortage_then_refill_round_trip():
    client, events = _client_with_events()
    client._handle_response(Response.ERROR_LACK_OF_WATER, _frame_notag((0).to_bytes(4, "little")))
    assert client._status.water_level_ok is False
    client._handle_response(Response.ERROR_LACK_OF_WATER, _frame_notag((1).to_bytes(4, "little")))
    assert client._status.water_level_ok is True
    assert [e[:2] for e in events] == [("error", "water_shortage"), ("notification", "water_refilled")]


def test_truncated_payload_defaults_to_shortage():
    client, events = _client_with_events()
    client._handle_response(Response.ERROR_LACK_OF_WATER, b"\x58\x02\x00")
    assert any(e[:2] == ("error", "water_shortage") for e in events)


# ---------------------------------------------------------------------
# Advanced-settings raw pre-scan (cmd 11506-11509)
# ---------------------------------------------------------------------

_TYPE2_MARKER = 0xC2


def _advanced_frame(cmd: int, value: int) -> bytes:
    payload = value.to_bytes(4, "little")
    total_len = 12 + len(payload)
    header = bytes([0x58, 0x07, 0x02]) + cmd.to_bytes(2, "little") + total_len.to_bytes(4, "little")
    return header + bytes([_TYPE2_MARKER]) + payload + b"\x00\x00"


def test_get_pour_radius_response_sets_status():
    client = _client()
    client._scan_for_advanced_settings(_advanced_frame(11506, 840))
    assert client._status.pour_radius == 840


def test_set_pour_radius_ack_also_updates_status():
    client = _client()
    client._scan_for_advanced_settings(_advanced_frame(11507, 760))
    assert client._status.pour_radius == 760


def test_vibration_amplitude_get_and_set():
    client = _client()
    client._scan_for_advanced_settings(_advanced_frame(11508, 1200))
    assert client._status.vibration_amplitude == 1200
    client._scan_for_advanced_settings(_advanced_frame(11509, 1300))
    assert client._status.vibration_amplitude == 1300


def test_unrelated_cmd_ignored():
    client = _client()
    client._scan_for_advanced_settings(_advanced_frame(40521, 999))
    assert client._status.pour_radius is None
    assert client._status.vibration_amplitude is None


def test_missing_marker_byte_ignored():
    client = _client()
    frame = bytearray(_advanced_frame(11506, 840))
    frame[9] = 0x00
    client._scan_for_advanced_settings(bytes(frame))
    assert client._status.pour_radius is None


def test_type1_marker_rejected():
    client = _client()
    frame = bytearray(_advanced_frame(11506, 840))
    frame[9] = 0xC1
    client._scan_for_advanced_settings(bytes(frame))
    assert client._status.pour_radius is None


def test_short_frame_ignored():
    client = _client()
    client._scan_for_advanced_settings(b"\x58\x07\x02\xf2\x2c")
    assert client._status.pour_radius is None


def test_frame_found_when_not_at_offset_zero():
    client = _client()
    prefix = b"\x11\x22\x33"
    client._scan_for_advanced_settings(prefix + _advanced_frame(11506, 900))
    assert client._status.pour_radius == 900


def test_frame_found_after_a_preceding_full_frame():
    client = _client()
    leading = _advanced_frame(20501, 55)
    client._scan_for_advanced_settings(leading + _advanced_frame(11508, 1100))
    assert client._status.vibration_amplitude == 1100
    assert client._status.pour_radius is None


# ---------------------------------------------------------------------
# Silence watchdog
# ---------------------------------------------------------------------


def test_seconds_since_last_notification_starts_near_zero():
    assert _client().seconds_since_last_notification() < 1.0


def test_seconds_since_last_notification_reflects_elapsed_time():
    client = _client()
    client._last_notification_monotonic -= 20.0
    assert client.seconds_since_last_notification() >= 20.0


def test_on_notification_resets_the_watchdog():
    client = _client()
    client._last_notification_monotonic -= 20.0
    client._on_notification(None, bytearray(b"\x00"))
    assert client.seconds_since_last_notification() < 1.0


# ---------------------------------------------------------------------
# Unit/water-source push (cmd 8015)
# ---------------------------------------------------------------------


def _unit_frame(weight: int, temp: int, water: int) -> bytes:
    payload = weight.to_bytes(4, "little") + temp.to_bytes(4, "little") + water.to_bytes(4, "little")
    return _frame_notag(payload)


def test_unit_change_fires_settings_event_with_parsed_values():
    client, events = _client_with_events()
    client._handle_response(Response.UNIT_CHANGE, _unit_frame(2, 1, 1))
    assert events == [("settings", "unit_change", {"weight_unit": 2, "temp_unit": 1, "water_source": 1})]


def test_unit_change_zero_values_parse_correctly():
    client, events = _client_with_events()
    client._handle_response(Response.UNIT_CHANGE, _unit_frame(0, 0, 0))
    assert events == [("settings", "unit_change", {"weight_unit": 0, "temp_unit": 0, "water_source": 0})]


def test_truncated_payload_is_ignored():
    client, events = _client_with_events()
    client._handle_response(Response.UNIT_CHANGE, _frame_notag(b"\x01\x00\x00\x00"))
    assert events == []


# ---------------------------------------------------------------------
# Pod detection, weight parity, easy-slot-begin, current-grinder,
# calibration completion — ported from
# test_pod_detection_and_weight_parity.py
# ---------------------------------------------------------------------


def test_pod_detected_fires_notification_event_with_xid():
    client, events = _client_with_events()
    client._handle_response(Response.PODS, _frame_notag(b"ABC123"))
    assert events == [("notification", "pod_detected", {"xid": "ABC123"})]


def test_pod_detected_only_reads_first_six_bytes():
    client, events = _client_with_events()
    client._handle_response(Response.PODS, _frame_notag(b"ABC123EXTRA"))
    assert events == [("notification", "pod_detected", {"xid": "ABC123"})]


def test_pod_detected_strips_padding_bytes():
    client, events = _client_with_events()
    client._handle_response(Response.PODS, _frame_notag(b"ABC1" + b"\xff\xff"))
    assert events == [("notification", "pod_detected", {"xid": "ABC1"})]


def test_current_weight_10507_parses_into_scale_weight():
    client, _events = _client_with_events()
    client._handle_response(Response.CURRENT_WEIGHT, _frame_notag(struct.pack("<f", 12.5)))
    assert client._status.scale.weight == 12.5


def test_current_weight_10507_truncated_payload_is_ignored():
    client, _events = _client_with_events()
    client._status.scale.weight = 0.0
    client._handle_response(Response.CURRENT_WEIGHT, _frame_notag(b"\x01\x00"))
    assert client._status.scale.weight == 0.0


def test_easy_slot_started_maps_index_to_letter():
    client, events = _client_with_events()
    for raw, letter in ((0, "A"), (1, "B"), (2, "C")):
        events.clear()
        client._handle_response(Response.EASYMODE_BEGIN, _frame_notag(raw.to_bytes(4, "little")))
        assert events == [("notification", "easy_slot_started", {"slot": letter})]


def test_easy_slot_started_ignores_out_of_range_index():
    client, events = _client_with_events()
    client._handle_response(Response.EASYMODE_BEGIN, _frame_notag((3).to_bytes(4, "little")))
    assert events == [("notification", "easy_slot_started", {})]


def test_current_grinder_40526_parses_into_grinder_size():
    client, _events = _client_with_events()
    client._handle_response(Response.CURRENT_GRINDER, _frame_notag((60).to_bytes(4, "little")))
    assert client._status.grinder.size == 30


def test_calibrate_start_sets_flag_without_firing_its_own_event():
    client, events = _client_with_events()
    client._handle_response(Response.CALIBRATE_START, _frame_notag(b""))
    assert client._status.is_calibrating_grinder is True
    assert events == []


def test_grinder_calibration_completes_via_current_grinder_85():
    client, events = _client_with_events()
    client._status.is_calibrating_grinder = True
    client._handle_response(Response.CALIBRATING, _frame_notag(b""))
    client._handle_response(Response.CURRENT_GRINDER, _frame_notag((60).to_bytes(4, "little")))
    assert client._status.is_calibrating_grinder is True
    client._handle_response(Response.CURRENT_GRINDER, _frame_notag((85).to_bytes(4, "little")))
    assert client._status.is_calibrating_grinder is False
    assert events == [
        ("notification", "grinder_calibration_progress", {}),
        ("notification", "grinder_calibration_complete", {}),
    ]


def test_current_grinder_85_outside_calibration_does_not_fire_complete():
    client, events = _client_with_events()
    client._handle_response(Response.CURRENT_GRINDER, _frame_notag((85).to_bytes(4, "little")))
    assert client._status.grinder.size == 55
    assert events == []


def test_grinder_stop_zeroes_live_speed():
    client, _events = _client_with_events()
    client._status.grinder.speed = 1200
    client._handle_response(Response.GRINDER_STOP, _frame_notag(b""))
    assert client._status.grinder.speed == 0


def test_grinder_stop_does_not_end_calibration():
    client, events = _client_with_events()
    client._status.is_calibrating_grinder = True
    client._handle_response(Response.GRINDER_STOP, _frame_notag(b""))
    assert client._status.is_calibrating_grinder is True
    assert client._status.grinder.speed == 0
    assert events == []
    client._handle_response(Response.CURRENT_GRINDER, _frame_notag((85).to_bytes(4, "little")))
    assert client._status.is_calibrating_grinder is False
    assert events[-1] == ("notification", "grinder_calibration_complete", {})


def test_grinder_stop_outside_calibration_does_not_fire_complete():
    client, events = _client_with_events()
    client._handle_response(Response.GRINDER_STOP, _frame_notag(b""))
    assert client.is_calibrating_grinder() is False
    assert events == [("notification", "grinding_complete", {})]


def test_grinding_events_suppressed_during_calibration():
    client, events = _client_with_events()
    client._status.is_calibrating_grinder = True
    client._handle_response(Response.GRINDER_BEGIN, _frame_notag(b""))
    client._handle_response(Response.GRINDER_STOP, _frame_notag(b""))
    client._handle_response(Response.GRINDER_BEGIN, _frame_notag(b""))
    client._handle_response(Response.GRINDER_STOP, _frame_notag(b""))
    assert events == []
    client._status.is_calibrating_grinder = False
    client._handle_response(Response.GRINDER_BEGIN, _frame_notag(b""))
    assert events == [("notification", "grinding_started", {})]


def test_is_calibrating_grinder_accessor():
    client, _events = _client_with_events()
    assert client.is_calibrating_grinder() is False
    client._handle_response(Response.CALIBRATE_START, _frame_notag(b""))
    assert client.is_calibrating_grinder() is True


# ---------------------------------------------------------------------
# 40506 — the hardware-confirmed grinder-begin signal (2026-07-19).
# 9003 GRINDER_BEGIN has never been seen firing on real hardware; 40506
# fires at the exact grind-start instant on recipe and manual grinds
# alike, paired with 40507 GRINDER_STOP.
# ---------------------------------------------------------------------


def test_40506_fires_grinding_started_and_marks_the_grinder_running():
    client, events = _client_with_events()
    client._handle_response(Response.GRINDER_RUN_BEGIN, _frame_notag(b""))
    assert ("notification", "grinding_started", {}) in events
    assert client._status.grinder.is_running is True


def test_40506_is_suppressed_during_calibration_like_9003():
    client, events = _client_with_events()
    client._status.is_calibrating_grinder = True
    client._handle_response(Response.GRINDER_RUN_BEGIN, _frame_notag(b""))
    assert events == []
