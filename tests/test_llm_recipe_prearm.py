"""xbloom__execute_recipe is two-phase: arm, ask, confirm.

The first call always arms the recipe (overrides included) so the
machine is showing its start prompt while the agent asks the user about
the returned checklist. confirmed=true starts only a standing arm of the
same recipe; without one it arms again and asks again — there is no
one-shot path.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers import llm

from custom_components.xbloom.llm.recipe import XBloomExecuteRecipeTool

_V60 = {
    "name": "V60",
    "cup_type": "omni_dripper",
    "grind_size": 35,
    "dose_g": 18.0,
    "ratio": 15.0,
    "pours": [{"volume_ml": 270, "temperature_c": 93, "pause_seconds": 30}],
}
_WATER_ONLY = {
    "name": "Hot water",
    "cup_type": "other",
    "grind_size": 0,
    "dose_g": 0,
    "pours": [{"volume_ml": 200, "temperature_c": 90, "pause_seconds": 0}],
}


def _coordinator(*, armed=None, selected=None, weight=0.0):
    coord = SimpleNamespace(
        client=SimpleNamespace(is_connected=True),
        recipes={"V60": _V60, "Hot water": _WATER_ONLY},
        water_source=0,
        data={"water_level_ok": True, "weight": weight},
        _armed_operation=armed,
        selected_recipe=selected,
        grind_size=35,
        rpm=90,
        async_cancel=AsyncMock(),
        async_confirm_recipe=AsyncMock(),
        async_execute_recipe=AsyncMock(),
        async_update_listeners=Mock(),
    )

    def _select(name):
        coord.selected_recipe = name

    async def _arm(**_kwargs):
        coord._armed_operation = "recipe"

    coord.select_recipe = Mock(side_effect=_select)
    coord.async_arm_recipe = AsyncMock(side_effect=_arm)
    return coord


def _call(coord, args):
    tool = XBloomExecuteRecipeTool(coord, None)
    return asyncio.run(
        tool.async_call(None, llm.ToolInput(tool_name=tool.name, tool_args=args), None)
    )


def test_first_call_arms_and_returns_checklist():
    coord = _coordinator()
    result = _call(coord, {"recipe": "V60"})
    assert not result.error
    assert result.data["armed"]
    assert result.data["confirmation_required"]
    checklist = " ".join(result.data["checklist"])
    for item in ("beans", "dripper", "filter", "cup"):
        assert item in checklist
    coord.async_arm_recipe.assert_awaited_once()
    coord.async_confirm_recipe.assert_not_awaited()
    coord.async_execute_recipe.assert_not_awaited()


def test_overrides_are_armed_not_skipped():
    coord = _coordinator()
    _call(coord, {"recipe": "V60", "dose_g": 20.0, "bypass_volume": 50})
    kwargs = coord.async_arm_recipe.await_args.kwargs
    assert kwargs["overrides"] == {"dose_g": 20.0}
    assert kwargs["bypass_volume"] == 50.0


def test_confirmed_without_standing_arm_rearms_instead_of_starting():
    coord = _coordinator()
    result = _call(coord, {"recipe": "V60", "confirmed": True})
    assert result.data["armed"]
    assert "NOT started" in result.data["instruction"]
    coord.async_arm_recipe.assert_awaited_once()
    coord.async_confirm_recipe.assert_not_awaited()
    coord.async_execute_recipe.assert_not_awaited()


def test_confirmed_with_standing_arm_starts():
    coord = _coordinator(armed="recipe", selected="V60")
    result = _call(coord, {"recipe": "V60", "confirmed": True})
    assert result.data["success"]
    assert not result.data.get("armed")
    coord.async_confirm_recipe.assert_awaited_once()
    coord.async_arm_recipe.assert_not_awaited()


def test_confirmed_for_a_different_recipe_rearms():
    coord = _coordinator(armed="recipe", selected="Hot water")
    _call(coord, {"recipe": "V60", "confirmed": True})
    coord.async_confirm_recipe.assert_not_awaited()
    coord.async_cancel.assert_awaited_once()
    coord.async_arm_recipe.assert_awaited_once()


def test_water_only_recipe_with_cup_has_empty_checklist():
    coord = _coordinator(weight=150.0)
    result = _call(coord, {"recipe": "Hot water"})
    assert result.data["armed"]
    assert result.data["checklist"] == []


def test_unknown_weight_asks_about_the_cup():
    coord = _coordinator(weight=None)
    result = _call(coord, {"recipe": "Hot water"})
    assert result.data["armed"]
    assert any("cup" in item for item in result.data["checklist"])


def test_failed_arm_is_a_tool_error():
    coord = _coordinator()
    coord.async_arm_recipe = AsyncMock()  # swallows, never sets the arm
    result = _call(coord, {"recipe": "V60"})
    assert result.error
    assert result.data["error"] == "arm_failed"


def test_low_water_refuses_before_arming():
    coord = _coordinator()
    coord.data["water_level_ok"] = False
    result = _call(coord, {"recipe": "V60"})
    assert result.data["error"] == "water_low"
    coord.async_arm_recipe.assert_not_awaited()
