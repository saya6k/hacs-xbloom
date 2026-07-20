"""Tests for OperationsMixin's two-stage arm/confirm manual grind/pour
button flow (2026-07-18) — see coordinator/__init__.py's
_armed_operation docstring for the full design. HA button entity only:
async_grind()/async_pour() (used by the execute_recipe service path and
every LLM tool) are untouched and still act in one call.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom.coordinator import operations
from custom_components.xbloom.coordinator.operations import OperationsMixin


@pytest.fixture(autouse=True)
def _no_pour_arm_settle(monkeypatch):
    """Zero the pour-arm entry-push delays (T7) — screen-transition and
    inter-send pacing is hardware behavior, not test-relevant."""
    monkeypatch.setattr(operations, "_POUR_ARM_SETTLE_S", 0)
    monkeypatch.setattr(operations, "_POUR_ARM_PUSH_GAP_S", 0)


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
        self.set_temperature_calls: list[float] = []
        self.set_pattern_calls: list[int] = []

    async def set_temperature(self, temperature: float) -> bool:
        self.set_temperature_calls.append(temperature)
        return True

    async def set_pattern(self, pattern: int) -> bool:
        self.set_pattern_calls.append(pattern)
        return True

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
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._pod_prompt_active = False
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self.data = {}
        self.connected = True
        self.update_listeners_calls = 0

    async def _async_ensure_connected(self) -> bool:
        return self.connected

    def async_update_listeners(self) -> None:
        self.update_listeners_calls += 1

    async def _async_retry_while_sleeping(self, action):
        return await action()


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
    # Backs out of the grind page with APP_GRINDER_QUIT (8012) — what the
    # official app's GrinderActivity.onBackPressed() sends — not the
    # grinder/brewer stop or the whole-recipe stop sequence, since nothing
    # had actually started yet.
    assert coordinator.client.sent_commands == [8012]
    assert coordinator.client.grinder.stop_calls == 0
    assert coordinator.client.brewer.stop_calls == 0
    assert coordinator.client.stop_recipe_calls == 0


def test_cancel_while_armed_pour_quits_the_pour_page():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_pour())
    asyncio.run(coordinator.async_cancel())

    # APP_BREWER_QUIT (8013) — BrewerActivity.onBackPressed().
    assert coordinator.client.sent_commands == [8013]
    assert coordinator._armed_operation is None


def test_cancel_while_armed_recipe_quits_the_recipe_start_screen():
    coordinator = _Coordinator()
    coordinator._armed_operation = "recipe"
    asyncio.run(coordinator.async_cancel())

    # APP_RECIPE_START_QUIT (8017) — the start dialog's own dismiss
    # handler in RecipeDetailActivity/PodsDetailActivity.
    assert coordinator.client.sent_commands == [8017]
    assert coordinator._armed_operation is None


def test_cancel_with_pod_prompt_over_armed_recipe_sends_the_command_once():
    coordinator = _Coordinator()
    coordinator._armed_operation = "recipe"
    coordinator._pod_prompt_active = True
    asyncio.run(coordinator.async_cancel())

    assert coordinator.client.sent_commands == [8017]
    assert coordinator._pod_prompt_active is False


def test_cancel_clears_armed_state_even_when_disconnected():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_grind())
    coordinator.connected = False
    asyncio.run(coordinator.async_cancel())

    # Nothing reaches the machine, but the armed flag must still clear:
    # leaving it set makes the next press of the same button CONFIRM
    # (start a real grind) instead of arm.
    assert coordinator._armed_operation is None
    assert coordinator.client.sent_commands == []
    assert coordinator.update_listeners_calls == 1


def test_pause_resume_is_a_noop_while_armed():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_pour())
    asyncio.run(coordinator.async_pause_resume())

    assert coordinator.client.brewer.start_calls == []
    assert coordinator.client.sent_commands == []


def test_armed_grinder_adjust_resends_enter_mode_with_new_values():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_grind())
    coordinator.grind_size = 55
    coordinator.rpm = 110
    asyncio.run(coordinator.async_sync_armed_grinder_settings())

    assert coordinator.client.grinder.enter_mode_calls[-1] == {
        "size": 55, "speed": 110,
    }


def test_armed_grinder_adjust_is_a_noop_unless_grind_is_armed():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_sync_armed_grinder_settings())
    assert coordinator.client.grinder.enter_mode_calls == []

    asyncio.run(coordinator.async_arm_pour())
    asyncio.run(coordinator.async_sync_armed_grinder_settings())
    assert coordinator.client.grinder.enter_mode_calls == []


def test_armed_brewer_adjust_sends_temperature_and_pattern():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_arm_pour())
    coordinator.temperature = 88
    coordinator.pour_pattern = 0
    asyncio.run(coordinator.async_sync_armed_brewer_temperature())
    asyncio.run(coordinator.async_sync_armed_brewer_pattern())

    # First entries are the arm's own entry push (T7) of the setpoints as
    # they were at arm time; the slider adjustments follow.
    assert coordinator.client.brewer.set_temperature_calls == [93.0, 88.0]
    assert coordinator.client.brewer.set_pattern_calls == [2, 0]


def test_armed_brewer_adjust_is_a_noop_unless_pour_is_armed():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_sync_armed_brewer_temperature())
    asyncio.run(coordinator.async_sync_armed_brewer_pattern())

    asyncio.run(coordinator.async_arm_grind())
    asyncio.run(coordinator.async_sync_armed_brewer_temperature())
    asyncio.run(coordinator.async_sync_armed_brewer_pattern())

    assert coordinator.client.brewer.set_temperature_calls == []
    assert coordinator.client.brewer.set_pattern_calls == []
