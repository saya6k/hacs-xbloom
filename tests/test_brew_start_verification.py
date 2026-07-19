"""Post-8002 brew-start verification (_async_verify_brew_started).

The 8002 echo ACK says nothing about whether the brew started; the
machine's raw status heartbeat is the real signal. An unconfirmed outcome
must raise rather than guess, and the verifier must send NOTHING while
watching — the third-party "40518 starts from awaiting-confirm" claim was
tried live on this machine (2026-07-19) and bounced the state back to
recipe_loaded instead of starting.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.xbloom.brewing import (
    BrewStartUnconfirmed,
    _async_verify_brew_started,
)


class _FakeClient:
    def __init__(self, labels: list[str | None]) -> None:
        """``labels`` is consumed one per poll; the last value then sticks."""
        self._labels = list(labels)
        self.status = SimpleNamespace(raw_state_label=None)
        self.sent: list[int] = []
        self._advance()

    def _advance(self) -> None:
        if self._labels:
            self.status.raw_state_label = self._labels.pop(0)

    async def _send_command(self, command, data=None, device_id=None):
        self.sent.append(int(command))
        return True


def _run(client: _FakeClient, timeout: float = 0.5) -> str:
    async def scenario():
        async def ticker():
            while True:
                await asyncio.sleep(0.05)
                client._advance()

        tick = asyncio.create_task(ticker())
        try:
            return await _async_verify_brew_started(client, timeout=timeout)
        finally:
            tick.cancel()

    return asyncio.run(scenario())


def test_returns_when_the_machine_starts_on_its_own():
    client = _FakeClient([None, None, "starting"])

    assert _run(client) == "starting"
    assert client.sent == []  # no 40518 when the machine acted


def test_brewing_also_counts_as_started():
    client = _FakeClient(["brewing"])

    assert _run(client) == "brewing"


def test_refusal_raises_with_the_reason():
    client = _FakeClient([None, "no_beans"])

    with pytest.raises(BrewStartUnconfirmed, match="no_beans"):
        _run(client)
    assert client.sent == []


def test_awaiting_confirm_can_still_resolve_if_the_user_confirms():
    # A human pressing the machine's own confirm screen mid-watch.
    client = _FakeClient([None, "awaiting_confirm", "awaiting_confirm", "starting"])

    assert _run(client) == "starting"
    assert client.sent == []


def test_silence_fails_closed():
    client = _FakeClient([None])

    with pytest.raises(BrewStartUnconfirmed):
        _run(client, timeout=0.2)
    assert client.sent == []


def test_awaiting_confirm_stall_raises_and_sends_nothing():
    # Live-refuted 2026-07-19: 40518 from awaiting-confirm bounced the
    # machine back to recipe_loaded instead of starting, so the verifier
    # must never try to nudge — it names the state and lets the human act.
    client = _FakeClient(["awaiting_confirm"])

    with pytest.raises(BrewStartUnconfirmed, match="its own screen"):
        _run(client, timeout=0.2)
    assert client.sent == []
