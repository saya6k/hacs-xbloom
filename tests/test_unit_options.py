"""Tests for the machine display-unit code mappings (commands 8005/8010).

These ints are the official app's (jadx 2026-10-15): CodeModule(8005,
WeightUnitType) — ml=0/g=1/oz=2; MachineJ15Fragment's °C button sends
CodeModule(8010, 1) and °F sends 0. Each is one LE u32. Hardware
2026-10-15: 8010 [0] switched the Studio to °F and [1] back, while the
former 1-byte payload was ACKed and ignored. A silent edit to these dicts
would send the wrong unit to the machine with no error — this pins the
values down.
"""
from __future__ import annotations

from custom_components.xbloom.coordinator import TEMP_UNIT_OPTIONS, WEIGHT_UNIT_OPTIONS


def test_weight_unit_codes_match_protocol():
    assert WEIGHT_UNIT_OPTIONS == {"ml": 0, "g": 1, "oz": 2}


def test_temp_unit_codes_match_protocol():
    assert TEMP_UNIT_OPTIONS == {"f": 0, "c": 1}


def test_machine_report_uses_the_same_codes():
    """8015 carries the same codes: the app stores them as-is
    (DeviceUnitBleModel) and reads them with the tables above."""
    from custom_components.xbloom.coordinator.constants import (
        _RAW_TO_TEMP_UNIT,
        _RAW_TO_WEIGHT_UNIT,
    )

    assert _RAW_TO_WEIGHT_UNIT == {0: "ml", 1: "g", 2: "oz"}
    assert _RAW_TO_TEMP_UNIT == {0: "f", 1: "c"}
