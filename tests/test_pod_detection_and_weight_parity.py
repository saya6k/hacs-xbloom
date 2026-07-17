"""Tests for the command-table completeness sweep (2026-07-17), verified
against the official app's decompiled source (jadx) rather than guessed
from command names — see AGENTS.md's firmware-quirks section.

- RD_Pods (40501): NFC pod detected. xid is 6 raw bytes (the app hex-decodes
  12 hex chars, not 12 raw bytes — an earlier version of this integration
  got this wrong and read 12 raw bytes).
- RD_CURRENT_WEIGHT (10507): second weight-telemetry cmd, same float32
  layout as the already-handled RD_CURRENT_WEIGHT2 (20501).
- RD_EASYMODE_BEGIN (8111): Easy Mode brew started from the machine's own
  dial. Payload is a 0-2 slot index, confirmed via AppBaseActivity's
  direct list-indexing use of the value.
- RD_CurrentGrinder (40526): same grind-size telemetry as RD_GRINDER_SIZE
  (identical -30 offset), plus doubles as the grinder-calibration-complete
  signal (raw == 85) while a calibration (cmd 3502) is in progress.
- RD_CalibrateStart/RD_Calibrating (50038/50039): grinder calibration
  sweep start/progress pulses, no payload.
"""
from __future__ import annotations

import struct

from custom_components.xbloom._client import XBloomClientWithEvents
from xbloom.protocol import XBloomResponse


def _frame(payload: bytes) -> bytes:
    # header/dev_id/type/cmd/len fill (10 bytes) | payload | crc(2)
    return b"\x58\x02\x00\x00\x00\x00\x00\x00\x00\x00" + payload + b"\x00\x00"


def _client_with_events():
    client = XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")
    events = []
    client.on_event(lambda cat, etype, attrs: events.append((cat, etype, attrs)))
    return client, events


def test_pod_detected_fires_notification_event_with_xid():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_Pods, _frame(b"ABC123"))
    assert events == [("notification", "pod_detected", {"xid": "ABC123"})]


def test_pod_detected_only_reads_first_six_bytes():
    # The real app takes hexStr.substring(0, 12) — 12 hex chars, i.e. 6
    # raw bytes — not the full payload. Extra trailing bytes must be
    # ignored, not appended to the xid.
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_Pods, _frame(b"ABC123EXTRA"))
    assert events == [("notification", "pod_detected", {"xid": "ABC123"})]


def test_pod_detected_strips_padding_bytes():
    # 0xFF-padded tail, matching the same filler pattern MachineInfo's
    # serial/version fields use — strict_ascii() should drop it, not turn
    # it into garbage.
    client, events = _client_with_events()
    client._handle_response(
        XBloomResponse.RD_Pods, _frame(b"ABC1" + b"\xff\xff")
    )
    assert events == [("notification", "pod_detected", {"xid": "ABC1"})]


def test_current_weight_10507_parses_into_scale_weight():
    client, _events = _client_with_events()
    client._handle_response(
        XBloomResponse.RD_CURRENT_WEIGHT, _frame(struct.pack("<f", 12.5))
    )
    assert client._status.scale.weight == 12.5


def test_current_weight_10507_truncated_payload_is_ignored():
    client, _events = _client_with_events()
    client._status.scale.weight = 0.0
    client._handle_response(XBloomResponse.RD_CURRENT_WEIGHT, _frame(b"\x01\x00"))
    assert client._status.scale.weight == 0.0


def test_easy_slot_started_maps_index_to_letter():
    client, events = _client_with_events()
    for raw, letter in ((0, "A"), (1, "B"), (2, "C")):
        events.clear()
        client._handle_response(
            XBloomResponse.RD_EASYMODE_BEGIN,
            _frame(raw.to_bytes(4, "little")),
        )
        assert events == [("notification", "easy_slot_started", {"slot": letter})]


def test_easy_slot_started_ignores_out_of_range_index():
    client, events = _client_with_events()
    client._handle_response(
        XBloomResponse.RD_EASYMODE_BEGIN, _frame((3).to_bytes(4, "little"))
    )
    assert events == [("notification", "easy_slot_started", {})]


def test_current_grinder_40526_parses_into_grinder_size():
    client, _events = _client_with_events()
    client._handle_response(
        XBloomResponse.RD_CurrentGrinder, _frame((60).to_bytes(4, "little"))
    )
    assert client._status.grinder.size == 30  # 60 - _GRIND_SIZE_RAW_OFFSET(30)


def test_grinder_calibration_flow_fires_start_progress_and_complete():
    client, events = _client_with_events()

    client._handle_response(XBloomResponse.RD_CalibrateStart, _frame(b""))
    assert client._status.is_calibrating_grinder is True

    client._handle_response(XBloomResponse.RD_Calibrating, _frame(b""))

    # Not yet done — a normal knob position, not the completion marker.
    client._handle_response(
        XBloomResponse.RD_CurrentGrinder, _frame((60).to_bytes(4, "little"))
    )
    assert client._status.is_calibrating_grinder is True

    # 85 while calibrating == done.
    client._handle_response(
        XBloomResponse.RD_CurrentGrinder, _frame((85).to_bytes(4, "little"))
    )
    assert client._status.is_calibrating_grinder is False

    assert events == [
        ("notification", "grinder_calibration_started", {}),
        ("notification", "grinder_calibration_progress", {}),
        ("notification", "grinder_calibration_complete", {}),
    ]


def test_current_grinder_85_outside_calibration_does_not_fire_complete():
    client, events = _client_with_events()
    client._handle_response(
        XBloomResponse.RD_CurrentGrinder, _frame((85).to_bytes(4, "little"))
    )
    assert client._status.grinder.size == 55
    assert events == []
