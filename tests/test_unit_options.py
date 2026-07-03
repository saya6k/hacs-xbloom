"""Tests for the machine display-unit code mappings (commands 8005/8010).

These ints are dictated by the firmware protocol (PROTOCOL.md:
CodeModule(8005, value) — 0=g/1=oz/2=ml; CodeModule(8010, value) —
0=°C/1=°F), confirmed live against a real J15 Studio (2026-07-04). A
silent edit to these dicts would send the wrong unit to the machine
with no error — this pins the values down.
"""
from __future__ import annotations

from custom_components.xbloom.coordinator import TEMP_UNIT_OPTIONS, WEIGHT_UNIT_OPTIONS


def test_weight_unit_codes_match_protocol():
    assert WEIGHT_UNIT_OPTIONS == {"g": 0, "oz": 1, "ml": 2}


def test_temp_unit_codes_match_protocol():
    assert TEMP_UNIT_OPTIONS == {"c": 0, "f": 1}
