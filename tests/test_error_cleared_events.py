"""The coordinator synthesizes "water_shortage_cleared" when the latched
water-shortage condition resolves — the one error with a wire-level
resolution signal (cmd 40522 with value=1 → "water_refilled"); a
successful brew also clears the latch. Deliberately the ONLY "_cleared"
event type: the other errors are payload-less one-shot alarms with no
resolution signal, so a derived "cleared" would be a guess.
"""
from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.xbloom.event import ERROR_EVENT_TYPES

from tests.test_finish_run_and_pause_gate import _Coordinator


def _events_of(listener_log: list, category: str) -> list[str]:
    return [etype for cat, etype, _attrs in listener_log if cat == category]


def _make_coordinator() -> tuple[_Coordinator, list]:
    coordinator = _Coordinator()
    log: list = []
    coordinator._event_listeners.append(
        lambda cat, etype, attrs: log.append((cat, etype, attrs))
    )
    return coordinator, log


def test_water_refilled_fires_water_shortage_cleared():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("error", "water_shortage", {})
    coordinator._dispatch_event("notification", "water_refilled", {})
    assert _events_of(log, "error") == ["water_shortage", "water_shortage_cleared"]


def test_successful_brew_also_clears_the_latch():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("error", "water_shortage", {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert "water_shortage_cleared" in _events_of(log, "error")


def test_no_cleared_event_without_a_latched_shortage():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("notification", "water_refilled", {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert not any(e.endswith("_cleared") for e in _events_of(log, "error"))


def test_cleared_fires_once_not_on_every_success_signal():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("error", "water_shortage", {})
    coordinator._dispatch_event("notification", "water_refilled", {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert _events_of(log, "error").count("water_shortage_cleared") == 1


def test_other_errors_have_no_cleared_counterpart():
    # Wire-signal-backed only: water_shortage_cleared must stay the sole
    # "_cleared" type (user decision 2026-07-19).
    cleared = [t for t in ERROR_EVENT_TYPES if t.endswith("_cleared")]
    assert cleared == ["water_shortage_cleared"]

    coordinator, log = _make_coordinator()
    for error in ("no_beans", "abnormal_dose_or_water", "abnormal_gear_position"):
        coordinator._dispatch_event("error", error, {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert not any(e.endswith("_cleared") for e in _events_of(log, "error"))
