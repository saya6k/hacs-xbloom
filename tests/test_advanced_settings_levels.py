"""Tests for coordinator._vibration_level_to_raw / _pour_radius_level_to_raw
— the level-to-raw-device-value conversion backing the advanced_settings
service's pour_radius_level / vibration_amplitude_level fields. Formulas
decompiled from the official app 2026-07-16 (MachineSetPourRadiusActivity /
MachineSetVibrationAmplitudeActivity) — see AGENTS.md.
"""
from __future__ import annotations

from custom_components.xbloom.coordinator import (
    _pour_radius_level_to_raw,
    _vibration_level_to_raw,
)


def test_vibration_level_to_raw_fixed_scale():
    assert _vibration_level_to_raw(0) == 1000  # L1, min
    assert _vibration_level_to_raw(2) == 1200
    assert _vibration_level_to_raw(5) == 1500  # L6, max


def test_pour_radius_level_centers_on_given_reference():
    center = 840
    assert _pour_radius_level_to_raw(2, center) == center  # L3 == center
    assert _pour_radius_level_to_raw(0, center) == center - 160  # L1
    assert _pour_radius_level_to_raw(1, center) == center - 80  # L2
    assert _pour_radius_level_to_raw(3, center) == center + 80  # L4
    assert _pour_radius_level_to_raw(4, center) == center + 160  # L5


def test_pour_radius_level_tracks_whatever_center_is_passed():
    # Center isn't a fixed constant — it's whatever the machine's last
    # known pour_radius reading was (see async_set_advanced_settings'
    # docstring for why). Different centers -> different absolute values
    # for the same level.
    assert _pour_radius_level_to_raw(2, 680) == 680
    assert _pour_radius_level_to_raw(0, 680) == 520
