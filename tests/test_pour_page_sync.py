"""Pour-page entry push + knob mirroring (T7).

HA→machine: arming the pour page (8007) is followed, after a settle delay,
by a best-effort push of HA's temperature (4510) and pattern (8016) — the
machine no longer sits on its own defaults ignoring the entities.

Machine→HA: temperature/pattern knob turns (8108/8107) and the knob-entry
settings snapshot (9001) mirror onto the entities immediately, gated on
the pour page being open with nothing running. The 9001 snapshot is
additionally suppressed while an HA arm is in flight — otherwise it would
overwrite the very values the entry push is about to apply.

Also pins the 8108 scale fix: knob pushes carry literal °C (hardware
2026-07-20: payload 56 → 53 as the knob was turned down), not the ×10
encoding — the old unconditional /10 showed 5.6 °C for a 56 °C knob.
"""
from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import pytest

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.coordinator import operations
from custom_components.xbloom.coordinator.operations import OperationsMixin
from custom_components.xbloom.coordinator.state import StateMixin


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    monkeypatch.setattr(operations, "_POUR_ARM_SETTLE_S", 0)
    monkeypatch.setattr(operations, "_POUR_ARM_PUSH_GAP_S", 0)


# ── client side ──────────────────────────────────────────────────────────


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


def test_temperature_knob_push_is_literal_celsius():
    client, events = _ble_client()
    client._on_notification(None, bytearray(_frame(8108, struct.pack("<I", 56))))
    assert client.status.brewer.temperature == 56.0
    assert ("brewer_knob", {"temperature": 56.0}) in _settings_events(events)


def test_temperature_x10_encoding_still_decodes():
    """Values above the machine's physical maximum can only be the ×10
    encoding (the 4510-echo family)."""
    client, events = _ble_client()
    client._on_notification(None, bytearray(_frame(8108, struct.pack("<I", 880))))
    assert client.status.brewer.temperature == 88.0


def test_pattern_knob_push_fires_event():
    client, events = _ble_client()
    client._on_notification(None, bytearray(_frame(8107, struct.pack("<I", 1))))
    assert ("brewer_knob", {"pattern": 1}) in _settings_events(events)


def test_pour_page_entry_snapshot_fires_event():
    client, events = _ble_client()
    client._on_notification(
        None, bytearray(_frame(9001, struct.pack("<4I", 250, 56, 0, 56)))
    )
    assert (
        "brewer_page_entry",
        {"volume": 250, "temperature": 56, "pattern": 0},
    ) in _settings_events(events)


# ── coordinator side ─────────────────────────────────────────────────────


class _FakeHass:
    loop = None


class _StateCoordinator(StateMixin):
    def __init__(self, screen="pour", running=False, armed=None) -> None:
        self.hass = _FakeHass()
        self.client = SimpleNamespace(
            status=SimpleNamespace(
                screen=screen,
                brewer=SimpleNamespace(is_running=running),
                grinder=SimpleNamespace(is_running=False, size=0, speed=0),
            )
        )
        self.data = {"state": "unknown"}
        self.temperature = 93
        self.pour_pattern = 2
        self.volume = 200
        self.grind_size = 50
        self.rpm = 80
        self._live_grind_size = None
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self._active_operation = None
        self._armed_operation = armed
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._pod_prompt_active = False
        self._water_shortage = False
        self._no_beans = False
        self._event_listeners: list = []


def test_knob_turns_move_the_entities_on_the_pour_page():
    coordinator = _StateCoordinator()
    coordinator._dispatch_event("settings", "brewer_knob", {"temperature": 56.0})
    coordinator._dispatch_event("settings", "brewer_knob", {"pattern": 1})
    assert coordinator.temperature == 56
    assert coordinator.pour_pattern == 1


def test_knob_turns_mirror_even_while_armed():
    """An HA-armed pour page's knobs are live — turning them must reach
    the entities (bidirectional sync), unlike the entry snapshot."""
    coordinator = _StateCoordinator(armed="pour")
    coordinator._dispatch_event("settings", "brewer_knob", {"temperature": 88.0})
    assert coordinator.temperature == 88


def test_knob_turns_ignored_off_the_pour_page_or_mid_brew():
    coordinator = _StateCoordinator(screen=None)
    coordinator._dispatch_event("settings", "brewer_knob", {"temperature": 56.0})
    assert coordinator.temperature == 93
    coordinator = _StateCoordinator(running=True)
    coordinator._dispatch_event("settings", "brewer_knob", {"temperature": 56.0})
    assert coordinator.temperature == 93


def test_entry_snapshot_seeds_the_entities_on_knob_entry():
    coordinator = _StateCoordinator()
    coordinator._dispatch_event(
        "settings", "brewer_page_entry", {"volume": 250, "temperature": 56, "pattern": 1}
    )
    assert coordinator.volume == 250
    assert coordinator.temperature == 56
    assert coordinator.pour_pattern == 1


def test_entry_snapshot_suppressed_while_ha_arm_in_flight():
    """8007-armed entry: the machine's snapshot must not overwrite the HA
    setpoints the entry push is about to apply."""
    coordinator = _StateCoordinator(armed="pour")
    coordinator._dispatch_event(
        "settings", "brewer_page_entry", {"volume": 250, "temperature": 56, "pattern": 1}
    )
    assert coordinator.volume == 200
    assert coordinator.temperature == 93
    assert coordinator.pour_pattern == 2


def test_brewer_settings_events_stay_off_the_event_entities():
    coordinator = _StateCoordinator()
    seen = []
    coordinator._event_listeners.append(lambda c, e, a: seen.append(e))
    coordinator._dispatch_event("settings", "brewer_knob", {"temperature": 56.0})
    coordinator._dispatch_event("settings", "brewer_page_entry", {"volume": 250})
    assert seen == []


# ── operations side: entry push + widened live-adjust gates ──────────────


class _FakeBrewer:
    def __init__(self, fail_push=False) -> None:
        self.fail_push = fail_push
        self.enter_mode_calls = 0
        self.set_temperature_calls: list[float] = []
        self.set_pattern_calls: list[int] = []

    async def enter_mode(self) -> bool:
        self.enter_mode_calls += 1
        return True

    async def set_temperature(self, temperature: float) -> bool:
        if self.fail_push:
            raise ConnectionError("boom")
        self.set_temperature_calls.append(temperature)
        return True

    async def set_pattern(self, pattern: int) -> bool:
        self.set_pattern_calls.append(pattern)
        return True


class _OpsCoordinator(OperationsMixin):
    def __init__(self, screen=None, running=False, fail_push=False) -> None:
        self.client = SimpleNamespace(
            brewer=_FakeBrewer(fail_push=fail_push),
            status=SimpleNamespace(
                screen=screen,
                brewer=SimpleNamespace(is_running=running),
                grinder=SimpleNamespace(is_running=False),
            ),
        )
        self.temperature = 88
        self.pour_pattern = 1
        self._armed_operation = None

    async def _async_ensure_connected(self) -> bool:
        return True

    async def _async_retry_while_sleeping(self, action):
        return await action()


def test_arm_pour_pushes_ha_setpoints_after_entering():
    coordinator = _OpsCoordinator()
    asyncio.run(coordinator.async_arm_pour())
    assert coordinator.client.brewer.enter_mode_calls == 1
    assert coordinator.client.brewer.set_temperature_calls == [88.0]
    assert coordinator.client.brewer.set_pattern_calls == [1]
    assert coordinator._armed_operation == "pour"


def test_entry_push_failure_is_best_effort():
    coordinator = _OpsCoordinator(fail_push=True)
    asyncio.run(coordinator.async_arm_pour())
    assert coordinator._armed_operation == "pour"


def test_slider_live_adjusts_a_knob_opened_pour_page():
    coordinator = _OpsCoordinator(screen="pour")
    asyncio.run(coordinator.async_sync_armed_brewer_temperature())
    asyncio.run(coordinator.async_sync_armed_brewer_pattern())
    assert coordinator.client.brewer.set_temperature_calls == [88.0]
    assert coordinator.client.brewer.set_pattern_calls == [1]


def test_slider_sync_still_noop_when_page_closed_and_not_armed():
    coordinator = _OpsCoordinator(screen="home")
    asyncio.run(coordinator.async_sync_armed_brewer_temperature())
    asyncio.run(coordinator.async_sync_armed_brewer_pattern())
    assert coordinator.client.brewer.set_temperature_calls == []
    assert coordinator.client.brewer.set_pattern_calls == []


def test_slider_sync_noop_mid_pour():
    coordinator = _OpsCoordinator(screen="pour", running=True)
    asyncio.run(coordinator.async_sync_armed_brewer_temperature())
    assert coordinator.client.brewer.set_temperature_calls == []
