"""Tests for ble.client.XBloomClient.async_set_display_brightness —
cmd 8103 (RD_LetType), decompiled from the official app's
MachineDisplayActivity 2026-07-16 (see project memory
xbloom-advanced-features-jadx-findings). Untested on real hardware; this
only checks the level->raw mapping and that the right command/payload
gets sent.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.ble.constants import Command


class _FakeConnection:
    is_connected = False


def _client() -> XBloomClient:
    return XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())


def test_level_1_2_3_map_to_raw_1_8_15():
    client = _client()
    calls = []

    async def fake_send_command(command, data=None, **kwargs):
        calls.append((command, data))
        return True

    client._send_command = fake_send_command

    asyncio.run(client.async_set_display_brightness(1))
    asyncio.run(client.async_set_display_brightness(2))
    asyncio.run(client.async_set_display_brightness(3))

    assert calls == [
        (Command.SET_DISPLAY_BRIGHTNESS, [1]),
        (Command.SET_DISPLAY_BRIGHTNESS, [8]),
        (Command.SET_DISPLAY_BRIGHTNESS, [15]),
    ]
