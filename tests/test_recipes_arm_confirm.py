"""Tests for RecipesMixin's two-stage arm/confirm manual execute-recipe
button flow (2026-07-18) — see coordinator/__init__.py's
_armed_operation docstring for the full design. HA button entity only:
async_execute_recipe() (used by the execute_recipe / execute_tea_recipe
services and every LLM tool) is untouched and still brews in one call.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.coordinator.recipes import RecipesMixin


class _FakeClient:
    is_connected = True

    def __init__(self) -> None:
        self.raw_calls: list[tuple] = []
        self.plain_calls: list[tuple] = []
        self.executed = False
        self.status = SimpleNamespace(raw_state_label=None)

    async def _send_command_raw(self, command, data, device_id=None, type_code=0x01):
        self.raw_calls.append((int(command), bytes(data), type_code))
        return True

    async def _send_command(self, command, payload=None, device_id=None):
        self.plain_calls.append(("_send_command", int(command), payload))
        return True

    async def set_bypass(self, volume, temperature, dose):
        self.plain_calls.append(("set_bypass", volume, temperature, dose))
        return True

    async def set_cup(self, cup_max, cup_min):
        self.plain_calls.append(("set_cup", cup_max, cup_min))
        return True

    async def execute_coffee_recipe(self, device_id=None):
        self.executed = True
        # See test_recipe_arm_confirm.py — satisfies the post-8002 state
        # verifier immediately.
        self.status.raw_state_label = "brewing"

    # See the same block in test_recipe_arm_confirm.py — the arm chains
    # are ACK-gated, so they route through send_and_wait.
    _bypass_args = staticmethod(XBloomClient._bypass_args)
    _cup_args = staticmethod(XBloomClient._cup_args)

    async def send_and_wait(
        self, command, data=None, *, raw=None, timeout=1.5,
        device_id=None, type_code=0x01,
    ):
        if raw is not None:
            await self._send_command_raw(command, raw, device_id, type_code)
        else:
            await self._send_command(command, data, device_id)
        return b""


_COFFEE_RECIPE = {
    "name": "V60",
    "cup_type": "omni_dripper",
    "grind_size": 35,
    "dose_g": 18.0,
    "ratio": 15.0,
    "pours": [{"volume_ml": 270, "temperature_c": 93, "pause_seconds": 30}],
}

_TEA_RECIPE = {
    "name": "Chamomile",
    "cup_type": "tea",
    "grind_size": 0,
    "dose_g": 0,
    "pours": [{"volume_ml": 120, "temperature_c": 80, "pause_seconds": 60}],
}


class _Coordinator(RecipesMixin):
    def __init__(self, recipes: dict, selected_recipe: str) -> None:
        self.client = _FakeClient()
        self.recipes = recipes
        self.selected_recipe = selected_recipe
        self.water_source = 0
        self.data = {"water_level_ok": True, "version": "V12.0D.500"}
        self.grind_size = 35
        self.rpm = 90
        self._active_operation = None
        self._armed_operation = None
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None

    async def _async_ensure_connected(self) -> bool:
        return True

    async def _async_retry_while_sleeping(self, action):
        return await action()


def _no_sleep(monkeypatch):
    async def _fast_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def test_arm_coffee_queues_without_executing(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator({"V60": _COFFEE_RECIPE}, "V60")
    asyncio.run(coordinator.async_arm_recipe())

    assert coordinator.client.executed is False
    assert coordinator._armed_operation == "recipe"
    assert coordinator._armed_recipe_is_tea is False
    assert coordinator._armed_recipe_tea_payload is None
    # Not yet actually executing.
    assert coordinator._executing_recipe is False


def test_confirm_coffee_executes_and_clears_armed_state(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator({"V60": _COFFEE_RECIPE}, "V60")
    asyncio.run(coordinator.async_arm_recipe())
    asyncio.run(coordinator.async_confirm_recipe())

    assert coordinator.client.executed is True
    assert coordinator._armed_operation is None
    assert coordinator._executing_recipe is True
    assert coordinator._active_operation == "recipe"


def test_arm_tea_queues_without_making(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator({"Chamomile": _TEA_RECIPE}, "Chamomile")
    asyncio.run(coordinator.async_arm_recipe())

    assert coordinator._armed_operation == "recipe"
    assert coordinator._armed_recipe_is_tea is True
    assert coordinator._armed_recipe_tea_payload is not None
    assert all(cmd != 4512 for cmd, _payload, _type in coordinator.client.raw_calls)


def test_confirm_tea_resends_the_armed_payload(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator({"Chamomile": _TEA_RECIPE}, "Chamomile")
    asyncio.run(coordinator.async_arm_recipe())
    armed_payload = coordinator._armed_recipe_tea_payload

    asyncio.run(coordinator.async_confirm_recipe())

    make_calls = [c for c in coordinator.client.raw_calls if c[0] == 4512]
    assert len(make_calls) == 1
    assert make_calls[0][1] == armed_payload
    assert coordinator._armed_operation is None
    assert coordinator._armed_recipe_tea_payload is None


def test_arm_with_no_recipe_selected_is_a_noop():
    coordinator = _Coordinator({}, "")
    asyncio.run(coordinator.async_arm_recipe())

    assert coordinator._armed_operation is None
    assert coordinator.client.raw_calls == []
