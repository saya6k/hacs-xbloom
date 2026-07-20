"""Machine alarm channel — cmd 0xFFFE, marker 0xCD (T14 / SPEC G).

jadx 2026-07-20 (`ErrorBle1Model`): the payload's first LE u32 is an alarm
code mapped to six app dialog categories. The frames carry marker 0xCD,
which the normal framing loop rejects, so a dedicated pre-scan handles
them. Silent-list codes and unknown codes fire nothing (mirroring the
app); no `*_cleared` synthesis (the sole-type rule stands).
"""
from __future__ import annotations

import struct

import pytest

from custom_components.xbloom.ble.client import XBloomClient


class _FakeConnection:
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


def _client_with_events():
    client = XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())
    events = []
    client.on_event(lambda cat, etype, attrs: events.append((cat, etype, attrs)))
    return client, events


def _alarm_frame(code: int) -> bytes:
    payload = struct.pack("<I", code)
    total_len = 12 + len(payload)
    return (
        bytes([0x58, 0x02, 0x07])
        + (0xFFFE).to_bytes(2, "little")
        + total_len.to_bytes(4, "little")
        + bytes([0xCD])
        + payload
        + b"\x00\x00"
    )


@pytest.mark.parametrize(
    ("code", "event_type"),
    [
        (8449, "mismatched_power"),
        (4355, "mismatched_power"),   # the umeng-constant part of the list
        (513, "brewing_error"),
        (14603, "brewing_error"),
        (8961, "dock_moving_error"),
        (13064, "dock_moving_error"),
        (1025, "grinding_error"),
        (13572, "grinding_error"),
        (1793, "scale_overload"),
        (5890, "scale_overload"),
        (7169, "upgrade_failed"),
        (7170, "upgrade_failed"),
    ],
)
def test_alarm_code_fires_its_category_event(code, event_type):
    client, events = _client_with_events()
    client._on_notification(None, bytearray(_alarm_frame(code)))
    assert ("error", event_type, {"code": code}) in events


@pytest.mark.parametrize("code", [2562, 6657, 6913, 9479])
def test_silent_list_codes_fire_nothing(code):
    client, events = _client_with_events()
    client._on_notification(None, bytearray(_alarm_frame(code)))
    assert events == []


def test_unknown_code_fires_nothing():
    client, events = _client_with_events()
    client._on_notification(None, bytearray(_alarm_frame(99999)))
    assert events == []


def test_c1_marker_on_the_alarm_id_is_ignored():
    """The app explicitly ignores 0xFFFE frames with the normal 0xC1
    marker (ErrorBle2Model.excute is empty) — so do we."""
    client, events = _client_with_events()
    frame = bytearray(_alarm_frame(8449))
    frame[9] = 0xC1
    client._on_notification(None, frame)
    assert events == []


def test_alarm_event_types_are_registered_on_the_event_entity():
    from custom_components.xbloom.event import ERROR_EVENT_TYPES

    for event_type in (
        "mismatched_power", "brewing_error", "dock_moving_error",
        "grinding_error", "scale_overload", "upgrade_failed",
    ):
        assert event_type in ERROR_EVENT_TYPES
