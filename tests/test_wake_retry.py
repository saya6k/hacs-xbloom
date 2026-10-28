"""Tests for coordinator.connection.ConnectionMixin._async_retry_while_sleeping.

Decompiled 2026-07-17/18 from the official app's AppBleManager.sendMessage/
createDisposable: every command it sends is wrapped in a 1.5s ACK-timeout
retry that resends the identical command while the machine reports itself
asleep (up to 3 retries), and stops the instant it's not sleeping. This
integration had only implemented that pattern for the mode-switch command
(_async_switch_mode_with_retry) — hardware-reported 2026-07-17: operating
the machine (grind/pour/tare/calibrate/execute recipe/easy-slot write)
while it was asleep silently did nothing, since nothing else retried.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom.ble.client import AckTimeout
from custom_components.xbloom.coordinator.connection import ConnectionMixin
from custom_components.xbloom.coordinator.constants import (
    _WAKE_RETRY_DELAY_S,
    _WAKE_RETRY_MAX_ATTEMPTS,
)


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


class _Coordinator(ConnectionMixin):
    def __init__(self, client) -> None:
        self.client = client

    async def _async_wake_machine(self) -> None:
        # The wake step has its own tests (test_wake_before_action.py);
        # these cover the resend loop on its own.
        pass


def _no_sleep(monkeypatch):
    """Skip the real asyncio.sleep delay between retries so tests run fast."""

    async def _fast_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def test_single_success_when_never_sleeping(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=0)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)

    asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert len(calls) == 1
    # One up-front check (asleep at start?) plus one after the action.
    assert client.is_sleeping_call_count == 2


def test_retries_while_sleeping_then_stops_once_awake(monkeypatch):
    _no_sleep(monkeypatch)
    # Reports asleep for the up-front check and after the first 2 sends,
    # awake after the 3rd.
    client = _FakeClient(sleeping_for_n_checks=3)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)

    asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert len(calls) == 3  # 1 initial send + 2 retries, then stops


def test_caps_at_max_attempts_if_still_sleeping(monkeypatch):
    _no_sleep(monkeypatch)
    # Always reports asleep — must not retry forever.
    client = _FakeClient(sleeping_for_n_checks=_WAKE_RETRY_MAX_ATTEMPTS + 10)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)

    asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert len(calls) == _WAKE_RETRY_MAX_ATTEMPTS


def test_action_called_fresh_each_retry_not_reused_coroutine(monkeypatch):
    # A real bug shape: passing a single already-created coroutine object
    # (e.g. `client.foo()` instead of `client.foo`) would raise
    # "cannot reuse already awaited coroutine" on the second attempt.
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=2)
    coordinator = _Coordinator(client)
    seen = []

    async def action():
        seen.append(len(seen))

    asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert seen == [0, 1]


def test_returns_the_action_result(monkeypatch):
    # 2026-07-18: added so async_arm_recipe can get the built tea payload
    # back from brewing.async_arm_recipe through the retry wrapper — every
    # pre-existing caller ignores the return value, so this is additive.
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=0)
    coordinator = _Coordinator(client)

    async def action():
        return "some-payload"

    result = asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert result == "some-payload"


def test_returns_the_last_result_even_after_retries(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=3)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)
        return len(calls)

    result = asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert result == 3  # the 3rd (final, successful) attempt's return value


def test_waits_the_expected_delay_between_retries(monkeypatch):
    sleeps = []

    async def _record_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)
    client = _FakeClient(sleeping_for_n_checks=2)
    coordinator = _Coordinator(client)

    async def action():
        pass

    asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert sleeps == [_WAKE_RETRY_DELAY_S]


def test_ack_timeout_while_asleep_is_retried(monkeypatch):
    # Live 2026-10-28: a recipe arm's first 8022 to the sleeping machine
    # went unacknowledged and the arm failed outright; the same 8022 sent
    # again was ACKed in 86 ms.
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=1)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)
        if len(calls) == 1:
            raise AckTimeout("No ACK for 8022")
        return "armed"

    result = asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert result == "armed"
    assert len(calls) == 2


def test_ack_timeout_while_awake_is_not_retried(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=0)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)
        raise AckTimeout("No ACK for 8022")

    with pytest.raises(AckTimeout):
        asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert len(calls) == 1


def test_ack_timeout_gives_up_after_max_attempts(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient(sleeping_for_n_checks=_WAKE_RETRY_MAX_ATTEMPTS + 10)
    coordinator = _Coordinator(client)
    calls = []

    async def action():
        calls.append(1)
        raise AckTimeout("No ACK for 8022")

    with pytest.raises(AckTimeout):
        asyncio.run(coordinator._async_retry_while_sleeping(action))
    assert len(calls) == _WAKE_RETRY_MAX_ATTEMPTS
