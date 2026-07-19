"""Tests for XBloomClient.send_and_wait — the ACK-gated send primitive.

Phase 1 of the official-app parity work (tasks/2026-07-app-parity-spec.md).
The app's AppBleManager.sendMessage takes a per-command timeout plus
success/fail callbacks, and its multi-step sequences chain the next step
from the previous step's success callback rather than after a fixed delay.
This primitive is what lets us do the same; nothing calls it yet.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom.ble.client import (
    ACK_TIMEOUT_S,
    AckTimeout,
    XBloomClient,
)
from custom_components.xbloom.ble.framing import TYPE1_MARKER_BYTE


def _ack_frame(command: int, marker: int = TYPE1_MARKER_BYTE) -> bytes:
    """Build a bare acknowledgement frame the way the machine sends one.

    Shaped after a real capture of the 8012 ACK
    (``5802074c1f0c000000c1e444``): header, device id, echoed command,
    total length, marker, CRC. ``iter_frames`` does not verify the CRC,
    so the trailing bytes are arbitrary.
    """
    return (
        bytes([0x58, 0x02, 0x07])
        + command.to_bytes(2, "little")
        + (12).to_bytes(4, "little")
        + bytes([marker, 0x00, 0x00])
    )


class _FakeConnection:
    """Records writes; optionally echoes an ACK back through the client."""

    def __init__(self) -> None:
        self.is_connected = True
        self.writes: list[bytes] = []
        self.client: XBloomClient | None = None
        self.echo: int | None = None

    async def write_command(self, uuid, packet: bytes, response: bool = False) -> None:
        self.writes.append(packet)
        if self.echo is not None:
            # The machine answers on its own notification characteristic.
            self.client._on_notification(None, bytearray(_ack_frame(self.echo)))

    async def disconnect(self) -> None:
        self.is_connected = False

    async def stop_notify(self, uuid) -> None:
        pass


def _client(echo: int | None = None) -> tuple[XBloomClient, _FakeConnection]:
    connection = _FakeConnection()
    client = XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=connection)
    connection.client = client
    connection.echo = echo
    client._status.connected = True
    return client, connection


def test_resolves_when_the_machine_echoes_the_command():
    client, connection = _client(echo=8012)

    frame = asyncio.run(client.send_and_wait(8012, timeout=1.0))

    assert connection.writes, "command was never written"
    assert frame  # the echoed frame is handed back to the caller


def test_raises_ack_timeout_when_nothing_comes_back():
    client, _ = _client(echo=None)

    with pytest.raises(AckTimeout):
        asyncio.run(client.send_and_wait(8012, timeout=0.05))


def test_an_unrelated_echo_does_not_resolve_the_waiter():
    # Telemetry floods at ~10 Hz; a waiter must not be satisfied by whatever
    # frame happens to arrive next.
    client, _ = _client(echo=20501)

    with pytest.raises(AckTimeout):
        asyncio.run(client.send_and_wait(8012, timeout=0.05))


def test_waiters_are_cleaned_up_on_both_paths():
    client, _ = _client(echo=8012)
    asyncio.run(client.send_and_wait(8012, timeout=1.0))
    assert client._pending_acks == {}

    client, _ = _client(echo=None)
    with pytest.raises(AckTimeout):
        asyncio.run(client.send_and_wait(8012, timeout=0.05))
    assert client._pending_acks == {}


def test_disconnect_aborts_an_in_flight_wait():
    # Otherwise a sequence interrupted by a dropped link sits out its full
    # timeout on every remaining step instead of failing fast.
    client, _ = _client(echo=None)

    async def scenario():
        waiter = asyncio.create_task(client.send_and_wait(8012, timeout=30.0))
        await asyncio.sleep(0)
        await client.disconnect()
        await waiter

    with pytest.raises(AckTimeout):
        asyncio.run(scenario())


def test_raw_payloads_go_through_the_raw_sender():
    client, connection = _client(echo=11511)

    asyncio.run(client.send_and_wait(11511, raw=b"\x00\x00\x00\x00", type_code=2, timeout=1.0))

    assert connection.writes


def test_default_timeout_matches_the_app():
    # AppBleManager.DefaultTimeOut = 1500L
    assert ACK_TIMEOUT_S == 1.5


def test_send_failure_does_not_leak_a_waiter():
    client, connection = _client(echo=None)
    connection.is_connected = False
    client._status.connected = False

    with pytest.raises(ConnectionError):
        asyncio.run(client.send_and_wait(8012, timeout=1.0))
    assert client._pending_acks == {}
