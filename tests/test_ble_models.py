"""Tests for the native ble/models.py — Phase 2a of the de-vendoring
refactor. Parity tests cross-check against the vendored src/xbloom
implementation (reference-only per the ADR, imported here only as a test
oracle) — see test_ble_framing.py's module docstring for why that's the
right verification strategy.
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

vendor_types = pytest.importorskip("xbloom.models.types")
vendor_recipes = pytest.importorskip("xbloom.models.recipes")


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


def _make_vendor_recipe(**overrides):
    defaults = dict(
        grind_size=35,
        total_water=250,
        rpm=90,
        cup_type=int(CupType.OMNI_DRIPPER),
        name="Test",
        bean_weight=18.0,
        pours=[
            vendor_types.PourStep(volume=50, temperature=93, flow_rate=3.0, pausing=30, pattern=vendor_types.PourPattern.SPIRAL),
            vendor_types.PourStep(volume=200, temperature=92, flow_rate=3.0, pausing=0, pattern=vendor_types.PourPattern.SPIRAL),
        ],
    )
    defaults.update(overrides)
    return vendor_types.XBloomRecipe(**defaults)


def test_build_recipe_payload_matches_vendor_simple():
    assert build_recipe_payload(_make_recipe()) == vendor_recipes.build_recipe_payload(
        _make_vendor_recipe()
    )


def test_build_recipe_payload_matches_vendor_with_volume_chunking():
    # >127ml pour forces the sub-step chunking path.
    recipe = _make_recipe(pours=[PourStep(volume=300, temperature=90, pausing=0)])
    vendor_recipe = _make_vendor_recipe(
        pours=[vendor_types.PourStep(volume=300, temperature=90, pausing=0)]
    )
    assert build_recipe_payload(recipe) == vendor_recipes.build_recipe_payload(vendor_recipe)


def test_build_recipe_payload_matches_vendor_tea_shape():
    # No-grind, no-dose tea-style recipe (rpm still must be a valid value).
    recipe = _make_recipe(
        grind_size=0,
        bean_weight=0.0,
        pours=[
            PourStep(volume=120, temperature=80, flow_rate=3.0, pausing=60),
            PourStep(volume=120, temperature=80, flow_rate=3.0, pausing=0),
        ],
    )
    vendor_recipe = _make_vendor_recipe(
        grind_size=0,
        bean_weight=0.0,
        pours=[
            vendor_types.PourStep(volume=120, temperature=80, flow_rate=3.0, pausing=60),
            vendor_types.PourStep(volume=120, temperature=80, flow_rate=3.0, pausing=0),
        ],
    )
    assert build_recipe_payload(recipe) == vendor_recipes.build_recipe_payload(vendor_recipe)


def test_pour_step_rejects_out_of_range_temperature_like_vendor():
    with pytest.raises(ValueError):
        PourStep(volume=50, temperature=150)
    with pytest.raises(ValueError):
        vendor_types.PourStep(volume=50, temperature=150)


def test_xbloom_recipe_rejects_invalid_rpm_like_vendor():
    with pytest.raises(ValueError):
        XBloomRecipe(rpm=75)
    with pytest.raises(ValueError):
        vendor_types.XBloomRecipe(rpm=75)


def test_vibration_pattern_and_cup_type_values_match_vendor():
    assert int(VibrationPattern.BOTH) == int(vendor_types.VibrationPattern.BOTH)
    assert int(CupType.TEA) == int(vendor_types.CupType.TEA)
    assert int(PourPattern.SPIRAL) == int(vendor_types.PourPattern.SPIRAL)
