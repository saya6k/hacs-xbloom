"""Tests for cmd 8015 (RD_UNIT_CHANGE) parsing in _client.py.

The machine pushes 8015 when its display units / water source are changed
on its own touchscreen. Decompiled from the official app's
DeviceUnitBleModel: payload is three LE uint32s — [0:4] weight unit
(0=g/1=oz/2=ml), [4:8] temperature unit (0=C/1=F), [8:12] water source
(0=tank/1=direct). The client fires a coordinator-internal "settings"
event (never surfaced on the notification event entity, which filters on
category) carrying the raw values.
"""
from __future__ import annotations

from custom_components.xbloom._client import XBloomClientWithEvents
from xbloom.protocol import XBloomResponse


def _frame(weight: int, temp: int, water: int) -> bytes:
    # header/dev_id/type/cmd/len fill (10 bytes) | 3x LE uint32 | crc(2)
    payload = (
        weight.to_bytes(4, "little")
        + temp.to_bytes(4, "little")
        + water.to_bytes(4, "little")
    )
    return b"\x58\x02\x00\x00\x00\x00\x00\x00\x00\x00" + payload + b"\x00\x00"


def _client_with_events():
    client = XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")
    events = []
    client.on_event(lambda cat, etype, attrs: events.append((cat, etype, attrs)))
    return client, events


def test_unit_change_fires_settings_event_with_parsed_values():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_UNIT_CHANGE, _frame(2, 1, 1))
    assert events == [
        (
            "settings",
            "unit_change",
            {"weight_unit": 2, "temp_unit": 1, "water_source": 1},
        )
    ]


def test_unit_change_zero_values_parse_correctly():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_UNIT_CHANGE, _frame(0, 0, 0))
    assert events == [
        (
            "settings",
            "unit_change",
            {"weight_unit": 0, "temp_unit": 0, "water_source": 0},
        )
    ]


def test_truncated_payload_is_ignored():
    # The app's own DeviceUnitBleModel bails out (all fields -1) below 12
    # payload bytes; we fire nothing rather than guessing.
    client, events = _client_with_events()
    client._handle_response(
        XBloomResponse.RD_UNIT_CHANGE,
        b"\x58\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x01\x00\x00\x00" + b"\x00\x00",
    )
    assert events == []
