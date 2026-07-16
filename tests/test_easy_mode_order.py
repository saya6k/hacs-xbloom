"""Tests for brewing.async_write_easy_slots' cmd 11512 (Easy Mode slot
order) frame — added after decompiling the official app confirmed
`BleCodeFactory$Companion.easyModeRecipesOrder()` is a real call, not a
third-party embellishment (see AGENTS.md's command-id validation sweep,
2026-07-16)."""
from __future__ import annotations

import asyncio

from custom_components.xbloom import brewing
from xbloom.models.types import CupType, PourStep, XBloomRecipe


class _FakeClient:
    is_connected = True

    def __init__(self):
        self.calls: list[tuple[int, bytes, int]] = []

    async def _send_command_raw(self, command, data, device_id=None, type_code=0x01):
        self.calls.append((command, bytes(data), type_code))
        return True


def _recipe(name: str) -> XBloomRecipe:
    return XBloomRecipe(
        name=name,
        grind_size=60,
        rpm=100,
        cup_type=int(CupType.OMNI_DRIPPER),
        bean_weight=15.0,
        pours=[PourStep(volume=250, temperature=93)],
    )


def test_order_frame_sent_after_all_three_slots():
    client = _FakeClient()
    slot_recipes = {"A": _recipe("A"), "B": _recipe("B"), "C": _recipe("C")}
    asyncio.run(brewing.async_write_easy_slots(client, slot_recipes))

    # 3 slot writes (11510) + 1 order frame (11512), in that order.
    commands = [c[0] for c in client.calls]
    assert commands == [11510, 11510, 11510, 11512]


def test_order_frame_is_type2_with_canonical_abc_payload():
    client = _FakeClient()
    slot_recipes = {"A": _recipe("A"), "B": _recipe("B"), "C": _recipe("C")}
    asyncio.run(brewing.async_write_easy_slots(client, slot_recipes))

    order_cmd, order_payload, order_type = client.calls[-1]
    assert order_cmd == 11512
    assert order_type == 2
    # [slot_count, then A/B/C indices in canonical order] — matches
    # Mel0day/xbloom-ai-brew's observed default ('03000102').
    assert order_payload == bytes([3, 0, 1, 2])
