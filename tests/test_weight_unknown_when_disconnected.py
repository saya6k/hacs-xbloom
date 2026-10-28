"""sensor.weight reads unknown, not 0.0 g, while there is no BLE link.

The coordinator falls back to DEFAULT_STATE whenever the link is down
(idle standby, out of range). A 0.0 g default there was indistinguishable
from a real empty scale. The scale itself keeps measuring while the machine
sleeps (20501 streams ~5 Hz through sleep, hardware 2026-10-14), so only a
missing link makes the reading unknown.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.xbloom.coordinator.constants import DEFAULT_STATE
from custom_components.xbloom.sensor import XBloomWeightSensor


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
