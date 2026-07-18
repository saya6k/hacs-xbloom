"""Tests for OperationsMixin's two-stage arm/confirm manual grind/pour
button flow (2026-07-18) — see coordinator/__init__.py's
_armed_operation docstring for the full design. HA button entity only:
async_grind()/async_pour() (used by the execute_recipe service path and
every LLM tool) are untouched and still act in one call.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator.operations import OperationsMixin


class _FakeGrinder:
    def __init__(self) -> None:
        self.enter_mode_calls: list[dict] = []
        self.confirm_start_calls = 0
        self.stop_calls = 0

    async def enter_mode(self, size=None, speed=None) -> bool:
        self.enter_mode_calls.append({"size": size, "speed": speed})
        return True

    async def confirm_start(self) -> bool:
        self.confirm_start_calls += 1
        return True

    async def stop(self) -> bool:
        self.stop_calls += 1
        return True


class _FakeBrewer:
    def __init__(self) -> None:
        self.enter_mode_calls = 0
        self.start_calls: list[dict] = []
        self.stop_calls = 0

    async def enter_mode(self) -> bool:
        self.enter_mode_calls += 1
        return True

    async def start(self, **kwargs) -> bool:
        self.start_calls.append(kwargs)
        return True

    async def stop(self) -> bool:
        self.stop_calls += 1
        return True


class _FakeClient:
    def __init__(self) -> None:
        self.grinder = _FakeGrinder()
        self.brewer = _FakeBrewer()
        self.sent_commands: list[int] = []
        self.stop_recipe_calls = 0

    async def _send_command(self, command, *args, **kwargs) -> bool:
        self.sent_commands.append(int(command))
        return True

    async def stop_recipe(self) -> bool:
        self.stop_recipe_calls += 1
        return True


class _Coordinator(OperationsMixin):
    def __init__(self) -> None:
        self.client = _FakeClient()
        self.volume = 100.0
        self.temperature = 93.0
        self.flow_rate = 3.0
        self.water_source = 0
        self.pour_pattern = 2
        self.grind_size = 40
        self.rpm = 90
        self._active_operation = None
        self._armed_operation = None
        self._pod_prompt_active = False
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self.data = {}
        self.restore_persisted_mode_calls = 0

    def _check_connected(self) -> bool:
        return True

    async def _ensure_pro_mode(self) -> None:
        return None

    async def _async_retry_while_sleeping(self, action):
        return await action()

    async def _restore_persisted_mode(self, _reason) -> None:
        self.restore_persisted_mode_calls += 1


def test_arm_grind_enters_mode_without_starting():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_grind())

    assert len(coordinator.client.grinder.enter_mode_calls) == 1
    assert coordinator.client.grinder.confirm_start_calls == 0
    assert coordinator._armed_operation == "grind"


def test_confirm_grind_starts_and_clears_armed_state():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_grind())
    asyncio.run(coordinator.async_confirm_grind())

    assert coordinator.client.grinder.confirm_start_calls == 1
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "manual_grind"


def test_arm_pour_enters_mode_without_starting():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_pour())

    assert coordinator.client.brewer.enter_mode_calls == 1
    assert coordinator.client.brewer.start_calls == []
    assert coordinator._armed_operation == "pour"


def test_confirm_pour_starts_with_current_sliders_and_clears_armed_state():
    coordinator = _Coordinator()
    coordinator.volume = 250.0
    asyncio.run(coordinator.async_arm_pour())
    asyncio.run(coordinator.async_confirm_pour())

    assert len(coordinator.client.brewer.start_calls) == 1
    assert coordinator.client.brewer.start_calls[0]["volume"] == 250.0
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "manual_pour"


def test_cancel_while_armed_backs_out_without_heavier_stop_sequence():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_grind())
    asyncio.run(coordinator.async_cancel())

    assert coordinator._armed_operation is None
    # Backs out via Back to Home (8022), not the grinder/brewer stop or
    # whole-recipe stop sequence — nothing had actually started yet.
    assert coordinator.client.sent_commands == [8022]
    assert coordinator.client.grinder.stop_calls == 0
    assert coordinator.client.brewer.stop_calls == 0
    assert coordinator.client.stop_recipe_calls == 0


def test_pause_resume_is_a_noop_while_armed():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_pour())
    asyncio.run(coordinator.async_pause_resume())

    assert coordinator.client.brewer.start_calls == []
    assert coordinator.client.sent_commands == []
