"""Tests for bidirectional RD_ErrorLackOfWater (40522) handling.

Reproduces a real deadlock reported on hardware 2026-07-17: after a
water-shortage error, refilling the tank never cleared the shortage flag,
so async_execute_recipe's low-water gate blocked every subsequent brew —
and the only flag-clearing path (a successful brew notification) was
itself behind that gate.

The official app's decompiled ErrorLackOfWaterBleModel parses the 40522
payload's first 4 bytes (LE) as a value — 0 = tank empty, 1 = water
restored — and HomeActivity dismisses the warning on value == 1. Our
client used to fire ("error", "water_shortage") for every 40522
regardless of payload, turning the firmware's own "refilled" notification
into a re-trigger of the shortage.
"""
from __future__ import annotations

from custom_components.xbloom._client import XBloomClientWithEvents
from xbloom.protocol import XBloomResponse


def _frame(value: int) -> bytes:
    # header/dev_id/type/cmd/len fill (10 bytes) | payload[0:4] LE | crc(2)
    return b"\x58\x02\x00\x00\x00\x00\x00\x00\x00\x00" + value.to_bytes(4, "little") + b"\x00\x00"


def _client_with_events():
    client = XBloomClientWithEvents(mac_address="AA:BB:CC:DD:EE:FF")
    events = []
    client.on_event(lambda cat, etype, attrs: events.append((cat, etype)))
    return client, events


def test_value_zero_fires_water_shortage_error():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_ErrorLackOfWater, _frame(0))
    assert ("error", "water_shortage") in events
    assert client._status.water_level_ok is False


def test_value_one_fires_water_refilled_notification():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_ErrorLackOfWater, _frame(1))
    assert ("notification", "water_refilled") in events
    assert ("error", "water_shortage") not in events
    assert client._status.water_level_ok is True


def test_shortage_then_refill_round_trip():
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_ErrorLackOfWater, _frame(0))
    assert client._status.water_level_ok is False
    client._handle_response(XBloomResponse.RD_ErrorLackOfWater, _frame(1))
    assert client._status.water_level_ok is True
    assert events == [("error", "water_shortage"), ("notification", "water_refilled")]


def test_truncated_payload_defaults_to_shortage():
    # A malformed/short frame must not crash and must err on the side of
    # reporting a shortage (value defaults to 0), matching the pre-fix
    # behavior for frames we can't parse.
    client, events = _client_with_events()
    client._handle_response(XBloomResponse.RD_ErrorLackOfWater, b"\x58\x02\x00")
    assert ("error", "water_shortage") in events
