"""HA-side wrapper around the vendored xbloom.XBloomClient.

Upstream xbloom only exposes status callbacks (on_status_update). The HA
event entities need (category, event_type) callbacks for grind/brew start
and stop, bloom, errors, etc. This subclass extends _handle_response to
fire those events without modifying the vendored package.

It also implements a fallback MachineInfo extractor: the upstream
_on_notification parses packet length from bytes 5–8 and bails out when
that field looks corrupt, sometimes silently discarding RD_MachineInfo
frames. We scan the raw notification for the cmd-id signature and recover
serial / firmware version directly. ``theModel`` is skipped — the
firmware leaves it 0xFF-padded on every observed unit, so the surfaced
model entity has been removed.

Machine-info string decoding mirrors src/xbloom-ble/python/xbloom.py
(brAzzi64): keep only printable ASCII (0x20-0x7E) bytes. The vendored
upstream calls ``decode('utf-8', errors='ignore').strip('\\x00')`` which
silently passes 0xFF padding through whenever it forms a valid UTF-8
sequence with neighboring bytes — produces garbage on firmwares that
zero-fill ``theModel`` with 0xFF.

Handshake handling: the vendored ``XBloomClient.connect`` runs
``_reset_state`` after subscribing notifications but never sends the
``8100`` MTU-handshake packet. Per src/xbloom-ble/PROTOCOL.md the machine
silently ignores every command (no display wake, no MachineInfo
notification) until that handshake arrives. We override ``_reset_state``
to send it first so the upstream cleanup commands actually take effect
and ``RD_MachineInfo`` (40521) is emitted.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional

from xbloom import XBloomClient
from xbloom.protocol import XBloomResponse

_LOGGER = logging.getLogger(__name__)

# Cmd 40521 (RD_MachineInfo) as little-endian bytes, matching the upstream
# packet layout: header(3) | cmd(2) | len(4) | type(1) | payload | crc(2).
_MACHINE_INFO_CMD_BYTES = (40521).to_bytes(2, "little")  # b"\x09\xa9"

# MachineInfo payload byte offsets (from PROTOCOL.md field map).
# Mode is a 4-byte hex string at payload offset 51–54:
#   "91327856" → Easy/Auto Mode, anything else → Pro Mode.
_MACHINE_INFO_MODE_OFFSET = 51
_MACHINE_INFO_MODE_LEN = 4
_MACHINE_INFO_MODE_EASY_HEX = "91327856"

EventCallback = Callable[[str, str, dict], None]

# 8100 — MTU handshake. Cherry-picked from
# src/xbloom-ble/python/xbloom.py:HANDSHAKE = build_packet_type1(8100, [185, 1]).
HANDSHAKE_CMD = 8100
HANDSHAKE_DATA = [185, 1]


def strict_ascii(data: bytes) -> str:
    """Return printable-ASCII (0x20–0x7E) bytes only, trimmed.

    Cherry-picked from src/xbloom-ble/python/xbloom.py
    ``_handshake_notify._hex_ascii``. Drops 0xFF padding, NULs, and any
    other byte the firmware uses as filler in MachineInfo strings.
    """
    return "".join(chr(b) for b in data if 0x20 <= b < 0x7F).strip()


_NOTIFICATION_MAP = {
    XBloomResponse.RD_GRINDER_BEGIN: "grinding_started",
    XBloomResponse.RD_Grinder_Stop: "grinding_complete",
    XBloomResponse.RD_BREWER_BEGIN: "brewing_started",
    XBloomResponse.RD_BREWER_COFFEE_START: "brewing_started",
    XBloomResponse.RD_Brewer_Stop: "pour_complete",
    XBloomResponse.RD_BLOOM: "bloom",
    XBloomResponse.RD_BREWER_PAUSE: "paused",
    XBloomResponse.RD_TEA_RECIP_PAUSE: "paused",
    XBloomResponse.RD_ENJOY: "recipe_complete",
    XBloomResponse.RD_ENJOY2: "recipe_complete",
    XBloomResponse.RD_TEA_RECIP_SOAK: "tea_soaking",
    XBloomResponse.RD_TEA_RECIP_CHANGE_SOAK_TIME: "tea_soak_time_changed",
}

_ERROR_MAP = {
    XBloomResponse.RD_ErrorIdling: "no_beans",
    XBloomResponse.RD_ErrorLackOfWater: "water_shortage",
    XBloomResponse.RD_AbnormalDoseOrWater: "abnormal_dose_or_water",
    XBloomResponse.RD_AbnormalGearPosition: "abnormal_gear_position",
}


class XBloomClientWithEvents(XBloomClient):
    """XBloomClient subclass exposing on_event() for HA event entities."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._event_callbacks: List[EventCallback] = []

    def on_event(self, callback: EventCallback) -> None:
        self._event_callbacks.append(callback)

    async def async_send_handshake(self) -> bool:
        """Send the 8100 MTU handshake the firmware needs to wake up.

        Cherry-picked from src/xbloom-ble/python/xbloom.py — without this,
        the machine ignores every subsequent command and never sends the
        ``RD_MachineInfo`` (40521) notification.
        """
        if not self.is_connected:
            return False
        try:
            await self._send_command(HANDSHAKE_CMD, HANDSHAKE_DATA)
            return True
        except Exception as exc:
            _LOGGER.warning("Handshake send failed: %s", exc)
            return False

    async def _reset_state(self) -> None:
        """Send the 8100 handshake before the upstream cleanup commands.

        Per src/xbloom-ble/PROTOCOL.md: ``APP_RECIPE_STOP`` /
        ``BREWER_QUIT`` / ``GRINDER_QUIT`` are silently dropped if the
        machine has not received the handshake first. Sending it here
        keeps the upstream cleanup intact while letting MachineInfo
        flow on the very first connection.
        """
        await self.async_send_handshake()
        # brAzzi64 captures show the machine takes ~100-200ms to ack the
        # handshake before it accepts further writes.
        await asyncio.sleep(0.2)
        await super()._reset_state()

    def _fire_event(
        self,
        category: str,
        event_type: str,
        attributes: Optional[dict] = None,
    ) -> None:
        for cb in self._event_callbacks:
            try:
                cb(category, event_type, attributes or {})
            except Exception as exc:
                _LOGGER.error("Event callback error: %s", exc)

    def _machine_mode(self) -> str:
        """Return ``easy`` or ``pro`` from the cached MachineInfo payload.

        Reads the raw mode bytes stored during ``_handle_response`` /
        ``_scan_for_machine_info``.  Falls back to ``pro`` when not yet
        available (the coordinator treats ``pro`` as the safe default).
        """
        raw = getattr(self._status, "_mode_bytes", None)
        if not raw or len(raw) < _MACHINE_INFO_MODE_OFFSET + _MACHINE_INFO_MODE_LEN:
            return "pro"
        mode_slice = raw[_MACHINE_INFO_MODE_OFFSET : _MACHINE_INFO_MODE_OFFSET + _MACHINE_INFO_MODE_LEN]
        return "easy" if mode_slice.hex() == _MACHINE_INFO_MODE_EASY_HEX else "pro"

    def _on_notification(self, char, data: bytearray) -> None:
        raw = bytes(data)
        char_uuid = str(getattr(char, "uuid", char))
        # DEBUG, not INFO — the firmware floods weight/water-volume frames
        # at multi-Hz rates and HA rate-limits the log at 200 messages.
        # Diagnostic confirmed nothing useful hides in these packets.
        _LOGGER.debug(
            "BLE notify on %s (%d bytes): %s",
            char_uuid, len(raw), raw.hex(),
        )
        # Recover MachineInfo even if upstream's length-based parser discards
        # the frame. Run BEFORE super() so a successful manual extract beats
        # a bogus parser warning.
        if not self._status.serial_number:
            self._scan_for_machine_info(raw)
        super()._on_notification(char, data)

    def _scan_for_machine_info(self, raw: bytes) -> None:
        """Extract RD_MachineInfo by signature, ignoring the length field.

        Packet layout: header(0x58|0x02) | dev_id | type | cmd(2 LE) |
        len(4 LE) | const(0x01) | payload | crc(2). We locate cmd bytes
        09 A9 (40521 LE) at offset+3 and decode payload starting at offset+10.
        """
        idx = 0
        while True:
            idx = raw.find(_MACHINE_INFO_CMD_BYTES, idx)
            if idx < 0 or idx < 3:
                return
            header_byte = raw[idx - 3]
            if header_byte not in (0x58, 0x02):
                idx += 1
                continue
            payload = raw[idx + 7 :]
            if len(payload) < 34:
                _LOGGER.debug(
                    "Manual MachineInfo signature found but payload too "
                    "short (%d bytes) at offset %d",
                    len(payload), idx - 3,
                )
                idx += 2
                continue
            try:
                serial = strict_ascii(payload[0:13])
                version = strict_ascii(payload[19:29])
            except Exception as exc:
                _LOGGER.debug("Manual MachineInfo decode error: %s", exc)
                return
            if serial:
                self._status.serial_number = serial
                self._status.version = version
                self._status._mode_bytes = payload
                _LOGGER.info(
                    "Manual MachineInfo extract: serial=%r version=%r mode=%s",
                    serial, version, self._machine_mode(),
                )
            return

    def _handle_response(self, response: XBloomResponse, data: bytes) -> None:
        if response == XBloomResponse.RD_MachineInfo:
            payload = data[10:-2] if len(data) > 12 else b""
            _LOGGER.info(
                "RD_MachineInfo packet received: payload_len=%d hex=%s",
                len(payload), payload.hex(),
            )
        super()._handle_response(response, data)
        if response == XBloomResponse.RD_MachineInfo:
            payload = data[10:-2] if len(data) > 12 else b""
            # Re-decode with the strict-printable filter — overrides the
            # upstream UTF-8 decode that lets 0xFF padding through.
            # ``theModel`` (payload[13:19]) is intentionally skipped: the
            # firmware leaves it 0xFF-padded on every observed unit and
            # the model entity has been removed.
            if len(payload) >= 29:
                self._status.serial_number = strict_ascii(payload[0:13])
                self._status.version = strict_ascii(payload[19:29])
            # Cache the raw payload so _machine_mode() can extract the
            # mode bytes at offset 51–54.
            self._status._mode_bytes = payload
            _LOGGER.info(
                "RD_MachineInfo parsed: serial=%r version=%r water_ok=%s mode=%s",
                self._status.serial_number,
                self._status.version,
                self._status.water_level_ok,
                self._machine_mode(),
            )
        if response in _NOTIFICATION_MAP:
            self._fire_event("notification", _NOTIFICATION_MAP[response])
        elif response in _ERROR_MAP:
            self._fire_event("error", _ERROR_MAP[response])
