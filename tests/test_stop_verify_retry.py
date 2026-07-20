"""Outcome-based stop retry for manual grind/pour cancels.

Hardware 2026-07-20 (Checkpoint 2 smoke): a 3505 sent between a knob
start's begin report (9003) and its run-begin (40506) is silently dropped
— the grinder kept running through a cancel. The same command 1s later
stops it instantly. Cancel therefore watches is_running after the stop
and re-sends once if it never clears.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.xbloom.coordinator import operations
from custom_components.xbloom.coordinator.operations import OperationsMixin


@pytest.fixture(autouse=True)
def _fast_verify(monkeypatch):
    monkeypatch.setattr(operations, "_STOP_VERIFY_ATTEMPTS", 3)
    monkeypatch.setattr(operations, "_STOP_VERIFY_INTERVAL_S", 0)


class _Component:
    def __init__(self, status_side, stops_on: int) -> None:
        self._status_side = status_side
        self._stops_on = stops_on
        self.stop_calls = 0

    async def stop(self) -> bool:
        self.stop_calls += 1
        if self.stop_calls >= self._stops_on:
            self._status_side.is_running = False
        return True


class _Coordinator(OperationsMixin):
    def __init__(self, stops_on: int = 1, running: bool = True) -> None:
        grinder_status = SimpleNamespace(is_running=running)
        brewer_status = SimpleNamespace(is_running=False)
        self.client = SimpleNamespace(
            grinder=_Component(grinder_status, stops_on),
            brewer=_Component(brewer_status, stops_on),
            status=SimpleNamespace(grinder=grinder_status, brewer=brewer_status),
        )
        self._active_operation = "manual_grind"
        self._armed_operation = None
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._pod_prompt_active = False
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None

    async def _async_ensure_connected(self) -> bool:
        return True

    def async_update_listeners(self) -> None:
        pass


def test_stop_that_lands_is_not_resent():
    coordinator = _Coordinator(stops_on=1)
    asyncio.run(coordinator.async_cancel())
    assert coordinator.client.grinder.stop_calls == 1


def test_dropped_stop_is_resent_once():
    """First 3505 falls in the start-transition window (is_running never
    clears) — exactly one re-send follows."""
    coordinator = _Coordinator(stops_on=2)
    asyncio.run(coordinator.async_cancel())
    assert coordinator.client.grinder.stop_calls == 2


def test_verify_is_a_noop_without_status():
    coordinator = _Coordinator()
    coordinator.client = SimpleNamespace(
        grinder=coordinator.client.grinder, brewer=coordinator.client.brewer
    )
    asyncio.run(coordinator._async_verify_component_stop("grinder"))
    assert coordinator.client.grinder.stop_calls == 0
