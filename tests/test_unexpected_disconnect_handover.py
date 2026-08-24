"""An unexpected drop must not race the link back instantly.

Hardware-measured 2026-08-24: after a disconnect the machine re-advertises
in 1.0-1.9s and another central can take it 2.0-3.0s later — but a phone
needs its user to open the app and scan first. _handle_unexpected_disconnect
used to fire a reconnect within milliseconds, so when the machine dropped
HA to hand the slot to the phone, HA took it straight back and the phone
never got in. Reconnecting is now the supervisor's job (poll tick, 5s by
default), the same call this made for _async_drop_stale_link on 2026-07-19.
"""
from __future__ import annotations

from custom_components.xbloom.coordinator.connection import ConnectionMixin


class _FakeHass:
    def __init__(self) -> None:
        self.created_tasks: list = []

    def async_create_task(self, coro):
        self.created_tasks.append(coro)
        coro.close()
        return None


class _Coordinator(ConnectionMixin):
    def __init__(self, *, manual: bool = False) -> None:
        self.hass = _FakeHass()
        self.client = object()
        self._manual_disconnect = manual
        self._machine_info_task = None


def test_drop_does_not_schedule_an_immediate_reconnect():
    coordinator = _Coordinator()
    coordinator._handle_unexpected_disconnect()
    assert coordinator.client is None
    assert coordinator.hass.created_tasks == []


def test_our_own_disconnect_is_left_alone():
    """The connection switch / idle standby path must keep its client
    teardown to itself — this handler is only for machine-side drops."""
    coordinator = _Coordinator(manual=True)
    sentinel = coordinator.client
    coordinator._handle_unexpected_disconnect()
    assert coordinator.client is sentinel
    assert coordinator.hass.created_tasks == []


def test_supervisor_still_reconnects_after_the_drop():
    """The backstop is what picks it up — it must not be gated by
    anything the drop handler leaves behind."""
    coordinator = _Coordinator()
    coordinator._handle_unexpected_disconnect()

    import asyncio

    coordinator._idle_disconnected = False
    coordinator._connect_lock = asyncio.Lock()
    coordinator._reconnect_blocked_until = 0.0
    coordinator.async_connect = _noop_coro
    coordinator._maybe_schedule_reconnect()
    assert len(coordinator.hass.created_tasks) == 1


async def _noop_coro():
    return True
