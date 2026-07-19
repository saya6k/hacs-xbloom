"""Armed→active transitions on machine-side starts (T5).

When the user arms an operation in HA but presses the machine's own knob to
start it, the bookkeeping must transition exactly as the HA confirm press
would: `_armed_operation` clears and `_active_operation` is set to the
matching family — otherwise pause/cancel target the wrong command family
(see project memory xbloom-manual-operation-command-targeting) and the
state sensor sticks on the armed value.

Also: a stale grind/pour arm clears once the machine reports its home
screen (the user backed out with the knob) — cancel must not later send a
quit command for a screen that is no longer open.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.xbloom.coordinator.state import StateMixin


class _FakeHass:
    loop = None  # _dispatch_event guards on truthiness


class _Coordinator(StateMixin):
    def __init__(self) -> None:
        self.hass = _FakeHass()
        self.data = {"state": "unknown"}
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


def test_machine_started_grind_transitions_armed_to_active():
    coordinator = _Coordinator()
    coordinator._armed_operation = "grind"
    coordinator._dispatch_event("notification", "grinding_started", {})
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "manual_grind"


def test_machine_started_pour_transitions_armed_to_active():
    coordinator = _Coordinator()
    coordinator._armed_operation = "pour"
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "manual_pour"


def test_machine_confirmed_recipe_transitions_on_grind_start():
    coordinator = _Coordinator()
    coordinator._armed_operation = "recipe"
    coordinator._armed_recipe_is_tea = True
    coordinator._armed_recipe_tea_payload = b"\x01"
    coordinator._dispatch_event("notification", "grinding_started", {})
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "recipe"
    assert coordinator._armed_recipe_is_tea is False
    assert coordinator._armed_recipe_tea_payload is None


def test_machine_confirmed_recipe_transitions_on_brew_start():
    """A no-grind (bypass) recipe's first start signal is brewing_started."""
    coordinator = _Coordinator()
    coordinator._armed_operation = "recipe"
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "recipe"


def test_easy_slot_start_is_a_recipe():
    """A brew started from the machine's Easy Mode dial (8111) is a recipe
    execution — cancel must take the 40519 branch, pause the 40518 one."""
    coordinator = _Coordinator()
    coordinator._dispatch_event("notification", "easy_slot_started", {"slot": "A"})
    assert coordinator._active_operation == "recipe"


def test_unarmed_grind_start_does_not_guess():
    """grinding_started with nothing armed and nothing active (e.g. an NFC
    pod brew before any tracked signal) must not claim manual_grind — the
    recipe cancel fallback (bare 40519) is the safe default."""
    coordinator = _Coordinator()
    coordinator._dispatch_event("notification", "grinding_started", {})
    assert coordinator._active_operation is None


def test_recipe_grind_stage_does_not_downgrade_active():
    coordinator = _Coordinator()
    coordinator._active_operation = "recipe"
    coordinator._dispatch_event("notification", "grinding_started", {})
    assert coordinator._active_operation == "recipe"


def test_mismatched_start_signal_leaves_armed_alone():
    """brewing_started while a grind is armed is not a plausible confirm of
    that arm — leave the bookkeeping for the screen reconcile/cancel."""
    coordinator = _Coordinator()
    coordinator._armed_operation = "grind"
    coordinator._dispatch_event("notification", "brewing_started", {})
    assert coordinator._armed_operation == "grind"
    assert coordinator._active_operation is None


# ── page-exit reconcile ──────────────────────────────────────────────────


def _status(screen):
    return SimpleNamespace(screen=screen)


def test_home_screen_clears_stale_grind_arm():
    coordinator = _Coordinator()
    coordinator._armed_operation = "grind"
    coordinator._reconcile_armed_with_screen(_status("home"))
    assert coordinator._armed_operation is None


def test_home_screen_clears_stale_pour_arm():
    coordinator = _Coordinator()
    coordinator._armed_operation = "pour"
    coordinator._reconcile_armed_with_screen(_status("home"))
    assert coordinator._armed_operation is None


def test_no_screen_report_keeps_the_arm():
    coordinator = _Coordinator()
    coordinator._armed_operation = "pour"
    coordinator._reconcile_armed_with_screen(_status(None))
    assert coordinator._armed_operation == "pour"


def test_matching_page_keeps_the_arm():
    coordinator = _Coordinator()
    coordinator._armed_operation = "grind"
    coordinator._reconcile_armed_with_screen(_status("grind"))
    assert coordinator._armed_operation == "grind"


def test_armed_recipe_is_not_screen_reconciled():
    """The recipe prompt's machine-side dismissal is unverified on hardware,
    and the arm send chain (8102→8104→8001) has a longer home-screen window
    than the instant 8006/8007 page opens — leave recipe arms to cancel."""
    coordinator = _Coordinator()
    coordinator._armed_operation = "recipe"
    coordinator._reconcile_armed_with_screen(_status("home"))
    assert coordinator._armed_operation == "recipe"
