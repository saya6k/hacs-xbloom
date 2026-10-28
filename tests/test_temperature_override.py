"""xbloom__execute_recipe takes a water-temperature override.

Live 2026-10-28: asked for a coffee "at 15 g and 93 °C", the agent could
override the dose but had no way to change the temperature, so it saved
a new recipe ("15g 93도 커피") instead of brewing a saved one with
overrides.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.llm.recipe import XBloomExecuteRecipeTool
from tests.test_llm_recipe_prearm import _call
from tests.test_llm_recipe_prearm import _coordinator as _tool_coordinator
from tests.test_recipes_arm_confirm import (
    _COFFEE_RECIPE,
    _TEA_RECIPE,
    _Coordinator,
    _no_sleep,
)


def test_temperature_override_applies_to_every_pour(monkeypatch):
    _no_sleep(monkeypatch)
    recipe = {
        **_COFFEE_RECIPE,
        "pours": [
            {"volume_ml": 50, "temperature_c": 96, "pause_seconds": 30},
            {"volume_ml": 220, "temperature_c": 90, "pause_seconds": 0},
        ],
    }
    coordinator = _Coordinator({"V60": recipe}, "V60")
    asyncio.run(coordinator.async_arm_recipe(overrides={"temperature_c": 93}))
    assert [p.temperature for p in coordinator._active_recipe_pours] == [93, 93]
    # The stored recipe is unchanged.
    assert [p["temperature_c"] for p in recipe["pours"]] == [96, 90]


def test_temperature_override_works_with_a_dose_override(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator({"V60": _COFFEE_RECIPE}, "V60")
    asyncio.run(
        coordinator.async_arm_recipe(overrides={"dose_g": 15.0, "temperature_c": 93})
    )
    assert sum(p.volume for p in coordinator._active_recipe_pours) == 225
    assert {p.temperature for p in coordinator._active_recipe_pours} == {93}


def test_temperature_override_applies_to_tea(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator({"Chamomile": _TEA_RECIPE}, "Chamomile")
    coordinator.data["version"] = "V12.0D.500"
    asyncio.run(coordinator.async_arm_recipe(overrides={"temperature_c": 85}))
    assert {p.temperature for p in coordinator._active_recipe_pours} == {85}


def test_tool_passes_the_temperature_override():
    coord = _tool_coordinator()
    _call(coord, {"recipe": "V60", "temperature_c": 93})
    assert coord.async_arm_recipe.await_args.kwargs["overrides"] == {"temperature_c": 93}


def test_tool_schema_accepts_the_temperature_override():
    tool = XBloomExecuteRecipeTool(None, None)
    assert tool.parameters({"recipe": "V60", "temperature_c": 93})["temperature_c"] == 93
