"""The LLM tools report a failed arm/confirm instead of claiming success.

Live 2026-10-28: a recipe confirm logged "Recipe confirm error" while the
agent told the user the brew had started.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.xbloom.llm.grind import XBloomGrindTool
from custom_components.xbloom.llm.pour import XBloomPourTool
from tests.test_llm_recipe_prearm import _call
from tests.test_llm_recipe_prearm import _coordinator as _recipe_coordinator
from tests.test_llm_results import call


def _ops_coordinator(*, armed=None, ok=True):
    return SimpleNamespace(
        client=SimpleNamespace(is_connected=True),
        grind_size=50,
        rpm=80,
        temperature=93,
        volume=200,
        flow_rate=3.0,
        _armed_operation=armed,
        async_arm_grind=AsyncMock(return_value=ok),
        async_confirm_grind=AsyncMock(return_value=ok),
        async_arm_pour=AsyncMock(return_value=ok),
        async_confirm_pour=AsyncMock(return_value=ok),
        async_update_listeners=Mock(),
    )


def test_failed_recipe_confirm_is_reported():
    coord = _recipe_coordinator(armed="recipe", selected="V60")
    coord.async_confirm_recipe = AsyncMock(return_value=False)
    result = _call(coord, {"recipe": "V60", "confirmed": True})
    assert result.error
    assert not result.data["success"]


def test_failed_grind_arm_is_reported():
    result = call(XBloomGrindTool(_ops_coordinator(ok=False), None))
    assert result.error
    assert not result.data["success"]


def test_failed_grind_confirm_is_reported():
    coord = _ops_coordinator(armed="grind", ok=False)
    result = call(XBloomGrindTool(coord, None), {"confirmed": True})
    assert result.error
    assert not result.data["success"]


def test_failed_pour_arm_is_reported():
    coord = _ops_coordinator(ok=False)
    result = call(XBloomPourTool(coord, None), {"temperature": 93, "volume": 200})
    assert result.error
    assert not result.data["success"]


def test_failed_pour_confirm_is_reported():
    coord = _ops_coordinator(armed="pour", ok=False)
    result = call(
        XBloomPourTool(coord, None),
        {"temperature": 93, "volume": 200, "confirmed": True},
    )
    assert result.error
    assert not result.data["success"]


def test_successful_pour_arm_is_not_an_error():
    coord = _ops_coordinator(ok=True)
    result = call(XBloomPourTool(coord, None), {"temperature": 93, "volume": 200})
    assert not result.error
    assert result.data["armed"]
