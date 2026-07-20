"""Telemetry-driven standalone-state derivation (T4 of the standalone-mode
overhaul).

The state sensor's standalone_grind/standalone_pour/standalone_scale values
derive from the machine's own screen telemetry (ble client `status.screen`,
T3), with the HA-side `_armed_operation` bookkeeping as a fallback only for
the no-code-emitted case. Telemetry wins when present: a machine reporting
its home screen shows idle even if HA still thinks an operation is armed.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.xbloom.ble.models import DeviceState
from custom_components.xbloom.coordinator.state import StateMixin


class _Coordinator(StateMixin):
    def __init__(self) -> None:
        self._armed_operation = None
        self._no_beans = False
        self._water_shortage = False
        self._calibrating = False
        self.client = SimpleNamespace(is_calibrating_grinder=lambda: self._calibrating)


def _status(
    screen=None,
    raw_state_label=None,
    state=DeviceState.IDLE,
    grinder_running=False,
    brewer_running=False,
):
    return SimpleNamespace(
        screen=screen,
        raw_state_label=raw_state_label,
        state=state,
        grinder=SimpleNamespace(is_running=grinder_running),
        brewer=SimpleNamespace(is_running=brewer_running),
    )


def test_screen_pages_map_to_standalone_states():
    coordinator = _Coordinator()
    assert coordinator._derive_state_string(_status(screen="grind")) == "standalone_grind"
    assert coordinator._derive_state_string(_status(screen="pour")) == "standalone_pour"
    assert coordinator._derive_state_string(_status(screen="scale")) == "standalone_scale"


def test_home_screen_is_idle():
    coordinator = _Coordinator()
    assert coordinator._derive_state_string(_status(screen="home")) == "idle"


def test_armed_fallback_only_when_no_screen_telemetry():
    """The pour page's code emission was once observed missing after our own
    8007 — armed bookkeeping fills that gap, but only when the machine has
    not reported a screen at all."""
    coordinator = _Coordinator()
    coordinator._armed_operation = "pour"
    assert coordinator._derive_state_string(_status(screen=None)) == "standalone_pour"
    coordinator._armed_operation = "grind"
    assert coordinator._derive_state_string(_status(screen=None)) == "standalone_grind"


def test_home_telemetry_beats_stale_armed_bookkeeping():
    """User backs out of an armed page on the machine: the reported home
    screen wins over the not-yet-cleared armed flag."""
    coordinator = _Coordinator()
    coordinator._armed_operation = "grind"
    assert coordinator._derive_state_string(_status(screen="home")) == "idle"


def test_running_operation_beats_the_page():
    """A grind started from the grind page must read grinding, not
    standalone_grind, even while the last screen report is stale."""
    coordinator = _Coordinator()
    status = _status(screen="grind", state=DeviceState.GRINDING, grinder_running=True)
    assert coordinator._derive_state_string(status) == "grinding"


def test_activity_label_beats_the_page():
    coordinator = _Coordinator()
    status = _status(screen="grind", raw_state_label="starting")
    assert coordinator._derive_state_string(status) == "starting"


def test_armed_recipe_is_unchanged_and_wins():
    coordinator = _Coordinator()
    coordinator._armed_operation = "recipe"
    assert coordinator._derive_state_string(_status(screen="pour")) == "armed_recipe"


def test_calibrating_grinder_rename():
    coordinator = _Coordinator()
    coordinator._calibrating = True
    assert coordinator._derive_state_string(_status()) == "calibrating_grinder"


def test_errors_beat_the_page():
    coordinator = _Coordinator()
    coordinator._water_shortage = True
    assert coordinator._derive_state_string(_status(screen="pour")) == "water_shortage"
    coordinator = _Coordinator()
    coordinator._no_beans = True
    assert coordinator._derive_state_string(_status(screen="grind")) == "no_beans"


def test_unknown_still_coerces_to_idle():
    coordinator = _Coordinator()
    assert coordinator._derive_state_string(_status(state=DeviceState.UNKNOWN)) == "idle"
