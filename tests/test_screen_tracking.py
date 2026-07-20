"""Screen-code tracking (T3 of the standalone-mode overhaul).

Pins the machine-screen map established by the 2026-07-20 T2 live capture
(see docs/en/protocol.md's raw-status-heartbeat row and project memory
xbloom-t2-screen-code-capture): heartbeat/8023 page codes are the primary
channel, the 9xxx IN_*/OUT_* pairs are auxiliary, and 9001 (IN_BREWER) is a
page-entry settings snapshot — NOT a "brewing started" signal.
"""
from __future__ import annotations

import struct

import pytest

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.ble.models import DeviceState


class _FakeConnection:
    is_connected = False

    async def connect(self, address, timeout=20.0):
        return False

    async def disconnect(self):
        pass

    async def write_command(self, char_uuid, data, response=False):
        pass

    async def start_notify(self, char_uuid, callback):
        pass

    async def stop_notify(self, char_uuid):
        pass


def _client() -> XBloomClient:
    return XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())


def _frame(cmd: int, payload: bytes = b"") -> bytes:
    """Inbound frame as observed on hardware 2026-07-20:
    58 02 07 | cmd LE(2) | total_len LE(4) | marker 0xC1 | payload | crc(2)."""
    total_len = 12 + len(payload)
    return (
        bytes([0x58, 0x02, 0x07])
        + cmd.to_bytes(2, "little")
        + total_len.to_bytes(4, "little")
        + bytes([0xC1])
        + payload
        + b"\x00\x00"
    )


def _heartbeat(code: int) -> bytes:
    return _frame(8023, struct.pack("<I", code))


@pytest.mark.parametrize(
    ("code", "screen"),
    [
        (0x01, "home"),       # PRO home
        (0x41, "home"),       # Easy Mode home
        (0x02, "grind"),      # grind page
        (0x06, "grind"),      # grind-size adjust subscreen
        (0x07, "grind"),      # RPM adjust subscreen
        (0x03, "pour"),       # pour page
        (0x08, "pour"),       # pattern adjust subscreen
        (0x09, "pour"),       # temperature adjust subscreen
        (0x04, "scale"),      # scale entry
        (0x05, "scale"),      # scale page
    ],
)
def test_heartbeat_code_maps_to_screen(code, screen):
    client = _client()
    client._on_notification(None, bytearray(_heartbeat(code)))
    assert client.status.screen_code == code
    assert client.status.screen == screen


def test_unmapped_code_clears_screen_but_keeps_state_label():
    """Activity codes (0x22 starting, etc.) are not screens — the screen
    resets to None (self-correcting, like raw_state_label) while the
    existing state-label tracking keeps working on the same frame."""
    client = _client()
    client._on_notification(None, bytearray(_heartbeat(0x02)))
    assert client.status.screen == "grind"
    client._on_notification(None, bytearray(_heartbeat(0x22)))
    assert client.status.screen is None
    assert client.status.screen_code == 0x22
    assert client.status.raw_state_label == "starting"


@pytest.mark.parametrize(
    ("cmd", "payload", "screen"),
    [
        (9000, struct.pack("<2I", 43, 120), "grind"),          # IN_GRINDER snapshot
        (9001, struct.pack("<4I", 250, 56, 0, 56), "pour"),    # IN_BREWER snapshot
        (9002, b"", "scale"),                                  # IN_SCALE
        (9004, b"", "home"),                                   # OUT_GRINDER
        (9006, b"", "home"),                                   # OUT_BREWER
        (9008, b"", "home"),                                   # OUT_SCALE
    ],
)
def test_in_out_notifications_set_screen(cmd, payload, screen):
    client = _client()
    client._on_notification(None, bytearray(_frame(cmd, payload)))
    assert client.status.screen == screen


def test_in_brewer_is_a_page_snapshot_not_brewing():
    """Hardware 2026-07-20: 9001 fires on knob-driven pour-page ENTRY with
    a (volume, temp, pattern, temp) settings snapshot. It must not claim
    the brewer is running — that made HA report "brewing" for a machine
    merely sitting on its pour page."""
    client = _client()
    client._on_notification(
        None, bytearray(_frame(9001, struct.pack("<4I", 250, 56, 0, 56)))
    )
    assert client.status.brewer.is_running is False
    assert client.status.state != DeviceState.BREWING
    assert client.status.screen == "pour"
    # The snapshot's temperature is still mirrored for the knob-sync path.
    assert client.status.brewer.temperature == 56.0


def test_screen_defaults_to_none():
    client = _client()
    assert client.status.screen is None
    assert client.status.screen_code is None


def test_page_report_clears_latched_run_flags():
    """A 4507-stopped pour never sends 40511 (hardware 2026-07-20), so
    brewer.is_running latched True forever and stuck the derived state at
    "brewing". The machine showing a page or home means nothing is
    running — page codes clear both run flags."""
    client = _client()
    client.status.brewer.is_running = True
    client.status.grinder.is_running = True
    client._on_notification(None, bytearray(_heartbeat(0x03)))
    assert client.status.brewer.is_running is False
    assert client.status.grinder.is_running is False


def test_activity_code_does_not_clear_run_flags():
    client = _client()
    client.status.brewer.is_running = True
    client._on_notification(None, bytearray(_heartbeat(0x23)))  # brewing
    assert client.status.brewer.is_running is True
