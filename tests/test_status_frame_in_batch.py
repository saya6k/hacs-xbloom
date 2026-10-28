"""An 8023 status frame is read wherever it sits in a notification.

A single BLE notification can carry several frames. The status scan only
looked at the start of the buffer, so an 8023 behind another frame (the
~10 Hz weight stream) was logged by the framing loop but never updated
``raw_state_label``. Live 2026-10-28: the machine reported 0x22
(starting) after an Assist confirm, yet the brew-start verifier timed out
on the earlier 0x1E and reported "waiting for confirmation".
"""
from __future__ import annotations

from custom_components.xbloom.ble.client import XBloomClient
from tests.test_maintenance_states import _FakeConnection, _heartbeat

# 20501 weight frame, 50.0 g (captured live 2026-10-28).
_WEIGHT_FRAME = bytes.fromhex("580207155010000000c100004842a65c")


def _client() -> XBloomClient:
    return XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=_FakeConnection())


def test_status_frame_alone_is_read():
    client = _client()
    client._on_notification(None, bytearray(_heartbeat(0x22)))
    assert client.status.raw_state_label == "starting"


def test_status_frame_behind_another_frame_is_read():
    client = _client()
    client._on_notification(None, bytearray(_WEIGHT_FRAME + _heartbeat(0x22)))
    assert client.status.raw_state_label == "starting"


def test_last_status_frame_in_a_notification_wins():
    client = _client()
    client._on_notification(
        None, bytearray(_heartbeat(0x1E) + _WEIGHT_FRAME + _heartbeat(0x22))
    )
    assert client.status.raw_state_label == "starting"
