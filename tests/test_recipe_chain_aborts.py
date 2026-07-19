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


# Captured before the autouse fixture below can shrink them.
_REAL_COFFEE_SETTLE = brewing._STEP_SETTLE_COFFEE_S
_REAL_TEA_SETTLE = brewing._STEP_SETTLE_TEA_S


@pytest.fixture(autouse=True)
def _fast_floors(monkeypatch):
    """Shrink the inter-step floors for every test in this module.

    The real 1.0s/2.0s values would add ~10s to the suite without testing
    anything the shrunken ones don't — what each test here asserts is
    ordering and abort behaviour. The values themselves are pinned by
    ``test_settle_floors_match_the_verified_values``, which reads the
    constants directly rather than timing them.
    """
    monkeypatch.setattr(brewing, "_STEP_SETTLE_COFFEE_S", 0.01)
    monkeypatch.setattr(brewing, "_STEP_SETTLE_TEA_S", 0.01)


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


def _step_gaps(monkeypatch, arm, recipe, settle: float) -> list[float]:
    """Run an arm chain with a shrunken floor and return the step gaps.

    The real 1.0s/2.0s floors would add ~9s to the suite for no extra
    coverage — what matters is that the chain honours whatever the
    constant says. ``test_settle_floors_match_the_verified_values`` pins
    the values themselves.
    """
    monkeypatch.setattr(brewing, "_STEP_SETTLE_COFFEE_S", settle)
    monkeypatch.setattr(brewing, "_STEP_SETTLE_TEA_S", settle)
    client = _FlakyClient()
    stamps: list[float] = []
    real = client.send_and_wait

    async def timed(command, *a, **kw):
        stamps.append(asyncio.get_running_loop().time())
        return await real(command, *a, **kw)

    client.send_and_wait = timed
    asyncio.run(arm(client, recipe))
    return [b - a for a, b in zip(stamps, stamps[1:])]


def test_steps_are_floor_spaced_even_when_acks_are_instant(monkeypatch):
    # The ACK means "received", not "applied", so the floor must survive an
    # instantly-ACKing machine — an intermediate version relied on the ACK
    # alone and lost the spacing entirely. (That version was also seen to
    # run a grind recipe as no-grind, but restoring the floor did not fix
    # that, so the two are not known to be connected — see
    # brewing._STEP_SETTLE_COFFEE_S.)
    gaps = _step_gaps(monkeypatch, brewing._async_arm_coffee, _coffee(), 0.2)

    assert len(gaps) == 3
    for gap in gaps:
        assert gap >= 0.19, f"steps too close: {gaps}"


def test_tea_steps_are_floor_spaced_too(monkeypatch):
    gaps = _step_gaps(monkeypatch, brewing._async_arm_tea, _tea(), 0.2)

    assert len(gaps) == 3
    for gap in gaps:
        assert gap >= 0.19, f"steps too close: {gaps}"


def test_settle_floors_match_the_verified_values():
    # Both are the pre-ACK-gating shipped values, restored deliberately;
    # tea's 2.0s dates to the 2026-05-13 investigation.
    assert _REAL_COFFEE_SETTLE == 1.0
    assert _REAL_TEA_SETTLE == 2.0


def test_a_healthy_chain_sends_every_step_in_order():
    client = _FlakyClient()

    asyncio.run(brewing._async_arm_coffee(client, _coffee()))

    assert client.sent == [8022, 8102, 8104, 8001]


def test_a_healthy_tea_chain_sends_every_step_in_order():
    client = _FlakyClient()

    asyncio.run(brewing._async_arm_tea(client, _tea()))

    assert client.sent == [8022, 8102, 8104, 4513]
