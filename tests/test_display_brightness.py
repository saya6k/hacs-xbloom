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


def test_brightness_service_returns_the_machine_home_afterwards():
    """The 8103 SET leaves the machine on its own display page — the
    official app chains backToHome() (8022) off that command's success
    callback, and hardware-reported 2026-08-24 the same shape on the
    water-source page left the machine waiting for a manual confirm.
    """
    from custom_components.xbloom.coordinator.advanced_settings import (
        AdvancedSettingsMixin,
    )

    calls: list[str] = []

    class _Coordinator(AdvancedSettingsMixin):
        def __init__(self) -> None:
            self.client = self

        async def _async_ensure_connected(self):
            return True

        async def async_set_display_brightness(self, level):
            calls.append(f"brightness={level}")

        async def _async_return_machine_home(self, client):
            calls.append("back_to_home")

        async def async_refresh(self):
            pass

    coordinator = _Coordinator()
    result = asyncio.run(
        coordinator.async_set_advanced_settings(display_brightness_level=2)
    )

    assert result == {"success": True}
    assert calls == ["brightness=2", "back_to_home"]
