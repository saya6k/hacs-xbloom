"""Best-effort XBloom device discovery for the config flow's MAC pre-fill.

Native replacement for ``src/xbloom/scanner.py``. Uses a bare
``BleakScanner`` (not routed through HA's Bluetooth integration) — this
is a pre-existing, deliberately low-stakes shortcut: it only pre-fills a
text field the user can freely overwrite, unlike the actual connect path
(``ble/connection.py``), which always goes through HA's Bluetooth stack.
"""
from __future__ import annotations

from typing import List

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from .constants import SERVICE_UUID


async def discover_devices(timeout: float = 5.0) -> List[BLEDevice]:
    """Discover XBloom devices in range.

    Tries the advertised service UUID first; falls back to scanning
    everything and filtering by name, since some devices don't advertise
    the custom service UUID in their main advertising packet.
    """
    devices = await BleakScanner.discover(timeout=timeout, service_uuids=[SERVICE_UUID])
    if not devices:
        all_devices = await BleakScanner.discover(timeout=timeout)
        devices = [d for d in all_devices if d.name and "XBLOOM" in d.name.upper()]
    return devices
