"""0x45 is the tea steep screen, part of a running brew.

Live 2026-10-28: a two-steep tea brew sent 0x45 with each 9012
(TEA_RECIPE_SOAK) and 0x23 when the steep drained. Unmapped, it logged
"not in the known-code map; please report it" on every steep.
"""
from __future__ import annotations

from custom_components.xbloom.ble.client import XBloomClient
from tests.test_maintenance_states import _FakeConnection, _heartbeat


def test_tea_steep_screen_reads_as_brewing():
    client = XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())
    client._on_notification(None, bytearray(_heartbeat(0x45)))
    assert client.status.raw_state_label == "brewing"
    assert client.status.screen is None
