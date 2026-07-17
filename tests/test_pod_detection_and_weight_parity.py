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

Hardware feedback the same day found the calibration flow above didn't
actually surface anything on a real unit: 50038/50039 never arrived
during a real ~120s calibration run, so the whole started/progress/
complete flow was silently inert (is_calibrating_grinder never got set,
so even the RD_CurrentGrinder==85 completion check could never fire).
Fixed by moving "started" to send time (coordinator.async_calibrate_grinder(),
called from button.calibrate_grinder — briefly folded into
async_set_advanced_settings's calibrate_grinder field the same day, then
split back out to its own button after a separate hardware report showed
targeted advanced_settings calls were broken for an unrelated reason, see
AGENTS.md) instead of waiting for 50038, and adding RD_Grinder_Stop as a
second, hardware-confirmed-reliable completion signal alongside the raw==85
check. Also fixed while
investigating: RD_Grinder_Stop now zeroes live_grind_speed (0 RPM is a
real reading when the grinder isn't spinning, not "unknown").
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


def test_calibrate_start_sets_flag_without_firing_its_own_event():
    # 50038 is a best-effort safety net only, not the primary trigger —
    # hardware-confirmed 2026-07-17 that at least one real unit never sends
    # it during a real calibration run. coordinator.async_calibrate_grinder()
    # fires "grinder_calibration_started" itself at send time instead.
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_CalibrateStart, _frame(b""))
    assert client._status.is_calibrating_grinder is True
    assert events == []


def test_grinder_calibration_completes_via_current_grinder_85():
    client, events = _client_with_events()
    client._status.is_calibrating_grinder = True

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


def test_grinder_stop_zeroes_live_speed():
    # Hardware-confirmed 2026-07-17: the live RPM sensor stayed at its last
    # nonzero value (or Unknown) after grinding ended instead of reflecting
    # that the grinder isn't spinning — 0 is a real reading here, not a
    # missing one.
    client, _events = _client_with_events()
    client._status.grinder.speed = 1200
    client._handle_response(XBloomResponse.RD_Grinder_Stop, _frame(b""))
    assert client._status.grinder.speed == 0


def test_grinder_calibration_completes_via_grinder_stop_fallback():
    # Hardware-confirmed 2026-07-17: on at least one real unit, neither
    # 50038/50039 nor a RD_CurrentGrinder==85 ever arrived during a real
    # ~120s calibration run — only an entirely ordinary RD_Grinder_Stop at
    # the end. That must still resolve the calibration rather than leaving
    # is_calibrating_grinder stuck True (and the state sensor stuck on
    # "calibrating") forever.
    client, events = _client_with_events()
    client._status.is_calibrating_grinder = True

    client._handle_response(XBloomResponse.RD_Grinder_Stop, _frame(b""))

    assert client._status.is_calibrating_grinder is False
    assert client._status.grinder.speed == 0
    assert events == [
        ("notification", "grinder_calibration_complete", {}),
        ("notification", "grinding_complete", {}),
    ]


def test_grinder_stop_outside_calibration_does_not_fire_complete():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_Grinder_Stop, _frame(b""))
    assert client.is_calibrating_grinder() is False
    assert events == [("notification", "grinding_complete", {})]


def test_is_calibrating_grinder_accessor():
    client, _events = _client_with_events()
    assert client.is_calibrating_grinder() is False
    client._handle_response(XBloomResponse.RD_CalibrateStart, _frame(b""))
    assert client.is_calibrating_grinder() is True
