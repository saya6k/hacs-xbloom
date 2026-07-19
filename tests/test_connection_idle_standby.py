"""Tests for the connection supervisor's two link-dropping paths
(2026-07-19): the silence watchdog and idle standby.

Both were reshaped after decompiling the official app — see project memory
(xbloom-app-connection-lifecycle-and-page-quit). The app's own "heart
check" only ever DISCONNECTS a quiet link (reconnecting is left to the
next tick of its ordinary 5s poll loop), and its supervise/reconnect loop
is skipped entirely while the app is backgrounded, so the vendor's client
never holds an unattended link at all.
"""
from __future__ import annotations

import asyncio
import time

from custom_components.xbloom.coordinator.connection import ConnectionMixin
from custom_components.xbloom.coordinator.state import StateMixin


class _FakeHass:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    def async_create_task(self, coro) -> None:
        self.tasks.append(coro.cr_code.co_name)
        coro.close()  # never actually run — we only assert it was scheduled


class _FakeClient:
    def __init__(self, *, sleeping: bool = False, silence: float = 0.0) -> None:
        self.is_connected = True
        self._sleeping = sleeping
        self._silence = silence

    def is_sleeping(self) -> bool:
        return self._sleeping

    def seconds_since_last_notification(self) -> float:
        return self._silence


class _Coordinator(StateMixin, ConnectionMixin):
    def __init__(self, client: _FakeClient, *, session_timeout: int = 60) -> None:
        self.hass = _FakeHass()
        self.client = client
        self._force_reconnect_pending = False
        self._idle_standby_pending = False
        self._idle_disconnected = False
        self._manual_disconnect = False
        self._session_timeout = session_timeout
        self._last_activity_monotonic = time.monotonic()
        self._armed_operation = None
        self._active_operation = None
        self._pod_prompt_active = False

    def _note_activity(self) -> None:
        self._last_activity_monotonic = time.monotonic()


def _idle_for(coordinator: _Coordinator, seconds: float) -> None:
    coordinator._last_activity_monotonic = time.monotonic() - seconds


async def _tick(coordinator: _Coordinator) -> dict:
    return await coordinator._async_update_data()


def test_silence_watchdog_drops_a_wedged_link():
    coordinator = _Coordinator(_FakeClient(silence=30.0))
    asyncio.run(_tick(coordinator))

    assert coordinator.hass.tasks == ["_async_drop_stale_link"]


def test_silence_watchdog_ignores_a_sleeping_machine():
    coordinator = _Coordinator(_FakeClient(sleeping=True, silence=30.0))
    asyncio.run(_tick(coordinator))

    # A sleeping machine going quiet is normal. Treating it as a wedged
    # link is what turned every overnight idle period into a
    # disconnect/reconnect loop.
    assert coordinator.hass.tasks == []


def test_idle_standby_drops_the_link_after_the_timeout():
    coordinator = _Coordinator(_FakeClient(), session_timeout=60)
    _idle_for(coordinator, 61)
    asyncio.run(_tick(coordinator))

    assert coordinator.hass.tasks == ["_async_enter_idle_standby"]


def test_idle_standby_is_disabled_by_a_zero_timeout():
    coordinator = _Coordinator(_FakeClient(), session_timeout=0)
    _idle_for(coordinator, 3600)
    asyncio.run(_tick(coordinator))

    assert coordinator.hass.tasks == []


def test_idle_standby_waits_for_an_armed_operation_to_resolve():
    coordinator = _Coordinator(_FakeClient(), session_timeout=60)
    coordinator._armed_operation = "grind"
    _idle_for(coordinator, 3600)
    asyncio.run(_tick(coordinator))

    # The user armed something and walked away — dropping the link here
    # would silently strand the confirm press.
    assert coordinator.hass.tasks == []


def test_reconnect_supervisor_stays_off_during_idle_standby():
    coordinator = _Coordinator(_FakeClient())
    coordinator._idle_disconnected = True

    coordinator._maybe_schedule_reconnect()

    assert coordinator.hass.tasks == []


def test_reconnect_supervisor_runs_when_not_in_standby():
    coordinator = _Coordinator(_FakeClient())
    coordinator._connect_lock = asyncio.Lock()
    coordinator._maybe_schedule_reconnect()

    assert coordinator.hass.tasks == ["async_connect"]
