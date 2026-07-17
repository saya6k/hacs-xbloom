"""Grinder/brewer command senders.

Native replacement for ``src/xbloom/components/grinder.py`` and
``brewer.py``. ``ScaleController`` has no native equivalent — nothing in
this integration calls ``client.scale.*`` (scale weight is read from
``client.status.scale.weight`` instead), and the vendored ``ScaleController``
only wrapped the ``SG_*`` tray-motor commands, which are confirmed not real
(the official app never sends them — see project memory
``xbloom-removed-features``).
"""
from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

from .constants import Command

if TYPE_CHECKING:
    from .client import XBloomClient


class GrinderController:
    def __init__(self, client: "XBloomClient") -> None:
        self._client = client
        self._size: int = 50
        self._speed: int = 100

    async def enter_mode(self, size: int | None = None, speed: int | None = None) -> bool:
        """Enter grinder mode — must be called before start()."""
        if size is not None:
            self._size = size
        if speed is not None:
            self._speed = speed
        return await self._client._send_command(Command.GRINDER_IN, [self._size, self._speed])

    async def start(self, size: int | None = None, speed: int | None = None) -> bool:
        """Start the grinder. Enters grinder mode first (sets size/speed on
        the machine), waits for the burrs to adjust, then starts with no
        further params."""
        if size is not None:
            self._size = size
        if speed is not None:
            self._speed = speed
        await self.enter_mode()
        await asyncio.sleep(2.0)
        return await self._client._send_command(Command.GRINDER_START)

    async def stop(self) -> bool:
        return await self._client._send_command(Command.GRINDER_STOP)

    async def pause(self) -> bool:
        return await self._client._send_command(Command.GRINDER_PAUSE)

    async def restart(self) -> bool:
        return await self._client._send_command(Command.GRINDER_RESTART)

    @property
    def size(self) -> int:
        return self._size

    @property
    def speed(self) -> int:
        return self._speed

    @property
    def is_running(self) -> bool:
        return self._client.status.grinder.is_running

    @property
    def position(self) -> int:
        return self._client.status.grinder.position


class BrewerController:
    def __init__(self, client: "XBloomClient") -> None:
        self._client = client

    async def start(
        self,
        volume: float = 100.0,
        temperature: float = 93.0,
        flow_rate: float = 3.0,
        pattern: int = 2,
        water_source: int = 0,
    ) -> bool:
        """Start pouring. Payload: 5 LE u32s — flow*10, volume*10, temp*10
        (each as float32 bit patterns), water_source, pattern."""
        flow_bits = struct.unpack("<I", struct.pack("<f", flow_rate * 10))[0]
        volume_bits = struct.unpack("<I", struct.pack("<f", volume * 10))[0]
        temp_bits = struct.unpack("<I", struct.pack("<f", temperature * 10))[0]
        payload = struct.pack("<5I", flow_bits, volume_bits, temp_bits, water_source, pattern)
        return await self._client._send_command_raw(Command.BREWER_START, payload)

    async def stop(self) -> bool:
        return await self._client._send_command(Command.BREWER_STOP)

    async def pause(self) -> bool:
        return await self._client._send_command(Command.BREWER_PAUSE)

    async def restart(self) -> bool:
        return await self._client._send_command(Command.BREWER_RESTART)

    @property
    def temperature(self) -> float:
        return self._client.status.brewer.temperature

    @property
    def is_running(self) -> bool:
        return self._client.status.brewer.is_running
