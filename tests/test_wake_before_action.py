"""A user action on a sleeping machine wakes it first.

Live 2026-10-28 (rc.3): with the link held, the sleeping machine kept
streaming 20501 but ignored three 8022 sends 1.5 s apart; a reconnect
(8100 handshake) woke it (8011). The official app sends 8100 only right
after connecting, so a held link has no app-defined wake path. The
handshake is tried on the held link first (cheap, unverified), then a
reconnect (verified) — but never a reconnect while something is armed,
since connecting sends the cleanup commands that would clear it.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator.connection import ConnectionMixin


class _Client:
    def __init__(self, coordinator, wakes_on):
        self._coordinator = coordinator
        self._wakes_on = wakes_on

    def is_sleeping(self) -> bool:
        return self._coordinator.asleep

    async def async_send_handshake(self) -> bool:
        self._coordinator.calls.append("handshake")
        if self._wakes_on == "handshake":
            self._coordinator.asleep = False
        return True


class _Coordinator(ConnectionMixin):
    def __init__(self, *, asleep, wakes_on, armed=None):
        self.asleep = asleep
        self.calls: list[str] = []
        self._wakes_on = wakes_on
        self._armed_operation = armed
        self._manual_disconnect = False
        self.client = _Client(self, wakes_on)

    async def async_disconnect(self) -> None:
        self.calls.append("disconnect")
        self._manual_disconnect = True
        self.client = None

    async def async_connect(self) -> bool:
        self.calls.append("connect")
        self.client = _Client(self, self._wakes_on)
        if self._wakes_on == "reconnect":
            self.asleep = False
        return True


def test_wait_awake_gives_up_on_a_machine_that_stays_asleep(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator(asleep=True, wakes_on=None)
    assert asyncio.run(coordinator._async_wait_awake()) is False


def _run(coordinator):
    async def action():
        coordinator.calls.append("action")
        return "done"

    return asyncio.run(coordinator._async_retry_while_sleeping(action))


def _no_sleep(monkeypatch):
    async def _fast_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def test_awake_machine_is_not_woken(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator(asleep=False, wakes_on="handshake")
    assert _run(coordinator) == "done"
    assert coordinator.calls == ["action"]


def test_handshake_that_wakes_skips_the_reconnect(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator(asleep=True, wakes_on="handshake")
    assert _run(coordinator) == "done"
    assert coordinator.calls == ["handshake", "action"]


def test_reconnect_when_the_handshake_does_not_wake(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator(asleep=True, wakes_on="reconnect")
    assert _run(coordinator) == "done"
    assert coordinator.calls == ["handshake", "disconnect", "connect", "action"]
    # Our own drop must not read as a user-requested disconnect.
    assert coordinator._manual_disconnect is False


def test_no_reconnect_while_something_is_armed(monkeypatch):
    _no_sleep(monkeypatch)
    coordinator = _Coordinator(asleep=True, wakes_on="reconnect", armed="recipe")
    _run(coordinator)
    assert "disconnect" not in coordinator.calls
    assert "connect" not in coordinator.calls
    assert coordinator.calls[0] == "handshake"
