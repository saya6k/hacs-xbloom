"""HA-aware BLE transport for the native XBloom client.

Native replacement for ``_client.py``'s ``HABleakConnection`` (which
subclassed the vendored ``xbloom.connection.XBloomConnection`` ABC) and
``src/xbloom/connection/bleak_impl.py``'s bare ``BleakClient`` connector.

Connects through HA's Bluetooth integration
(``bluetooth.async_ble_device_from_address`` + ``bleak_retry_connector.
establish_connection``), not a bare ``BleakClient`` — required for HA proxy
routing and bleak-retry-connector's reconnect/cache-clear handling. A bare
client's reconnect after a mode-switch-induced BLE drop has historically
come back with garbled notifications instead of a clean resync; this path
avoids that.
"""
from __future__ import annotations

import logging
import warnings
from typing import Callable, Optional

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .framing import split_write_chunks

_LOGGER = logging.getLogger(__name__)


class HABleakConnection:
    """BLE transport for one XBloom device, backed by HA's Bluetooth stack."""

    def __init__(
        self,
        hass: HomeAssistant,
        disconnected_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self._hass = hass
        self._client: Optional[BleakClient] = None
        self._disconnected_callback = disconnected_callback

    async def connect(self, address: str, timeout: float = 20.0) -> bool:
        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, address, connectable=True
        )
        if ble_device is None:
            raise ConnectionError(f"XBloom device {address} not found via HA Bluetooth")
        self._client = await establish_connection(
            BleakClient,
            ble_device,
            address,
            timeout=timeout,
            disconnected_callback=self._on_bleak_disconnected,
        )
        return self._client.is_connected

    def _on_bleak_disconnected(self, client: BleakClient) -> None:
        """bleak's own disconnect hook — fires for both requested and dropped links.

        The coordinator tells the two apart (it skips reconnecting after its
        own ``async_disconnect()``); this just relays the event.
        """
        _LOGGER.warning("XBloom BLE link disconnected")
        if self._disconnected_callback:
            self._hass.loop.call_soon_threadsafe(self._disconnected_callback)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def write_command(self, char_uuid: str, data: bytes, response: bool = False) -> None:
        if not self.is_connected:
            raise ConnectionError("Not connected")
        # bleak's own .mtu_size property warns ("Using default MTU value...")
        # whenever the real MTU hasn't been negotiated yet — which is every
        # write until the first GATT operation completes negotiation.
        # Harmless (we already fall back to 23, bleak's own conservative
        # default), but noisy. Suppress just this one known-benign warning
        # rather than calling bleak's private _acquire_mtu() ourselves.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Using default MTU value")
            mtu_size = getattr(self._client, "mtu_size", None) or 23
        chunks = split_write_chunks(bytes(data), mtu_size)
        if len(chunks) > 1:
            _LOGGER.debug(
                "Splitting %d-byte write into %d chunks (mtu=%d)",
                len(data), len(chunks), mtu_size,
            )
        for chunk in chunks:
            await self._client.write_gatt_char(char_uuid, chunk, response=response)

    async def start_notify(
        self, char_uuid: str, callback: Callable[[int, bytearray], None]
    ) -> None:
        if not self.is_connected:
            raise ConnectionError("Not connected")
        await self._client.start_notify(char_uuid, callback)

    async def stop_notify(self, char_uuid: str) -> None:
        if self.is_connected:
            try:
                await self._client.stop_notify(char_uuid)
            except Exception as exc:
                _LOGGER.warning("Failed to stop notify: %s", exc)
