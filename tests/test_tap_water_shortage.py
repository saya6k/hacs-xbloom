"""A "lack of water" report is only a shortage on the built-in tank.

Hardware-observed 2026-08-24 (native BLE session): the machine fires
`RD_ErrorLackOfWater` (40522, value 0) ~90 ms after every `4508`
water-source SET whenever the tank is empty — which on a machine plumbed
to a water line is its normal state. That surfaced as a `water_shortage`
state, a `problem` binary sensor and an error event, for a user who had
simply changed a setting.

The official app takes the same branch this does: HomeActivity's
`ErrorLackOfWaterBleModel` handler calls `dismissWaterScarcityAnimation()`
whenever `device.waterFeed != 0`, before it ever looks at the payload
value (jadx 2026-08-24).
"""
from __future__ import annotations

from custom_components.xbloom.coordinator.constants import (
    WATER_SOURCE_DIRECT,
    WATER_SOURCE_TANK,
)
from tests.test_finish_run_and_pause_gate import _Coordinator


def _make_coordinator(water_source: int) -> tuple[_Coordinator, list]:
    coordinator = _Coordinator()
    coordinator.water_source = water_source
    log: list = []
    coordinator._event_listeners.append(
        lambda cat, etype, attrs: log.append((cat, etype, attrs))
    )
    return coordinator, log


def test_tank_water_still_latches_a_shortage():
    coordinator, log = _make_coordinator(WATER_SOURCE_TANK)
    coordinator._dispatch_event("error", "water_shortage", {})
    assert coordinator._water_shortage is True
    assert ("error", "water_shortage", {}) in log


def test_direct_water_is_not_a_shortage():
    coordinator, log = _make_coordinator(WATER_SOURCE_DIRECT)
    coordinator._dispatch_event("error", "water_shortage", {})
    assert coordinator._water_shortage is False
    assert log == []


def test_switching_to_direct_water_unsticks_a_latched_shortage():
    """Clearing, not ignoring: a shortage latched while the machine was on
    tank water would otherwise survive the switch to a plumbed line, with
    no refill signal ever coming to clear it."""
    coordinator, log = _make_coordinator(WATER_SOURCE_TANK)
    coordinator._dispatch_event("error", "water_shortage", {})
    assert coordinator._water_shortage is True

    coordinator.water_source = WATER_SOURCE_DIRECT
    coordinator._dispatch_event("error", "water_shortage", {})

    assert coordinator._water_shortage is False
    # The synthesized "cleared" event still rides out, so anything
    # listening for the resolution sees it.
    assert [etype for _cat, etype, _attrs in log] == [
        "water_shortage",
        "water_shortage_cleared",
    ]


def test_other_errors_are_unaffected_on_direct_water():
    coordinator, log = _make_coordinator(WATER_SOURCE_DIRECT)
    coordinator._dispatch_event("error", "no_beans", {})
    assert coordinator._no_beans is True
    assert ("error", "no_beans", {}) in log
