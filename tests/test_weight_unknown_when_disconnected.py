"""sensor.weight reads unknown, not a made-up number, when there is no reading.

The coordinator falls back to DEFAULT_STATE whenever the link is down
(idle standby, out of range). A 0.0 g default there was indistinguishable
from a real empty scale.

While the machine sleeps, 20501 keeps streaming but carries a fixed 50.0
with nothing on the scale. Live 2026-10-28: over 8 hours of history the
weight jumped to exactly 50.0 in the same second the state went sleeping,
every time, and back to 0.0 on wake. So a sleeping machine has no reading
either.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.xbloom.ble.models import DeviceStatus
from custom_components.xbloom.coordinator.constants import DEFAULT_STATE
from custom_components.xbloom.sensor import XBloomWeightSensor
from tests.test_connection_idle_standby import (
    _AsleepClient,
    _full_path_coordinator,
    _tick,
)


def _sensor(data: dict) -> XBloomWeightSensor:
    sensor = object.__new__(XBloomWeightSensor)
    sensor.coordinator = SimpleNamespace(data=data)
    return sensor


def test_disconnected_default_has_no_weight():
    assert DEFAULT_STATE["weight"] is None


def test_sensor_is_unknown_when_disconnected():
    assert _sensor({**DEFAULT_STATE}).native_value is None


def test_sensor_reports_a_real_zero_when_connected():
    assert _sensor({**DEFAULT_STATE, "connected": True, "weight": 0.0}).native_value == 0.0


def test_sleeping_machine_weight_is_unknown():
    client = _AsleepClient()
    client.status.scale.weight = 50.0  # the firmware's sleep placeholder
    data = asyncio.run(_tick(_full_path_coordinator(client)))
    assert data["state"] == "sleeping"
    assert data["weight"] is None


def test_awake_machine_reports_its_weight():
    client = _AsleepClient()
    client._sleeping = False
    client.status = DeviceStatus(is_sleeping=False)
    client.status.scale.weight = 12.34
    data = asyncio.run(_tick(_full_path_coordinator(client)))
    assert data["weight"] == 12.3
