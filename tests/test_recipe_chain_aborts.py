"""The recipe arm chains must abort on a step the machine never ACKed.

Phase 2 of the official-app parity work. Before ACK gating, the chain was
spaced with fixed sleeps and could not tell a delivered step from a dropped
one — a missed 8102 still ran on to the 8002 execute, starting a brew
against a recipe the machine never received. That is the behavior these
tests pin.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom import brewing
from custom_components.xbloom.ble.client import AckTimeout, XBloomClient
from custom_components.xbloom.ble.models import CupType, PourStep, XBloomRecipe


class _FlakyClient:
    """Records sends; refuses to ACK one nominated command."""

    is_connected = True
    _bypass_args = staticmethod(XBloomClient._bypass_args)
    _cup_args = staticmethod(XBloomClient._cup_args)

    def __init__(self, deaf_to: int | None = None) -> None:
        self.sent: list[int] = []
        self.deaf_to = deaf_to
        self.executed = False

    async def send_and_wait(
        self, command, data=None, *, raw=None, timeout=1.5,
        device_id=None, type_code=0x01,
    ):
        self.sent.append(int(command))
        if self.deaf_to is not None and int(command) == self.deaf_to:
            raise AckTimeout(f"No ACK for {command}")
        return b""

    async def _send_command(self, command, payload=None, device_id=None):
        self.sent.append(int(command))
        return True

    async def _send_command_raw(self, command, data, device_id=None, type_code=0x01):
        self.sent.append(int(command))
        return True

    async def execute_coffee_recipe(self, device_id=None):
        self.executed = True


def _coffee() -> XBloomRecipe:
    return XBloomRecipe(
        name="V60", grind_size=35, rpm=90, cup_type=int(CupType.OMNI_DRIPPER),
        bean_weight=18.0, pours=[PourStep(volume=250, temperature=93)],
    )


def _tea() -> XBloomRecipe:
    return XBloomRecipe(
        name="Chamomile", grind_size=0, rpm=0, cup_type=int(CupType.TEA),
        bean_weight=0.0, total_water=240,
        pours=[PourStep(volume=120, temperature=100, pausing=300)],
    )


@pytest.mark.parametrize(
    "deaf_to, label",
    [(8022, "back to home"), (8102, "set bypass"), (8104, "set cup")],
)
def test_coffee_chain_stops_at_the_unacked_step(deaf_to, label):
    client = _FlakyClient(deaf_to=deaf_to)

    with pytest.raises(AckTimeout):
        asyncio.run(brewing._async_arm_coffee(client, _coffee()))

    # The failing command is the last thing attempted — nothing after it
    # was sent, and above all the recipe payload never went out.
    assert client.sent[-1] == deaf_to, f"{label}: chain continued past the failure"
    assert 8001 not in client.sent
    assert 8004 not in client.sent


def test_coffee_single_shot_never_executes_when_the_chain_fails():
    # The whole point: a dropped step must not end in an 8002 execute
    # against a recipe the machine does not have.
    client = _FlakyClient(deaf_to=8102)

    with pytest.raises(AckTimeout):
        asyncio.run(brewing._async_brew_coffee(client, _coffee()))

    assert client.executed is False


def test_tea_chain_stops_at_the_unacked_step():
    client = _FlakyClient(deaf_to=8104)

    with pytest.raises(AckTimeout):
        asyncio.run(brewing._async_arm_tea(client, _tea()))

    assert client.sent[-1] == 8104
    assert 4513 not in client.sent


def test_tea_single_shot_never_makes_when_the_chain_fails():
    client = _FlakyClient(deaf_to=4513)

    with pytest.raises(AckTimeout):
        asyncio.run(brewing._async_brew_tea(client, _tea()))

    # 4512 (TEA_RECIPE_MAKE) is what actually starts a steep.
    assert 4512 not in client.sent


def test_a_healthy_chain_sends_every_step_in_order():
    client = _FlakyClient()

    asyncio.run(brewing._async_arm_coffee(client, _coffee()))

    assert client.sent == [8022, 8102, 8104, 8001]


def test_a_healthy_tea_chain_sends_every_step_in_order():
    client = _FlakyClient()

    asyncio.run(brewing._async_arm_tea(client, _tea()))

    assert client.sent == [8022, 8102, 8104, 4513]
