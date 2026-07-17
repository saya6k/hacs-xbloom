"""Tests for XBloomCoordinator._handle_unit_options_change's dirty-flag gating.

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
connect time (async_connect(), see coordinator.py) if it's set.

Calls the real unbound method off XBloomCoordinator with a minimal
duck-typed stand-in for `self` — legacy/1.4.x predates the coordinator/
package split (main branch), so there's no separable ConnectionMixin to
import here (same pattern as tests/test_wake_retry.py).
"""
from __future__ import annotations

from custom_components.xbloom.coordinator import XBloomCoordinator

_handle_unit_options_change = XBloomCoordinator._handle_unit_options_change


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


class _FakeSelf:
    def __init__(self, *, client, hass) -> None:
        self.client = client
        self.hass = hass
        self._weight_unit = "g"
        self._temp_unit = "c"
        self.water_source = 0
        self._unit_preferences_dirty = False

    async def _apply_unit_preferences(self, client=None) -> None:
        """Stub — the real method's own send behavior isn't under test here."""


def test_matching_options_is_a_noop():
    fake_self = _FakeSelf(client=_FakeClient(True), hass=_FakeHass())
    _handle_unit_options_change(
        fake_self, {"weight_unit": "g", "temp_unit": "c", "water_source": 0}
    )
    assert fake_self._unit_preferences_dirty is False
    assert fake_self.hass.created_tasks == []


def test_changed_while_disconnected_marks_dirty_without_pushing():
    fake_self = _FakeSelf(client=_FakeClient(False), hass=_FakeHass())
    _handle_unit_options_change(
        fake_self, {"weight_unit": "oz", "temp_unit": "c", "water_source": 0}
    )
    assert fake_self._weight_unit == "oz"
    assert fake_self._unit_preferences_dirty is True
    assert fake_self.hass.created_tasks == []


def test_changed_while_connected_pushes_and_clears_dirty():
    hass = _FakeHass()
    fake_self = _FakeSelf(client=_FakeClient(True), hass=hass)
    fake_self._unit_preferences_dirty = True  # simulate a prior offline change
    _handle_unit_options_change(
        fake_self, {"weight_unit": "oz", "temp_unit": "c", "water_source": 0}
    )
    assert fake_self._weight_unit == "oz"
    assert fake_self._unit_preferences_dirty is False
    assert len(hass.created_tasks) == 1
