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
change couldn't reach the machine while disconnected, and only push at
connect time (async_connect(), see connection.py) if it's set.
"""
from __future__ import annotations

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


def test_changed_while_disconnected_marks_dirty_without_pushing():
    coordinator = _Coordinator(client=_FakeClient(False), hass=_FakeHass())
    coordinator._handle_unit_options_change(
        {"weight_unit": "oz", "temp_unit": "c", "water_source": 0}
    )
    assert coordinator._weight_unit == "oz"
    assert coordinator._unit_preferences_dirty is True
    assert coordinator.hass.created_tasks == []


def test_changed_while_connected_pushes_and_clears_dirty():
    hass = _FakeHass()
    coordinator = _Coordinator(client=_FakeClient(True), hass=hass)
    coordinator._unit_preferences_dirty = True  # simulate a prior offline change
    coordinator._handle_unit_options_change(
        {"weight_unit": "oz", "temp_unit": "c", "water_source": 0}
    )
    assert coordinator._weight_unit == "oz"
    assert coordinator._unit_preferences_dirty is False
    assert len(hass.created_tasks) == 1
