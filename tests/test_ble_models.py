"""Tests for the native ble/models.py (see
adr/001-clean-room-reimplementation-of-xbloom-ble.md).

The build_recipe_payload tests below pin byte-exact output against *golden
vectors* — hex strings captured from the former vendored src/xbloom oracle
at de-vendoring time, while it still existed to generate them. The vendored
tree has since been removed; see test_ble_framing.py's module docstring for
why frozen vectors are the right verification strategy now.
"""
from __future__ import annotations

import pytest

from custom_components.xbloom.ble.models import (
    CupType,
    PourPattern,
    PourStep,
    VibrationPattern,
    XBloomRecipe,
    build_recipe_payload,
)


def _make_recipe(**overrides):
    defaults = dict(
        grind_size=35,
        total_water=250,
        rpm=90,
        cup_type=CupType.OMNI_DRIPPER,
        name="Test",
        bean_weight=18.0,
        pours=[
            PourStep(volume=50, temperature=93, flow_rate=3.0, pausing=30, pattern=PourPattern.SPIRAL),
            PourStep(volume=200, temperature=92, flow_rate=3.0, pausing=0, pattern=PourPattern.SPIRAL),
        ],
    )
    defaults.update(overrides)
    return XBloomRecipe(**defaults)


def test_build_recipe_payload_matches_golden_simple():
    assert build_recipe_payload(_make_recipe()).hex() == (
        "14325d0200e2005a1e7f5c0200495c02000000001e23c4"
    )


def test_build_recipe_payload_matches_golden_with_volume_chunking():
    # >127ml pour forces the sub-step chunking path.
    recipe = _make_recipe(pours=[PourStep(volume=300, temperature=90, pausing=0)])
    assert build_recipe_payload(recipe).hex() == (
        "107f5a02007f5a02002e5a020000005a1e23c4"
    )


def test_build_recipe_payload_matches_golden_tea_shape():
    # No-grind, no-dose tea-style recipe (rpm still must be a valid value).
    recipe = _make_recipe(
        grind_size=0,
        bean_weight=0.0,
        pours=[
            PourStep(volume=120, temperature=80, flow_rate=3.0, pausing=60),
            PourStep(volume=120, temperature=80, flow_rate=3.0, pausing=0),
        ],
    )
    assert build_recipe_payload(recipe).hex() == (
        "1078500200c4005a1e785002000000001e00c4"
    )


def test_pour_step_rejects_out_of_range_temperature():
    with pytest.raises(ValueError):
        PourStep(volume=50, temperature=150)


def test_xbloom_recipe_rejects_invalid_rpm():
    with pytest.raises(ValueError):
        XBloomRecipe(rpm=75)


def test_vibration_pattern_and_cup_type_values():
    # Frozen enum values (were cross-checked against the vendored oracle
    # before de-vendoring; see module docstring).
    assert int(VibrationPattern.BOTH) == 3
    assert int(CupType.TEA) == 4
    assert int(PourPattern.SPIRAL) == 2
