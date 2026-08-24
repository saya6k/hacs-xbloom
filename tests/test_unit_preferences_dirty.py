"""Tests for ConnectionMixin's pending-unit-push gating.

Hardware-reported 2026-07-18: the machine's own unit-settings screen
popped up first on every single reconnect. Root-caused via decompile
(MachineJ15Fragment, xbloom_coffee_release.apk): the official app only
ever sends the 8005/8010/4508 SET commands from an explicit button tap in
its own Settings screen — never automatically on connect. This
integration's async_connect() previously called _apply_unit_preferences()
unconditionally on every connect, which is indistinguishable to the
firmware from a user tapping those buttons.

Fix: track _pending_unit_pushes, filled only when a config_flow Settings
change was actually made, and only push at connect time (async_connect(),
see connection.py) if it's non-empty.

Amended 2026-08-24: a Settings-step change now pushes immediately even
when the link is down — _async_push_unit_preferences() reconnects on
demand — because idle standby means "not connected right now" is the
normal state, not the exception, so waiting for the next connect left the
change unapplied indefinitely. A key stays pending until its own send
lands and, while pending, suppresses the machine-wins 8015 sync that
would otherwise revert that setting.

Amended again the same day, hardware-reported: the flag became a set of
option keys, because pushing all three commands for a single changed
setting dropped the machine into its own settings wizard (starting at the
weight-unit page) and made the user re-enter everything.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom.ble.client import AckTimeout
from custom_components.xbloom.coordinator import connection as connection_module
from custom_components.xbloom.coordinator.connection import ConnectionMixin

# Captured before the autouse fixture below patches it out.
_REAL_SETTLE_S = connection_module._SETTINGS_PAGE_SETTLE_S


@pytest.fixture(autouse=True)
def _no_settle_delay(monkeypatch):
    """Skip the real back-to-home settle wait (see the test at the bottom
    for why it exists) so the suite doesn't sleep through it."""
    monkeypatch.setattr(connection_module, "_SETTINGS_PAGE_SETTLE_S", 0)


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
        self._pending_unit_pushes: set[str] = set()
        self._unit_push_lock = asyncio.Lock()


def test_matching_options_is_a_noop():
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    coordinator._handle_unit_options_change(
        {"weight_unit": "g", "temp_unit": "c", "water_source": 0}
    )
    assert coordinator._pending_unit_pushes == set()
    assert coordinator.hass.created_tasks == []


def test_changed_while_disconnected_still_schedules_a_push():
    hass = _FakeHass()
    coordinator = _Coordinator(client=_FakeClient(False), hass=hass)
    coordinator._handle_unit_options_change(
        {"weight_unit": "oz", "temp_unit": "c", "water_source": 0}
    )
    assert coordinator._weight_unit == "oz"
    assert coordinator._pending_unit_pushes == {"weight_unit"}
    assert len(hass.created_tasks) == 1


def test_changed_while_connected_schedules_a_push():
    hass = _FakeHass()
    coordinator = _Coordinator(client=_FakeClient(True), hass=hass)
    coordinator._handle_unit_options_change(
        {"weight_unit": "oz", "temp_unit": "c", "water_source": 1}
    )
    assert coordinator._weight_unit == "oz"
    assert coordinator.water_source == 1
    # Still pending: only the send itself clears a key, so a failed one is
    # retried by async_connect() instead of being lost. The unchanged
    # temp unit is not queued — its command would re-open the machine's
    # own settings screen for nothing.
    assert coordinator._pending_unit_pushes == {"weight_unit", "water_source"}
    assert len(hass.created_tasks) == 1


def test_push_applies_the_pending_keys():
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    coordinator._pending_unit_pushes = {"water_source"}
    applied: list[bool] = []
    coordinator._async_ensure_connected = _async_returning(True)
    coordinator._apply_unit_preferences = _async_recording(applied)

    asyncio.run(coordinator._async_push_unit_preferences())

    assert applied == [True]


def test_push_keeps_the_keys_pending_when_the_machine_is_unreachable():
    coordinator = _Coordinator(client=_FakeClient(False), hass=_FakeHass())
    coordinator._pending_unit_pushes = {"water_source"}
    applied: list[bool] = []
    coordinator._async_ensure_connected = _async_raising(
        ConnectionError("not connected")
    )
    coordinator._apply_unit_preferences = _async_recording(applied)

    asyncio.run(coordinator._async_push_unit_preferences())

    assert applied == []
    assert coordinator._pending_unit_pushes == {"water_source"}


def test_machine_side_sync_is_ignored_while_a_push_is_pending():
    """The 8015 that arrives during the connect handshake carries the
    machine's pre-change values — adopting it would revert the change the
    user just made in the Settings step.
    """
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    coordinator.water_source = 1  # user picked "direct", not pushed yet
    coordinator._pending_unit_pushes = {"water_source"}

    asyncio.run(
        coordinator._async_sync_units_from_machine(
            {"weight_unit": 0, "temp_unit": 0, "water_source": 0}
        )
    )

    assert coordinator.water_source == 1


def test_machine_side_sync_applies_when_nothing_is_pending():
    coordinator = _Coordinator(client=_FakeClient(True), hass=_FakeHass())
    persisted: list[bool] = []
    coordinator._persist_unit_options = lambda: persisted.append(True)
    coordinator.async_update_listeners = lambda: None

    asyncio.run(
        coordinator._async_sync_units_from_machine(
            {"weight_unit": 0, "temp_unit": 0, "water_source": 1}
        )
    )

    assert coordinator.water_source == 1
    assert persisted == [True]


class _RecordingClient:
    """Records ACK-gated sends; optionally times out on given commands."""

    is_connected = True

    def __init__(self, timeout_commands: tuple[int, ...] = ()) -> None:
        self.sent: list[tuple[int, object]] = []
        self._timeout_commands = timeout_commands

    async def send_and_wait(self, command, data=None, *, raw=None, **kwargs):
        self.sent.append((command, raw if raw is not None else data))
        if command in self._timeout_commands:
            raise AckTimeout(f"No ACK for {command}")
        return b""


def test_only_the_changed_setting_is_sent():
    """Sending all three commands for one changed setting is what put the
    machine into its own settings wizard (hardware-reported 2026-08-24)."""
    client = _RecordingClient()
    coordinator = _Coordinator(client=client, hass=_FakeHass())
    coordinator.water_source = 1
    coordinator._pending_unit_pushes = {"water_source"}

    asyncio.run(coordinator._apply_unit_preferences())

    # 8022 (back to home) follows, or the machine sits on its TAP/TANK
    # page waiting for a manual confirm — see _async_return_machine_home.
    assert client.sent == [(4508, [1]), (8022, None)]
    assert coordinator._pending_unit_pushes == set()


def test_each_setting_maps_to_its_own_command():
    client = _RecordingClient()
    coordinator = _Coordinator(client=client, hass=_FakeHass())
    coordinator._weight_unit = "oz"
    coordinator._temp_unit = "f"
    coordinator._pending_unit_pushes = {"weight_unit", "temp_unit", "water_source"}

    asyncio.run(coordinator._apply_unit_preferences())

    assert client.sent == [
        (8005, b"\x01"), (8010, b"\x01"), (4508, [0]), (8022, None),
    ]


def test_a_timed_out_send_is_retried_once_then_given_up_on():
    """A key that can never be acknowledged must not stay pending — it
    would re-open the machine's settings screen on every connect."""
    client = _RecordingClient(timeout_commands=(4508,))
    coordinator = _Coordinator(client=client, hass=_FakeHass())
    coordinator._pending_unit_pushes = {"water_source"}

    asyncio.run(coordinator._apply_unit_preferences())

    assert client.sent == [(4508, [0]), (4508, [0]), (8022, None)]
    assert coordinator._pending_unit_pushes == set()


def test_nothing_pending_sends_nothing_at_all():
    """No settings command means no page was opened, so no back-to-home
    either — 8022 on its own would yank the machine off whatever screen
    the user is on."""
    client = _RecordingClient()
    coordinator = _Coordinator(client=client, hass=_FakeHass())

    asyncio.run(coordinator._apply_unit_preferences())

    assert client.sent == []


def test_a_send_that_could_not_be_attempted_stays_pending():
    class _DeadClient:
        is_connected = False

        async def send_and_wait(self, *args, **kwargs):
            raise ConnectionError("Not connected to device")

    coordinator = _Coordinator(client=_DeadClient(), hass=_FakeHass())
    coordinator._pending_unit_pushes = {"water_source"}

    asyncio.run(coordinator._apply_unit_preferences())

    assert coordinator._pending_unit_pushes == {"water_source"}


def test_two_overlapping_pushes_are_serialized():
    """A second Settings change arriving mid-push must not interleave its
    SET with the first push's 8022, nor re-send a key the first push has
    not discarded yet — both hit the documented back-to-back drop quirk.
    """
    class _SlowClient(_RecordingClient):
        async def send_and_wait(self, command, data=None, *, raw=None, **kwargs):
            self.sent.append((command, raw if raw is not None else data))
            await asyncio.sleep(0)  # let the queued push run if it can
            return b""

    client = _SlowClient()
    coordinator = _Coordinator(client=client, hass=_FakeHass())
    coordinator.water_source = 1
    coordinator._weight_unit = "oz"

    async def _drive():
        coordinator._pending_unit_pushes = {"water_source"}
        first = asyncio.create_task(coordinator._apply_unit_preferences())
        await asyncio.sleep(0)
        coordinator._pending_unit_pushes.add("weight_unit")
        second = asyncio.create_task(coordinator._apply_unit_preferences())
        await asyncio.gather(first, second)

    asyncio.run(_drive())

    assert client.sent == [
        (4508, [1]),
        (8022, None),
        (8005, bytes([1])),
        (8022, None),
    ]
    assert coordinator._pending_unit_pushes == set()


def test_a_change_to_the_same_key_mid_send_is_not_swallowed():
    """The in-flight send carries the old value, so clearing the key after
    it would leave the machine on that value while HA shows the newer one.
    The key stays queued instead — and _handle_unit_options_change has
    already scheduled the push that drains it, so it never survives into a
    later connect where the machine's own 8015 report should win.
    """
    coordinator = _Coordinator(client=None, hass=_FakeHass())
    coordinator._weight_unit = "oz"

    class _ChangeMidSendClient(_RecordingClient):
        """Applies the user's second pick while the first send is awaiting
        its ACK — what _handle_unit_options_change does to the coordinator.
        """

        async def send_and_wait(self, command, data=None, *, raw=None, **kwargs):
            self.sent.append((command, raw if raw is not None else data))
            if command == 8005 and coordinator._weight_unit == "oz":
                coordinator._weight_unit = "ml"
                coordinator._pending_unit_pushes.add("weight_unit")
            return b""

    client = _ChangeMidSendClient()
    coordinator.client = client

    coordinator._pending_unit_pushes = {"weight_unit"}
    asyncio.run(coordinator._apply_unit_preferences())

    assert coordinator._pending_unit_pushes == {"weight_unit"}

    # The follow-up push (the one _handle_unit_options_change schedules)
    # delivers the newer value and clears the key.
    asyncio.run(coordinator._apply_unit_preferences())
    assert client.sent[-2:] == [(8005, bytes([2])), (8022, None)]
    assert coordinator._pending_unit_pushes == set()


def _async_returning(value):
    async def _call(*args, **kwargs):
        return value
    return _call


def _async_raising(exc):
    async def _call(*args, **kwargs):
        raise exc
    return _call


def _async_recording(sink):
    async def _call(*args, **kwargs):
        sink.append(True)
    return _call


def test_back_to_home_waits_for_the_page_to_open():
    """Hardware 2026-08-24: the setting's page opens ~0.46s *after* its
    command is acknowledged, so an 8022 fired on the ACK lands before the
    page exists and the machine stays on it. Verified live at 2.5s — also
    the official app's own backToHomeIn default (2500 ms).
    """
    assert _REAL_SETTLE_S >= 2.0

