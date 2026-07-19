"""The coordinator synthesizes "_cleared" error events when a latched
error condition resolves.

Only water_shortage has a wire-level resolution signal (cmd 40522 with
value=1 → "water_refilled"); the other errors clear when the machine
demonstrably works again (brewing_started / pour_complete /
recipe_complete). Each transition must fire exactly one "<error>_cleared"
event on the error channel — and never fire when the error was not
latched in the first place.
"""
from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

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


def test_water_refilled_clears_water_shortage():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("error", "water_shortage", {})
    coordinator._dispatch_event("notification", "water_refilled", {})
    assert _events_of(log, "error") == ["water_shortage", "water_shortage_cleared"]


def test_successful_brew_clears_every_latched_error():
    coordinator, log = _make_coordinator()
    for error in (
        "water_shortage", "no_beans",
        "abnormal_dose_or_water", "abnormal_gear_position",
    ):
        coordinator._dispatch_event("error", error, {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    cleared = [e for e in _events_of(log, "error") if e.endswith("_cleared")]
    assert sorted(cleared) == [
        "abnormal_dose_or_water_cleared",
        "abnormal_gear_position_cleared",
        "no_beans_cleared",
        "water_shortage_cleared",
    ]


def test_no_cleared_event_without_a_latched_error():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("notification", "water_refilled", {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert not any(e.endswith("_cleared") for e in _events_of(log, "error"))


def test_cleared_fires_once_not_on_every_success_signal():
    coordinator, log = _make_coordinator()
    coordinator._dispatch_event("error", "no_beans", {})
    coordinator._dispatch_event("notification", "brewing_started", {})
    coordinator._dispatch_event("notification", "recipe_complete", {})
    assert _events_of(log, "error").count("no_beans_cleared") == 1
