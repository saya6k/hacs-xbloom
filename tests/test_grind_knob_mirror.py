"""Grind-page knob mirroring + live-sensor scoping (T6).

On the machine's grind page, knob turns push 8105 (size) / 8106 (RPM) and
page entry pushes a 9000 settings snapshot. While the page is open and the
grinder is not running, those must move `coordinator.grind_size`/`rpm` (the
number entities) immediately — and `sensor.live_grind_size` must do the
opposite: hold still unless a grind is actually running.
"""
from __future__ import annotations

import struct
from types import SimpleNamespace

import asyncio

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.coordinator.operations import OperationsMixin
from custom_components.xbloom.coordinator.state import StateMixin


# ── client side: knob pushes fire the internal settings event ────────────


class _FakeConnection:
    is_connected = False

    async def connect(self, address, timeout=20.0):
        return False

    async def disconnect(self):
        pass

    async def write_command(self, char_uuid, data, response=False):
        pass

    async def start_notify(self, char_uuid, callback):
        pass

    async def stop_notify(self, char_uuid):
        pass


def _ble_client():
    client = XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())
    events = []
    client.on_event(lambda cat, etype, attrs: events.append((cat, etype, attrs)))
    return client, events


def _frame(cmd: int, payload: bytes = b"") -> bytes:
    total_len = 12 + len(payload)
    return (
        bytes([0x58, 0x02, 0x07])
        + cmd.to_bytes(2, "little")
        + total_len.to_bytes(4, "little")
        + bytes([0xC1])
        + payload
        + b"\x00\x00"
    )


def _settings_events(events):
    return [(e, a) for c, e, a in events if c == "settings"]


def test_grind_size_push_fires_knob_event_with_adjusted_units():
    client, events = _ble_client()
    client._on_notification(None, bytearray(_frame(8105, struct.pack("<I", 65))))
    assert ("grinder_knob", {"size": 35}) in _settings_events(events)


def test_rpm_push_fires_knob_event():
    client, events = _ble_client()
    client._on_notification(None, bytearray(_frame(8106, struct.pack("<I", 100))))
    assert ("grinder_knob", {"rpm": 100}) in _settings_events(events)


def test_page_entry_snapshot_fires_knob_event_and_sets_size():
    """9000's snapshot is already in user units (T2: 9000 said 35 right
    after 8105's raw 65) — no -30 offset."""
    client, events = _ble_client()
    client._on_notification(None, bytearray(_frame(9000, struct.pack("<2I", 35, 60))))
    assert ("grinder_knob", {"size": 35, "rpm": 60}) in _settings_events(events)
    assert client.status.grinder.size == 35
    # The snapshot's RPM is a setpoint, not a live spin reading — the
    # live_grind_speed sensor's "0 = not spinning" contract must hold.
    assert client.status.grinder.speed == 0


# ── coordinator side: gated apply ────────────────────────────────────────


class _FakeHass:
    loop = None


class _StateCoordinator(StateMixin):
    def __init__(self, screen="grind", running=False) -> None:
        self.hass = _FakeHass()
        self.client = SimpleNamespace(
            status=SimpleNamespace(
                screen=screen,
                grinder=SimpleNamespace(is_running=running, size=0, speed=0),
            )
        )
        self.data = {"state": "unknown"}
        self.grind_size = 50
        self.rpm = 80
        self._live_grind_size = None
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self._active_operation = None
        self._armed_operation = None
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._pod_prompt_active = False
        self._water_shortage = False
        self._no_beans = False
        self._event_listeners: list = []


def test_knob_event_moves_the_setpoints_on_the_grind_page():
    coordinator = _StateCoordinator()
    coordinator._dispatch_event("settings", "grinder_knob", {"size": 43})
    coordinator._dispatch_event("settings", "grinder_knob", {"rpm": 100})
    assert coordinator.grind_size == 43
    assert coordinator.rpm == 100


def test_knob_event_ignored_off_the_grind_page():
    """A recipe's own 8105 push (screen is not the grind page) must not
    clobber the user's manual setpoints."""
    coordinator = _StateCoordinator(screen=None)
    coordinator._dispatch_event("settings", "grinder_knob", {"size": 43, "rpm": 100})
    assert coordinator.grind_size == 50
    assert coordinator.rpm == 80


def test_knob_event_ignored_while_grinding():
    coordinator = _StateCoordinator(running=True)
    coordinator._dispatch_event("settings", "grinder_knob", {"size": 43})
    assert coordinator.grind_size == 50


def test_out_of_range_values_ignored():
    coordinator = _StateCoordinator()
    coordinator._dispatch_event("settings", "grinder_knob", {"size": 0, "rpm": 0})
    assert coordinator.grind_size == 50
    assert coordinator.rpm == 80


def test_knob_event_stays_off_the_event_entities():
    coordinator = _StateCoordinator()
    seen = []
    coordinator._event_listeners.append(lambda c, e, a: seen.append(e))
    coordinator._dispatch_event("settings", "grinder_knob", {"size": 43})
    assert seen == []


# ── live_grind_size scoping ──────────────────────────────────────────────


def _grinder_status(running: bool, size: int):
    return SimpleNamespace(grinder=SimpleNamespace(is_running=running, size=size))


def test_live_grind_size_holds_still_unless_grinding():
    coordinator = _StateCoordinator()
    # Knob turn while idle on the page: live sensor stays unknown.
    assert coordinator._tracked_live_grind_size(_grinder_status(False, 43)) is None
    # A real grind runs: the in-use size shows.
    assert coordinator._tracked_live_grind_size(_grinder_status(True, 43)) == 43
    # Grind over, more knob turns: the sensor keeps the last in-grind value.
    assert coordinator._tracked_live_grind_size(_grinder_status(False, 65)) == 43


# ── live-adjust re-send gate (knob-opened page counts) ───────────────────


class _FakeGrinder:
    def __init__(self) -> None:
        self.enter_mode_calls: list[tuple] = []

    async def enter_mode(self, size, speed) -> bool:
        self.enter_mode_calls.append((size, speed))
        return True


class _OpsCoordinator(OperationsMixin):
    def __init__(self, screen=None, running=False) -> None:
        self.client = SimpleNamespace(
            grinder=_FakeGrinder(),
            status=SimpleNamespace(
                screen=screen,
                grinder=SimpleNamespace(is_running=running, size=0, speed=0),
            ),
        )
        self.grind_size = 40
        self.rpm = 90
        self._armed_operation = None

    async def _async_ensure_connected(self) -> bool:
        return True


def test_slider_change_live_adjusts_a_knob_opened_grind_page():
    coordinator = _OpsCoordinator(screen="grind")
    asyncio.run(coordinator.async_sync_armed_grinder_settings())
    assert coordinator.client.grinder.enter_mode_calls == [(40, 90)]


def test_slider_change_still_noop_when_page_closed_and_not_armed():
    coordinator = _OpsCoordinator(screen="home")
    asyncio.run(coordinator.async_sync_armed_grinder_settings())
    assert coordinator.client.grinder.enter_mode_calls == []


def test_slider_change_noop_while_grinding():
    coordinator = _OpsCoordinator(screen="grind", running=True)
    asyncio.run(coordinator.async_sync_armed_grinder_settings())
    assert coordinator.client.grinder.enter_mode_calls == []
