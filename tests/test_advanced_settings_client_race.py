"""_async_refresh_advanced_settings must survive a disconnect racing it.

Hardware-reported 2026-08-24: the BLE link dropped seconds after connect
on an HA restart, and the advanced-settings GET — scheduled as a
background task from async_connect — ran after _handle_unexpected_disconnect
had already set coordinator.client = None, producing

    Advanced settings refresh failed: 'NoneType' object has no attribute
    'async_get_pour_radius'

instead of a clean "not connected". Same race async_connect's own
docstring documents for its local `client` variable, and the same fix
_apply_unit_preferences already uses: take the client as an argument.
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator.advanced_settings import AdvancedSettingsMixin


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def async_get_pour_radius(self) -> None:
        self.calls.append("pour_radius")

    async def async_get_vibration_amplitude(self) -> None:
        self.calls.append("vibration_amplitude")


class _Coordinator(AdvancedSettingsMixin):
    def __init__(self, client) -> None:
        self.client = client


def test_refresh_uses_the_passed_client_when_self_client_is_gone():
    client = _FakeClient()
    coordinator = _Coordinator(client=None)  # disconnect already nulled it
    asyncio.run(coordinator._async_refresh_advanced_settings(client))
    assert client.calls == ["pour_radius", "vibration_amplitude"]


def test_refresh_is_a_noop_when_there_is_no_client_at_all():
    coordinator = _Coordinator(client=None)
    asyncio.run(coordinator._async_refresh_advanced_settings())  # must not raise


def test_refresh_falls_back_to_self_client():
    client = _FakeClient()
    coordinator = _Coordinator(client=client)
    asyncio.run(coordinator._async_refresh_advanced_settings())
    assert client.calls == ["pour_radius", "vibration_amplitude"]
