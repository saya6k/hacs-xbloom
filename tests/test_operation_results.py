"""Arm/confirm coordinator methods report whether they landed.

They log and swallow BLE failures (the HA buttons ignore the result), so
the LLM tools had no way to tell a failed confirm from a started one and
told the user it had started. Live 2026-10-28: a recipe confirm logged
"Recipe confirm error" while the agent said the brew had started.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from tests.test_operations_arm_confirm import _Coordinator as _OpsCoordinator
from tests.test_recipes_arm_confirm import _COFFEE_RECIPE, _no_sleep
from tests.test_recipes_arm_confirm import _Coordinator as _RecipeCoordinator

_FAIL = AsyncMock(side_effect=TimeoutError("No ACK"))


def test_confirm_recipe_reports_success(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _RecipeCoordinator({"V60": _COFFEE_RECIPE}, "V60")
    asyncio.run(coordinator.async_arm_recipe())
    assert asyncio.run(coordinator.async_confirm_recipe()) is True


def test_confirm_recipe_reports_failure(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _RecipeCoordinator({"V60": _COFFEE_RECIPE}, "V60")
    asyncio.run(coordinator.async_arm_recipe())
    coordinator.client.execute_coffee_recipe = _FAIL
    assert asyncio.run(coordinator.async_confirm_recipe()) is False


def test_confirm_recipe_reports_no_connection(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _RecipeCoordinator({"V60": _COFFEE_RECIPE}, "V60")

    async def _offline():
        return False

    coordinator._async_ensure_connected = _offline
    assert asyncio.run(coordinator.async_confirm_recipe()) is False


def test_grind_arm_and_confirm_report_success():
    coordinator = _OpsCoordinator()
    assert asyncio.run(coordinator.async_arm_grind()) is True
    assert asyncio.run(coordinator.async_confirm_grind()) is True


def test_grind_arm_and_confirm_report_failure():
    coordinator = _OpsCoordinator()
    coordinator.client.grinder.enter_mode = _FAIL
    coordinator.client.grinder.confirm_start = _FAIL
    assert asyncio.run(coordinator.async_arm_grind()) is False
    assert asyncio.run(coordinator.async_confirm_grind()) is False


def test_pour_arm_and_confirm_report_success(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _OpsCoordinator()
    assert asyncio.run(coordinator.async_arm_pour()) is True
    assert asyncio.run(coordinator.async_confirm_pour()) is True


def test_pour_arm_and_confirm_report_failure(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _OpsCoordinator()
    coordinator.client.brewer.enter_mode = _FAIL
    coordinator.client.brewer.start = _FAIL
    assert asyncio.run(coordinator.async_arm_pour()) is False
    assert asyncio.run(coordinator.async_confirm_pour()) is False


def test_pour_arm_survives_a_failed_setpoint_push(monkeypatch):
    # The temperature/pattern push after the arm is best-effort.
    _no_sleep(monkeypatch)
    coordinator = _OpsCoordinator()
    coordinator.client.brewer.set_temperature = _FAIL
    assert asyncio.run(coordinator.async_arm_pour()) is True
