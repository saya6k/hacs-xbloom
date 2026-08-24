"""Tests for ConnectionMixin._handle_unit_options_change's dirty-flag gating.

Hardware-reported 2026-07-18: the machine's own unit-settings screen
popped up first on every single reconnect. Root-caused via decompile
(MachineJ15Fragment, xbloom_coffee_release.apk): the official app only
ever sends the 8005/8010/4508 SET commands from an explicit button tap in
its own Settings screen — never automatically on connect. This
integration's async_connect() previously called _apply_unit_preferences()
unconditionally on every connect, which is indistinguishable to the
firmware from a user tapping those buttons.

Fix: track _unit_preferences_dirty, set only when a config_flow Settings
change was actually made, and only push at connect time (async_connect(),
see connection.py) if it's set.

Amended 2026-08-24: a Settings-step change now pushes immediately even
when the link is down — _async_push_unit_preferences() reconnects on
demand — because idle standby means "not connected right now" is the
normal state, not the exception, so waiting for the next connect left the
change unapplied indefinitely. The flag stays set until the push lands
and, while set, suppresses the machine-wins 8015 sync that would
otherwise revert the pending change.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator.connection import ConnectionMixin


class _FakeHass:
    def __init__(self) -> None:
        self.created_tasks: list = []

    def async_create_task(self, coro):
        self.created_tasks.append(coro)
        coro.close()  # record scheduling without actually running it
        return None


class _FakeClient:
    def __init__(self, is_connected: bool) -> None:
        self.is_connected = is_connected


class _Coordinator(ConnectionMixin):
    def __init__(self, *, client, hass) -> None:
        self.client = client
        self.hass = hass
        self._weight_unit = "g"
        self._temp_unit = "c"
        self.water_source = 0
        self._unit_preferences_dirty = False


def test_matching_options_is_a_noop():
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    coordinator._handle_unit_options_change(
        {"weight_unit": "g", "temp_unit": "c", "water_source": 0}
    )
    assert coordinator._unit_preferences_dirty is False
    assert coordinator.hass.created_tasks == []


def test_changed_while_disconnected_still_schedules_a_push():
    hass = _FakeHass()
    coordinator = _Coordinator(client=_FakeClient(False), hass=hass)
    coordinator._handle_unit_options_change(
        {"weight_unit": "oz", "temp_unit": "c", "water_source": 0}
    )
    assert coordinator._weight_unit == "oz"
    assert coordinator._unit_preferences_dirty is True
    assert len(hass.created_tasks) == 1


def test_changed_while_connected_schedules_a_push():
    hass = _FakeHass()
    coordinator = _Coordinator(client=_FakeClient(True), hass=hass)
    coordinator._handle_unit_options_change(
        {"weight_unit": "oz", "temp_unit": "c", "water_source": 1}
    )
    assert coordinator._weight_unit == "oz"
    assert coordinator.water_source == 1
    # Still dirty: only the push itself clears it, so a failed send is
    # retried by async_connect() instead of being lost.
    assert coordinator._unit_preferences_dirty is True
    assert len(hass.created_tasks) == 1


def test_push_applies_and_clears_dirty():
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    coordinator._unit_preferences_dirty = True
    applied: list[bool] = []
    coordinator._async_ensure_connected = _async_returning(True)
    coordinator._apply_unit_preferences = _async_recording(applied)

    asyncio.run(coordinator._async_push_unit_preferences())

    assert applied == [True]
    assert coordinator._unit_preferences_dirty is False


def test_push_keeps_dirty_when_the_machine_is_unreachable():
    coordinator = _Coordinator(client=_FakeClient(False), hass=_FakeHass())
    coordinator._unit_preferences_dirty = True
    applied: list[bool] = []
    coordinator._async_ensure_connected = _async_raising(
        ConnectionError("not connected")
    )
    coordinator._apply_unit_preferences = _async_recording(applied)

    asyncio.run(coordinator._async_push_unit_preferences())

    assert applied == []
    assert coordinator._unit_preferences_dirty is True


def test_machine_side_sync_is_ignored_while_a_push_is_pending():
    """The 8015 that arrives during the connect handshake carries the
    machine's pre-change values — adopting it would revert the change the
    user just made in the Settings step.
    """
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    coordinator.water_source = 1  # user picked "direct", not pushed yet
    coordinator._unit_preferences_dirty = True

    asyncio.run(
        coordinator._async_sync_units_from_machine(
            {"weight_unit": 0, "temp_unit": 0, "water_source": 0}
        )
    )

    assert coordinator.water_source == 1


def test_machine_side_sync_applies_when_nothing_is_pending():
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    persisted: list[bool] = []
    coordinator._persist_unit_options = lambda: persisted.append(True)
    coordinator.async_update_listeners = lambda: None

    asyncio.run(
        coordinator._async_sync_units_from_machine(
            {"weight_unit": 0, "temp_unit": 0, "water_source": 1}
        )
    )

    assert coordinator.water_source == 1
    assert persisted == [True]


def _async_returning(value):
    async def _call(*args, **kwargs):
        return value
    return _call


def _async_raising(exc):
    async def _call(*args, **kwargs):
        raise exc
    return _call


def _async_recording(sink):
    async def _call(*args, **kwargs):
        sink.append(True)
    return _call
