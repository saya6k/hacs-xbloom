"""Tests for coordinator.XBloomCoordinator._async_retry_while_sleeping.

Decompiled 2026-07-17/18 from the official app's AppBleManager.sendMessage/
createDisposable: every command it sends is wrapped in a 1.5s ACK-timeout
retry that resends the identical command while the machine reports itself
asleep (up to 3 retries), and stops the instant it's not sleeping. This
integration had only implemented that pattern for the mode-switch command
(_async_switch_mode_with_retry) — hardware-reported 2026-07-17: operating
the machine (grind/pour/tare/calibrate/execute recipe/easy-slot write)
while it was asleep silently did nothing, since nothing else retried.

Calls the real unbound method off XBloomCoordinator with a minimal
duck-typed stand-in for `self` (just a `.client` attribute) — legacy/1.4.x
predates the coordinator/ package split (main branch), so there's no
separable ConnectionMixin to import here.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator import (
    XBloomCoordinator,
    _WAKE_RETRY_DELAY_S,
    _WAKE_RETRY_MAX_ATTEMPTS,
)

_retry_while_sleeping = XBloomCoordinator._async_retry_while_sleeping


class _FakeClient:
    def __init__(self, sleeping_for_n_checks: int = 0) -> None:
        # How many times is_sleeping() should report True before flipping
        # to False (simulating the machine waking up mid-retry).
        self._remaining_sleeping_checks = sleeping_for_n_checks
        self.is_sleeping_call_count = 0

    def is_sleeping(self) -> bool:
        self.is_sleeping_call_count += 1
        if self._remaining_sleeping_checks > 0:
            self._remaining_sleeping_checks -= 1
            return True
        return False


class _FakeSelf:
    def __init__(self, client) -> None:
        self.client = client


def _no_sleep(monkeypatch):
    """Skip the real asyncio.sleep delay between retries so tests run fast."""

    async def _fast_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def test_single_success_when_never_sleeping(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=0)
    fake_self = _FakeSelf(client)
    calls = []

    async def action():
        calls.append(1)

    asyncio.run(_retry_while_sleeping(fake_self, action))
    assert len(calls) == 1
    assert client.is_sleeping_call_count == 1


def test_retries_while_sleeping_then_stops_once_awake(monkeypatch):
    _no_sleep(monkeypatch)
    # Reports asleep for the first 2 checks, awake on the 3rd.
    client = _FakeClient(sleeping_for_n_checks=2)
    fake_self = _FakeSelf(client)
    calls = []

    async def action():
        calls.append(1)

    asyncio.run(_retry_while_sleeping(fake_self, action))
    assert len(calls) == 3  # 1 initial send + 2 retries, then stops


def test_caps_at_max_attempts_if_still_sleeping(monkeypatch):
    _no_sleep(monkeypatch)
    # Always reports asleep — must not retry forever.
    client = _FakeClient(sleeping_for_n_checks=_WAKE_RETRY_MAX_ATTEMPTS + 10)
    fake_self = _FakeSelf(client)
    calls = []

    async def action():
        calls.append(1)

    asyncio.run(_retry_while_sleeping(fake_self, action))
    assert len(calls) == _WAKE_RETRY_MAX_ATTEMPTS


def test_action_called_fresh_each_retry_not_reused_coroutine(monkeypatch):
    # A real bug shape: passing a single already-created coroutine object
    # (e.g. `client.foo()` instead of `client.foo`) would raise
    # "cannot reuse already awaited coroutine" on the second attempt.
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=1)
    fake_self = _FakeSelf(client)
    seen = []

    async def action():
        seen.append(len(seen))

    asyncio.run(_retry_while_sleeping(fake_self, action))
    assert seen == [0, 1]


def test_waits_the_expected_delay_between_retries(monkeypatch):
    sleeps = []

    async def _record_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)
    client = _FakeClient(sleeping_for_n_checks=1)
    fake_self = _FakeSelf(client)

    async def action():
        pass

    asyncio.run(_retry_while_sleeping(fake_self, action))
    assert sleeps == [_WAKE_RETRY_DELAY_S]
