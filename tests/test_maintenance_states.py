"""Knob-triple-press maintenance states (T16 / SPEC A2–A4).

Codes hardware-captured 2026-07-20 (T2): descale-confirm screen 0x2F
(0x32 with cancel selected), scale-calibration-confirm 0x39 (0x3A), and
the grinder-calibration phases 0x26/0x27 — machine-entered grinder
calibration now reads the same calibrating_grinder as the HA-triggered
one. 0x25 (calibration-complete screen) stays unmapped (→ idle).
"""
from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from custom_components.xbloom.ble.client import XBloomClient
from custom_components.xbloom.coordinator.state import StateMixin


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


def _heartbeat(code: int) -> bytes:
    payload = struct.pack("<I", code)
    return (
        bytes([0x58, 0x02, 0x07])
        + (8023).to_bytes(2, "little")
        + (12 + len(payload)).to_bytes(4, "little")
        + bytes([0xC1])
        + payload
        + b"\x00\x00"
    )


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (0x26, "calibrating_grinder"),
        (0x27, "calibrating_grinder"),
        (0x2F, "descaling"),
        (0x32, "descaling"),
        (0x39, "calibrating_scale"),
        (0x3A, "calibrating_scale"),
    ],
)
def test_maintenance_codes_map_to_state_labels(code, label):
    client = XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())
    client._on_notification(None, bytearray(_heartbeat(code)))
    assert client.status.raw_state_label == label
    # Maintenance screens are activities, not standalone pages.
    assert client.status.screen is None


def test_calibration_complete_screen_stays_unmapped():
    client = XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())
    client._on_notification(None, bytearray(_heartbeat(0x25)))
    assert client.status.raw_state_label is None


class _Coordinator(StateMixin):
    def __init__(self) -> None:
        self._armed_operation = None
        self._no_beans = False
        self._water_shortage = False
        self.client = SimpleNamespace(is_calibrating_grinder=lambda: False)


@pytest.mark.parametrize("label", ["descaling", "calibrating_scale", "calibrating_grinder"])
def test_derived_state_passes_the_labels_through(label):
    coordinator = _Coordinator()
    status = SimpleNamespace(
        raw_state_label=label,
        screen=None,
        state=SimpleNamespace(value="idle"),
        grinder=SimpleNamespace(is_running=False),
        brewer=SimpleNamespace(is_running=False),
    )
    assert coordinator._derive_state_string(status) == label
