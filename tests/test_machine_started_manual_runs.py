"""Manual pours/grinds the machine started itself, and HA-side pause of them.

Hardware 2026-10-14 (knob-started pour, then BLE commands): the machine
showed only 9001/9005 and pour page 0x03 → brewing 0x23 — no
RD_BREWER_BEGIN, so nothing set ``_active_operation`` and pause fell
through to the recipe pause 40518, which the machine ignores mid-pour
(water kept flowing). 8019 paused it (pour page 0x03 again, no 9010
notification), 8021 resumed it (0x23), 4507 stopped it.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.xbloom.ble.models import DeviceState
from custom_components.xbloom.coordinator.operations import OperationsMixin
from custom_components.xbloom.coordinator.state import StateMixin


class _Controller:
    def __init__(self, sent: list, pause: int, restart: int, stop: int) -> None:
        self._sent, self._codes = sent, (pause, restart, stop)

    async def pause(self):
        self._sent.append(self._codes[0])

    async def restart(self):
        self._sent.append(self._codes[1])

    async def stop(self):
        self._sent.append(self._codes[2])


class _FakeClient:
    is_connected = True

    def __init__(self) -> None:
        self.sent: list[int] = []
        self.brewer = _Controller(self.sent, 8019, 8021, 4507)
        self.grinder = _Controller(self.sent, 8018, 8020, 3505)
        self.status = SimpleNamespace(
            brewer=SimpleNamespace(is_running=False),
            grinder=SimpleNamespace(is_running=False),
        )

    async def _send_command(self, command, data=None, device_id=None):
        self.sent.append(int(command))
        return True

    async def stop_recipe(self, type_code=1, device_id=None):
        self.sent.append(40519)
        return True

    def is_calibrating_grinder(self):
        return False

    def is_sleeping(self):
        return False


class _Coordinator(StateMixin, OperationsMixin):
    def __init__(self) -> None:
        self.client = _FakeClient()
        self.data = {"state": "idle"}
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self._active_operation = None
        self._armed_operation = None
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._pod_prompt_active = False
        self._no_beans = False
        self._water_shortage = False

    async def _async_ensure_connected(self) -> bool:
        return True

    def async_update_listeners(self) -> None:
        pass

    def tick(self, s) -> str:
        """One coordinator update: reconcile, then derive sensor.state."""
        self._reconcile_armed_with_screen(s)
        self._reconcile_manual_operation(s)
        self.data = {"state": self._derive_state_string(s)}
        return self.data["state"]


def _status(screen=None, label=None, last_page=None, brewer=False, grinder=False):
    return SimpleNamespace(
        screen=screen,
        raw_state_label=label,
        last_page=last_page if last_page is not None else screen,
        state=DeviceState.IDLE,
        brewer=SimpleNamespace(is_running=brewer),
        grinder=SimpleNamespace(is_running=grinder),
    )


POUR_PAGE = _status(screen="pour")
POURING = _status(label="brewing", last_page="pour")


def test_knob_started_pour_is_tracked_as_manual():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    assert c.tick(POURING) == "brewing"
    assert c._active_operation == "manual_pour"


def test_pause_of_a_knob_started_pour_sends_brewer_pause_not_recipe_pause():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_pause_resume())
    assert c.client.sent == [8019]
    # The paused machine just shows its pour page again — still "paused".
    assert c.tick(POUR_PAGE) == "paused"
    assert c.tick(POUR_PAGE) == "paused"
    assert c._active_operation == "manual_pour"


def test_second_press_resumes_with_brewer_restart():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_pause_resume())
    c.tick(POUR_PAGE)
    asyncio.run(c.async_pause_resume())
    assert c.client.sent == [8019, 8021]
    assert c.tick(POURING) == "brewing"


def test_cancel_of_a_knob_started_pour_sends_brewer_stop():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_cancel())
    assert c.client.sent == [4507]
    assert c._manual_paused is False


def test_finished_pour_back_on_its_page_ends_the_run():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    assert c.tick(POUR_PAGE) == "standalone_pour"
    assert c._active_operation is None


def test_leaving_the_page_while_paused_ends_the_run():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_pause_resume())
    assert c.tick(_status(screen="home")) == "idle"
    assert c._active_operation is None
    assert c._manual_paused is False


def test_resume_from_the_machine_clears_the_paused_flag():
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_pause_resume())
    c.tick(POUR_PAGE)
    assert c.tick(POURING) == "brewing"
    assert c._manual_paused is False


def test_ha_armed_pour_started_from_the_knob_is_promoted():
    c = _Coordinator()
    c._armed_operation = "pour"
    c.tick(POUR_PAGE)
    c.tick(POURING)
    assert c._armed_operation is None
    assert c._active_operation == "manual_pour"


def test_brew_from_home_is_not_a_manual_pour():
    c = _Coordinator()
    c.tick(_status(screen="home"))
    c.tick(_status(label="brewing", last_page="home"))
    assert c._active_operation is None


def test_recipe_run_is_left_alone():
    c = _Coordinator()
    c._active_operation = "recipe"
    c.tick(POUR_PAGE)
    c.tick(POURING)
    assert c._active_operation == "recipe"


def test_ha_grind_on_its_page_before_it_starts_is_not_cleared():
    """An HA-started grind sits on the grind page while the burrs adjust —
    that must not read as 'finished' before the run was ever seen."""
    c = _Coordinator()
    c._active_operation = "manual_grind"
    c.tick(_status(screen="grind"))
    assert c._active_operation == "manual_grind"
    c.tick(_status(last_page="grind", grinder=True))
    c.tick(_status(screen="grind"))
    assert c._active_operation is None


def test_hardware_sequence_with_the_machines_reporting_lag():
    """Replays the 2026-10-14 live run: the machine kept reporting brewing
    for ~1 s after 8019 and stayed on the pour page for ~1 s after 8021.
    The first implementation read that lag as 'resumed' then 'finished',
    dropped the run, and the second press did nothing."""
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_pause_resume())          # 8019
    assert c.tick(POURING) == "brewing"           # lag: still reports brewing
    assert c.tick(POURING) == "brewing"
    assert c.tick(POUR_PAGE) == "paused"          # machine shows it paused
    assert c.tick(POUR_PAGE) == "paused"
    assert c._active_operation == "manual_pour"
    asyncio.run(c.async_pause_resume())          # 8021
    assert c.tick(POUR_PAGE) == "paused"          # lag: page until water flows
    assert c._active_operation == "manual_pour"
    assert c.tick(POURING) == "brewing"           # resumed
    assert c._manual_paused is False
    asyncio.run(c.async_cancel())                 # 4507
    assert c.client.sent == [8019, 8021, 4507]


def test_a_pause_the_machine_never_honoured_still_shows_brewing():
    """If 8019 were dropped the machine keeps brewing — the heartbeat's own
    label wins, so HA doesn't claim a pause that didn't happen."""
    c = _Coordinator()
    c.tick(POUR_PAGE)
    c.tick(POURING)
    asyncio.run(c.async_pause_resume())
    for _ in range(5):
        assert c.tick(POURING) == "brewing"
