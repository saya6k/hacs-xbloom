"""Phase 3 teardown behaviors: _finish_run on machine errors, the
state-gated pause fallback, and the slimmed-down recipe cancel.

The run flags (_executing_recipe/_active_operation/…) gate the cancel
branch, the pause target, and idle standby — an errored-out brew that
leaves them set misroutes all three. The official app tears its run state
down on machine alarms (ErrorBle1/ErrorIdling → BleEnjoyEvent); a mid-brew
water_shortage provably does NOT end a brew (hardware-observed 2026-07-19)
and is excluded, matching the app's exclusion of ErrorLackOfWater.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.xbloom.coordinator.operations import OperationsMixin
from custom_components.xbloom.coordinator.state import StateMixin


class _FakeHass:
    def __init__(self) -> None:
        self.loop = None  # _dispatch_event guards on truthiness


class _Coordinator(StateMixin, OperationsMixin):
    def __init__(self) -> None:
        self.hass = _FakeHass()
        self.client = _FakeClient()
        self.data = {"state": "unknown"}
        self._executing_recipe = True
        self._active_recipe_pours = ["pour"]
        self.current_pour_index = 0
        self._active_operation = "recipe"
        self._armed_operation = None
        self._pod_prompt_active = False
        self._water_shortage = False
        self._no_beans = False
        self._auto_switched_to_pro = False
        self._event_listeners: list = []

    async def _async_ensure_connected(self) -> bool:
        return True

    def async_update_listeners(self) -> None:
        pass

    async def _restore_persisted_mode(self, _reason: str) -> None:
        pass


class _FakeClient:
    is_connected = True

    def __init__(self) -> None:
        self.sent: list[int] = []

    async def _send_command(self, command, data=None, device_id=None):
        self.sent.append(int(command))
        return True

    async def stop_recipe(self, type_code=1, device_id=None):
        self.sent.append(40519)
        return True

    class grinder:
        @staticmethod
        async def stop():
            raise AssertionError("component stop must not be sent for a recipe cancel")

    class brewer:
        @staticmethod
        async def stop():
            raise AssertionError("component stop must not be sent for a recipe cancel")


def _run_states(coordinator: _Coordinator) -> tuple:
    return (
        coordinator._executing_recipe,
        coordinator._active_recipe_pours,
        coordinator.current_pour_index,
        coordinator._active_operation,
    )


def test_machine_alarm_tears_the_run_down():
    for error in ("no_beans", "abnormal_dose_or_water", "abnormal_gear_position"):
        coordinator = _Coordinator()
        coordinator._dispatch_event("error", error, {})
        assert _run_states(coordinator) == (False, None, None, None), error


def test_water_shortage_mid_brew_does_not_end_the_run():
    coordinator = _Coordinator()
    coordinator._dispatch_event("error", "water_shortage", {})
    assert coordinator._executing_recipe is True
    assert coordinator._active_operation == "recipe"


def test_recipe_cancel_sends_bare_40519_only():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_cancel())
    assert coordinator.client.sent == [40519]


def test_pause_is_a_no_op_when_nothing_is_pausable():
    for state in ("unknown", "idle", "ready", "awaiting_confirm"):
        coordinator = _Coordinator()
        coordinator._active_operation = None
        coordinator.data = {"state": state}
        asyncio.run(coordinator.async_pause_resume())
        assert coordinator.client.sent == [], state


def test_pause_still_pauses_a_running_recipe():
    coordinator = _Coordinator()
    coordinator._active_operation = None
    coordinator.data = {"state": "brewing"}
    asyncio.run(coordinator.async_pause_resume())
    assert coordinator.client.sent == [40518]


def test_resume_still_resumes_a_paused_recipe():
    coordinator = _Coordinator()
    coordinator._active_operation = None
    coordinator.data = {"state": "paused"}
    asyncio.run(coordinator.async_pause_resume())
    assert coordinator.client.sent == [40524]
