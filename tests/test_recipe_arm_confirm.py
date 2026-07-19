"""Tests for brewing.async_arm_recipe/async_confirm_recipe — the arm/
confirm split behind the two-stage manual execute-recipe button flow
(2026-07-18). Also pins that the single-shot _async_brew_coffee/
_async_brew_tea (async_execute_recipe's path — the execute_recipe /
execute_tea_recipe services and every LLM tool) still send the full
sequence unchanged after being refactored into arm + confirm halves.

asyncio.sleep is patched out — these tests only care about command
ordering/content, not the real inter-command spacing (already covered by
the fact this is the same code the pre-refactor single-shot functions
used, just reordered into two callable halves).
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom import brewing
from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.ble.models import CupType, PourStep, XBloomRecipe


class _FakeClient:
    is_connected = True

    def __init__(self):
        self.raw_calls: list[tuple[int, bytes, int]] = []
        self.plain_calls: list[tuple] = []
        self.executed = False

    async def _send_command_raw(self, command, data, device_id=None, type_code=0x01):
        self.raw_calls.append((int(command), bytes(data), type_code))
        return True

    async def _send_command(self, command, payload=None, device_id=None):
        self.plain_calls.append(("_send_command", int(command), payload))
        return True

    async def set_bypass(self, volume, temperature, dose):
        self.plain_calls.append(("set_bypass", volume, temperature, dose))
        return True

    async def set_cup(self, cup_max, cup_min):
        self.plain_calls.append(("set_cup", cup_max, cup_min))
        return True

    async def execute_coffee_recipe(self, device_id=None):
        self.executed = True

    # The arm chains are ACK-gated (2026-07-19), so they go through
    # send_and_wait rather than the bare senders. Route both forms into
    # the same recorders and reuse the real argument packing, so these
    # tests keep asserting on the actual wire payloads.
    _bypass_args = staticmethod(XBloomClient._bypass_args)
    _cup_args = staticmethod(XBloomClient._cup_args)

    async def send_and_wait(
        self, command, data=None, *, raw=None, timeout=1.5,
        device_id=None, type_code=0x01,
    ):
        if raw is not None:
            await self._send_command_raw(command, raw, device_id, type_code)
        else:
            await self._send_command(command, data, device_id)
        return b""


def _coffee_recipe() -> XBloomRecipe:
    return XBloomRecipe(
        name="V60", grind_size=35, rpm=90, cup_type=int(CupType.OMNI_DRIPPER),
        bean_weight=18.0, pours=[PourStep(volume=250, temperature=93)],
    )


def _tea_recipe() -> XBloomRecipe:
    return XBloomRecipe(
        name="Chamomile", grind_size=0, rpm=0, cup_type=int(CupType.TEA),
        bean_weight=0.0,
        pours=[PourStep(volume=120, temperature=80, pausing=60)],
    )


def _no_sleep(monkeypatch):
    async def _fast_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def test_arm_coffee_sends_recipe_but_not_execute(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient()
    result = asyncio.run(brewing.async_arm_recipe(client, _coffee_recipe()))

    assert result is None  # coffee confirm needs no payload back
    assert client.executed is False
    # 8001 (RECIPE_SEND_AUTO, grinding) was sent as the last raw command.
    assert client.raw_calls
    assert client.raw_calls[-1][0] == 8001


def test_confirm_coffee_sends_execute(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient()
    asyncio.run(brewing.async_confirm_recipe(client, is_tea=False))

    assert client.executed is True


def test_arm_tea_sends_recipe_code_but_not_make(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient()
    payload = asyncio.run(brewing.async_arm_recipe(client, _tea_recipe()))

    assert isinstance(payload, (bytes, bytearray))
    assert client.raw_calls
    assert client.raw_calls[-1][0] == 4513  # TEA_RECIPE_CODE
    assert all(cmd != 4512 for cmd, _payload, _type in client.raw_calls)


def test_confirm_tea_resends_identical_payload(monkeypatch):
    _no_sleep(monkeypatch)
    client = _FakeClient()
    payload = asyncio.run(brewing.async_arm_recipe(client, _tea_recipe()))

    asyncio.run(brewing.async_confirm_recipe(client, is_tea=True, tea_payload=payload))

    make_calls = [c for c in client.raw_calls if c[0] == 4512]
    assert len(make_calls) == 1
    assert make_calls[0][1] == payload


def test_confirm_tea_without_payload_raises():
    client = _FakeClient()
    with pytest.raises(ValueError):
        asyncio.run(brewing.async_confirm_recipe(client, is_tea=True, tea_payload=None))


def test_single_shot_coffee_still_sends_full_sequence(monkeypatch):
    """Regression: async_execute_recipe's coffee path (used by the
    execute_recipe service / every LLM tool) must still both queue AND
    execute in one call after the arm/confirm refactor."""
    _no_sleep(monkeypatch)
    client = _FakeClient()
    asyncio.run(brewing.async_execute_recipe(client, _coffee_recipe()))

    assert client.executed is True
    assert client.raw_calls[-1][0] == 8001


def test_single_shot_tea_still_sends_full_sequence(monkeypatch):
    """Regression: async_execute_recipe's tea path must still queue
    (4513) AND make (4512, same payload) in one call."""
    _no_sleep(monkeypatch)
    client = _FakeClient()
    asyncio.run(brewing.async_execute_recipe(client, _tea_recipe()))

    codes = [c[0] for c in client.raw_calls]
    assert codes.count(4513) == 1
    assert codes.count(4512) == 1
    code_payload = {c[0]: c[1] for c in client.raw_calls}
    assert code_payload[4513] == code_payload[4512]
