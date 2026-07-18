"""Native XBloom Studio BLE client.

Replaces both the upstream PyBloom's ``core/client.py`` (base connection/
send/receive) and ``_client.py``'s ``XBloomClientWithEvents`` (the override
layer that had grown to dominate actual runtime behavior) with one
consolidated implementation — see
``adr/001-clean-room-reimplementation-of-xbloom-ble.md``.

Only the primitives this integration actually calls are implemented —
the vendored high-level ``brew()``/``brew_without_grinding()``/
``send_recipe()``/``execute_recipe()``/``send_coffee_recipe()``/
``confirm_next()``/``set_easy_mode()``/``set_temperature()`` have no call
site anywhere in this codebase (``brewing.py`` builds its own inline
command sequences) and are not carried over.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Callable, List, Optional

from .components import BrewerController, GrinderController
from .connection import HABleakConnection
from .constants import Command, NOTIFY_UUID, READ_CHAR_UUID, Response, WRITE_UUID, command_name
from .framing import (
    MAX_PACKET_LEN,
    TYPE2_MARKER_BYTE,
    build_packet,
    build_packet_raw,
    frame_command,
    frame_payload,
    iter_frames,
)
from .models import DeviceState, DeviceStatus

_LOGGER = logging.getLogger(__name__)

EventCallback = Callable[[str, str, dict], None]
StatusCallback = Callable[[DeviceStatus], None]

# MachineInfo payload byte offsets (from the upstream xbloom-ble's PROTOCOL.md field
# map, plus two more cross-referenced against a third-party HA integration
# — see docs/en/protocol.md and project memory for provenance).
_MACHINE_INFO_MODE_OFFSET = 51
_MACHINE_INFO_MODE_LEN = 4
_MACHINE_INFO_MODE_EASY_HEX = "91327856"
_MACHINE_INFO_GRIND_SIZE_OFFSET = 37
_MACHINE_INFO_VOLTAGE_OFFSET = 39

# Cmd 40521 (RD_MachineInfo) as little-endian bytes — used to recover the
# frame by signature when the length-bounded framing loop discards it.
_MACHINE_INFO_CMD_BYTES = int(Response.MACHINE_INFO).to_bytes(2, "little")

_GRIND_SIZE_RAW_OFFSET = 30  # UI value = max(1, raw - 30)
_VALID_POUR_PATTERNS = (0, 1, 2)
_GRINDER_CALIBRATION_DONE_RAW = 85

# Raw status-heartbeat frame — distinct framing from the cmd-tagged
# responses above (type byte 0x57, no Response enum entry). See
# docs/en/protocol.md.
_STATUS_FRAME_TYPE_BYTE = 0x57
_RAW_STATE_LABEL_MAP = {
    0x22: "starting",
    0x10: "brewing",
    0x23: "brewing",
    0x3B: "brewing",
    0x24: "ready",
}

_ADVANCED_SETTINGS_TYPE_CODE = 2
_CALIBRATE_GRINDER_PAYLOAD = [1000]
_DISPLAY_BRIGHTNESS_RAW = {1: 1, 2: 8, 3: 15}

HANDSHAKE_DATA = [185, 1]

_NOTIFICATION_MAP = {
    Response.GRINDER_BEGIN: "grinding_started",
    Response.GRINDER_STOP: "grinding_complete",
    Response.BREWER_BEGIN: "brewing_started",
    Response.BREWER_COFFEE_START: "brewing_started",
    Response.BREWER_STOP: "pour_complete",
    Response.BLOOM: "bloom",
    Response.BREWER_PAUSE: "paused",
    Response.TEA_RECIPE_PAUSE: "paused",
    Response.ENJOY: "recipe_complete",
    Response.ENJOY2: "recipe_complete",
    Response.TEA_RECIPE_SOAK: "tea_soaking",
    Response.TEA_RECIPE_CHANGE_SOAK_TIME: "tea_soak_time_changed",
    Response.TEA_RECIPE_RESTART: "tea_resumed",
    Response.PODS: "pod_detected",
    Response.EASYMODE_BEGIN: "easy_slot_started",
    Response.CALIBRATING: "grinder_calibration_progress",
}

_ERROR_MAP = {
    Response.ERROR_IDLING: "no_beans",
    Response.ABNORMAL_DOSE_OR_WATER: "abnormal_dose_or_water",
    Response.ABNORMAL_GEAR_POSITION: "abnormal_gear_position",
}


def strict_ascii(data: bytes) -> str:
    """Printable-ASCII (0x20-0x7E) bytes only, trimmed.

    Cherry-picked from the upstream xbloom-ble's ``python/xbloom.py``
    ``_handshake_notify._hex_ascii``. MachineInfo string fields are
    0xFF-padded, not NUL-padded — a naive UTF-8 decode lets 0xFF runs
    through whenever they form a valid sequence with neighboring bytes.
    """
    return "".join(chr(b) for b in data if 0x20 <= b < 0x7F).strip()


class XBloomClient:
    """XBloom Studio BLE client: connection lifecycle, command sending,
    notification dispatch, and the (category, event_type) event bus HA's
    event entities consume."""

    READ_CHAR = READ_CHAR_UUID

    def __init__(self, mac_address: str, connection: HABleakConnection) -> None:
        self.mac_address = mac_address
        self._connection = connection
        self._status = DeviceStatus()
        self._status_callbacks: List[StatusCallback] = []
        self._event_callbacks: List[EventCallback] = []
        self._device_id = 0x01
        # Cleanup-on-disconnect is opt-out: the coordinator disables it so
        # an unexpected drop doesn't reset in-progress brew state on the
        # machine before a reconnect can resume monitoring it.
        self._cleanup_on_disconnect = True
        # Freshly "seen" at construction time so the silence watchdog
        # doesn't false-positive before the first real notification has
        # had a chance to arrive.
        self._last_notification_monotonic: float = time.monotonic()

        self.grinder = GrinderController(self)
        self.brewer = BrewerController(self)

    @property
    def status(self) -> DeviceStatus:
        return self._status

    @property
    def is_connected(self) -> bool:
        return self._connection.is_connected

    def on_status_update(self, callback: StatusCallback) -> None:
        self._status_callbacks.append(callback)

    def on_event(self, callback: EventCallback) -> None:
        self._event_callbacks.append(callback)

    def is_sleeping(self) -> bool:
        """Whether the machine last reported itself asleep (cmd 8009/8011/8023).

        Defaults to False (matching the official app's static isSleeping
        field) until the first sleep-state notification arrives.
        """
        return self._status.is_sleeping

    def is_calibrating_grinder(self) -> bool:
        """Whether a grinder gear-position calibration sweep (cmd 3502) is
        in progress — set at send time by
        ``coordinator.async_calibrate_grinder()``, cleared on completion
        (``RD_CurrentGrinder == 85``, or the 180s timeout fallback in
        ``coordinator._async_calibration_timeout_fallback()``).
        """
        return self._status.is_calibrating_grinder

    def seconds_since_last_notification(self) -> float:
        """Seconds since the last raw BLE notification of any kind.

        The telemetry stream floods at multi-Hz under normal operation, so
        a large gap here means the GATT link is still "connected" but has
        gone silent/stale — the coordinator uses this to force a reconnect
        rather than trusting ``is_connected`` alone.
        """
        return time.monotonic() - self._last_notification_monotonic

    def _machine_mode(self) -> str:
        """Return "easy" or "pro" — the mode-switch ACK if we've seen one,
        else the connect-time MachineInfo payload.

        The firmware pushes RD_MachineInfo (40521) exactly once, at
        connect, and never again after a mode switch, so relying on that
        snapshot alone would stay stuck at whatever mode was active when
        HA first connected. The cmd-11511 (RD_EASYMODE_TYPE) ACK the
        firmware sends for every switch echoes the newly-applied mode
        code, so it's the freshest source once we've seen at least one.
        """
        if self._status.mode_ack_hex is not None:
            return "easy" if self._status.mode_ack_hex == _MACHINE_INFO_MODE_EASY_HEX else "pro"
        raw = self._status.mode_bytes
        if not raw or len(raw) < _MACHINE_INFO_MODE_OFFSET + _MACHINE_INFO_MODE_LEN:
            return "pro"
        mode_slice = raw[_MACHINE_INFO_MODE_OFFSET : _MACHINE_INFO_MODE_OFFSET + _MACHINE_INFO_MODE_LEN]
        return "easy" if mode_slice.hex() == _MACHINE_INFO_MODE_EASY_HEX else "pro"

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, timeout: float = 20.0) -> bool:
        if self._connection.is_connected:
            return True
        try:
            await self._connection.connect(self.mac_address, timeout=timeout)
        except Exception as exc:
            _LOGGER.error("Connection failed: %s", exc)
            return False
        if not self._connection.is_connected:
            return False
        await self._connection.start_notify(NOTIFY_UUID, self._on_notification)
        try:
            await self._connection.start_notify(self.READ_CHAR, self._on_notification)
        except Exception:
            pass
        self._status.connected = True
        await self._reset_state()
        await asyncio.sleep(0.5)  # settle time for the first status push
        return True

    async def disconnect(self) -> None:
        if self._connection.is_connected:
            if self._cleanup_on_disconnect:
                try:
                    await self._reset_state()
                except Exception:
                    pass
            try:
                await self._connection.stop_notify(NOTIFY_UUID)
            except Exception:
                pass
            await self._connection.disconnect()
        self._status.connected = False

    async def _reset_state(self) -> None:
        """Send the 8100 handshake, then the machine-state cleanup commands.

        The machine silently ignores every command — no display wake, no
        RD_MachineInfo — until it receives the 8100 handshake. Sending it
        first here lets the cleanup commands actually take effect and
        RD_MachineInfo flow on the very first connection.
        """
        await self.async_send_handshake()
        # The machine takes ~100-200ms to ack the handshake before it
        # accepts further writes.
        await asyncio.sleep(0.2)
        _LOGGER.info("Cleaning up machine state...")
        try:
            await self._send_command(Command.RECIPE_STOP)
            await asyncio.sleep(0.5)
            await self._send_command(Command.BREWER_QUIT)
            await self._send_command(Command.GRINDER_QUIT)
            await asyncio.sleep(0.5)
        except Exception as exc:
            _LOGGER.warning("Cleanup failed (may be disconnected): %s", exc)

    async def async_send_handshake(self) -> bool:
        if not self.is_connected:
            return False
        try:
            await self._send_command(Command.HANDSHAKE, HANDSHAKE_DATA)
            return True
        except Exception as exc:
            _LOGGER.warning("Handshake send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def _send_command(
        self,
        command: int,
        data: Optional[list] = None,
        device_id: Optional[int] = None,
        type_code: int = 0x01,
    ) -> bool:
        if not self.is_connected:
            raise ConnectionError("Not connected to device")
        target_device_id = device_id if device_id is not None else self._device_id
        packet = build_packet(command, data, device_id=target_device_id, type_code=type_code)
        _LOGGER.info(
            "SEND CMD [ID:0x%02x, Type:0x%02x]: %s (%s) | DATA: %s",
            target_device_id, type_code, command, command_name(command), packet.hex(),
        )
        await self._connection.write_command(WRITE_UUID, packet, response=False)
        return True

    async def _send_command_raw(
        self,
        command: int,
        data: bytes,
        device_id: Optional[int] = None,
        type_code: int = 0x01,
    ) -> bool:
        if not self.is_connected:
            raise ConnectionError("Not connected to device")
        target_device_id = device_id if device_id is not None else self._device_id
        packet = build_packet_raw(command, data, device_id=target_device_id, type_code=type_code)
        _LOGGER.info(
            "SEND CMD RAW [ID:0x%02x, Type:0x%02x]: %s (%s) | DATA: %s",
            target_device_id, type_code, command, command_name(command), packet.hex(),
        )
        await self._connection.write_command(WRITE_UUID, packet, response=False)
        return True

    async def stop_recipe(self, type_code: int = 1, device_id: Optional[int] = None) -> bool:
        return await self._send_command(Command.RECIPE_STOP, type_code=type_code, device_id=device_id)

    async def set_cup(
        self, f1: float, f2: float, type_code: int = 1, device_id: Optional[int] = None
    ) -> bool:
        b1 = struct.unpack("<I", struct.pack("<f", f1))[0]
        b2 = struct.unpack("<I", struct.pack("<f", f2))[0]
        return await self._send_command(Command.SET_CUP, [b1, b2], type_code=type_code, device_id=device_id)

    async def set_bypass(
        self,
        volume: float,
        temp: float,
        dose: int,
        type_code: int = 1,
        device_id: Optional[int] = None,
    ) -> bool:
        vol_bits = struct.unpack("<I", struct.pack("<f", volume))[0]
        temp_bits = struct.unpack("<I", struct.pack("<f", float(temp * 10)))[0]
        return await self._send_command(
            Command.SET_BYPASS, [vol_bits, temp_bits, int(dose)],
            type_code=type_code, device_id=device_id,
        )

    async def execute_coffee_recipe(self, device_id: Optional[int] = None) -> None:
        await self._send_command(Command.RECIPE_EXECUTE, device_id=device_id)

    # ------------------------------------------------------------------
    # Advanced settings (pour radius / vibration amplitude / brightness /
    # grinder calibration) — see docs/en/protocol.md's type-2 command
    # family and project memory (xbloom-advanced-settings-transport-bugs)
    # for why these need type_code=2.
    # ------------------------------------------------------------------

    async def async_get_pour_radius(self) -> None:
        if self.is_connected:
            await self._send_command(Command.POUR_RADIUS_GET, type_code=_ADVANCED_SETTINGS_TYPE_CODE)

    async def async_set_pour_radius(self, value: int) -> None:
        await self._send_command(
            Command.POUR_RADIUS_SET, [int(value)], type_code=_ADVANCED_SETTINGS_TYPE_CODE
        )
        self._status.pour_radius = int(value)

    async def async_get_vibration_amplitude(self) -> None:
        if self.is_connected:
            await self._send_command(
                Command.VIBRATION_AMPLITUDE_GET, type_code=_ADVANCED_SETTINGS_TYPE_CODE
            )

    async def async_set_vibration_amplitude(self, value: int) -> None:
        await self._send_command(
            Command.VIBRATION_AMPLITUDE_SET, [int(value)], type_code=_ADVANCED_SETTINGS_TYPE_CODE
        )
        self._status.vibration_amplitude = int(value)

    async def async_calibrate_grinder(self) -> None:
        """Trigger the ~120s grinder calibration sweep (cmd 3502). The
        machine runs it autonomously — no further BLE interaction needed
        once sent."""
        await self._send_command(Command.CALIBRATE_GRINDER, _CALIBRATE_GRINDER_PAYLOAD)

    async def async_set_display_brightness(self, level: int) -> None:
        """``level`` is 1-3 (matching the official app's L1-L3 labels),
        mapped to the raw device values 1/8/15."""
        await self._send_command(Command.SET_DISPLAY_BRIGHTNESS, [_DISPLAY_BRIGHTNESS_RAW[level]])

    # ------------------------------------------------------------------
    # Notification handling
    # ------------------------------------------------------------------

    def _fire_event(self, category: str, event_type: str, attributes: Optional[dict] = None) -> None:
        for cb in self._event_callbacks:
            try:
                cb(category, event_type, attributes or {})
            except Exception as exc:
                _LOGGER.error("Event callback error: %s", exc)

    def _on_notification(self, char, data: bytearray) -> None:
        self._last_notification_monotonic = time.monotonic()
        raw = bytes(data)
        char_uuid = str(getattr(char, "uuid", char))
        # DEBUG, not INFO — the firmware floods weight/water-volume frames
        # at multi-Hz rates and HA rate-limits the log at 200 messages.
        _LOGGER.debug("BLE notify on %s (%d bytes): %s", char_uuid, len(raw), raw.hex())
        # Recover MachineInfo even if the length-bounded framing loop
        # would discard the frame. Run before the framing loop so a
        # successful manual extract beats a bogus parse warning.
        if not self._status.serial_number:
            self._scan_for_machine_info(raw)
        self._scan_for_status_frame(raw)
        self._scan_for_advanced_settings(raw)
        for frame in iter_frames(raw):
            self._parse_response(frame)

    def _scan_for_status_frame(self, raw: bytes) -> None:
        """Track ``self._status.raw_state_label`` — see ``_RAW_STATE_LABEL_MAP``.

        Recomputed on every status frame (mapped code, or None for
        anything not in the map — falling through to the cmd-tagged
        ``state``). Self-correcting: a new brew's very first status frame
        (loading/armed/etc., none of which are in the map) clears any
        stale ready/starting/brewing label from a previous brew
        automatically.
        """
        if len(raw) <= 12 or raw[3] != _STATUS_FRAME_TYPE_BYTE:
            return
        payload = raw[10:-2]
        if not payload:
            return
        self._status.raw_state_label = _RAW_STATE_LABEL_MAP.get(payload[0])

    def _scan_for_advanced_settings(self, raw: bytes) -> None:
        """Raw pre-scan for cmd 11506/11507/11508/11509 responses — these
        aren't in the Response enum's dispatch table (the official app has
        no fixed response registry for them either), so they need a direct
        buffer walk rather than going through ``_parse_response``.

        Walks the whole buffer for a header match — a single notification
        can carry more than one frame, or a leading partial/unrelated
        frame, so the target frame is not guaranteed to start at offset 0.
        Marker byte is the type-2 marker (0xC2), not the usual 0xC1.
        """

        offset = 0
        n = len(raw)
        while offset < n:
            if raw[offset] not in (0x58, 0x02):
                offset += 1
                continue
            if n - offset < 14:
                break
            total_len = int.from_bytes(raw[offset + 5 : offset + 9], "little")
            if total_len > MAX_PACKET_LEN:
                offset += 1
                continue
            if raw[offset + 9] != TYPE2_MARKER_BYTE:
                offset += 1
                continue
            cmd = int.from_bytes(raw[offset + 3 : offset + 5], "little")
            if cmd in (
                Command.POUR_RADIUS_GET,
                Command.POUR_RADIUS_SET,
                Command.VIBRATION_AMPLITUDE_GET,
                Command.VIBRATION_AMPLITUDE_SET,
            ):
                value = int.from_bytes(raw[offset + 10 : offset + 14], "little")
                _LOGGER.info("Advanced settings response: cmd=%s value=%s", cmd, value)
                if cmd in (Command.POUR_RADIUS_GET, Command.POUR_RADIUS_SET):
                    self._status.pour_radius = value
                else:
                    self._status.vibration_amplitude = value
            if offset + total_len > n or total_len <= 0:
                break
            offset += total_len

    def _scan_for_machine_info(self, raw: bytes) -> None:
        """Extract RD_MachineInfo by signature, ignoring the length field —
        a fallback for firmwares where the length-bounded framing loop
        discards the frame."""
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
                self._status.mode_bytes = payload
                _LOGGER.info(
                    "Manual MachineInfo extract: serial=%r version=%r mode=%s",
                    serial, version, self._machine_mode(),
                )
            return

    def _parse_response(self, frame: bytes) -> None:
        cmd = frame_command(frame)
        _LOGGER.info("RECV CMD: %s (%s) | DATA: %s", cmd, command_name(cmd), frame.hex())
        try:
            response = Response(cmd)
        except ValueError:
            _LOGGER.debug("Unknown response command: %s", cmd)
        else:
            try:
                self._handle_response(response, frame)
            except Exception as exc:
                _LOGGER.error("Error handling response %s: %s", cmd, exc)
        for callback in self._status_callbacks:
            try:
                callback(self._status)
            except Exception as exc:
                _LOGGER.error("Callback error: %s", exc)

    def _handle_response(self, response: Response, data: bytes) -> None:
        payload = frame_payload(data)
        st = self._status

        if response == Response.MACHINE_INFO:
            _LOGGER.info(
                "RD_MachineInfo packet received: payload_len=%d hex=%s",
                len(payload), payload.hex(),
            )
            if len(payload) >= 29:
                st.serial_number = strict_ascii(payload[0:13])
                st.version = strict_ascii(payload[19:29])
            if len(payload) >= 34:
                st.water_level_ok = payload[33] == 1
            if len(payload) >= 37:
                st.water_volume = payload[36]
            st.mode_bytes = payload
            if len(payload) > _MACHINE_INFO_GRIND_SIZE_OFFSET:
                st.grinder.size = max(payload[_MACHINE_INFO_GRIND_SIZE_OFFSET] - _GRIND_SIZE_RAW_OFFSET, 1)
            if len(payload) > _MACHINE_INFO_VOLTAGE_OFFSET:
                st.voltage = payload[_MACHINE_INFO_VOLTAGE_OFFSET]
            _LOGGER.info(
                "RD_MachineInfo parsed: serial=%r version=%r water_ok=%s mode=%s",
                st.serial_number, st.version, st.water_level_ok, self._machine_mode(),
            )
        elif response == Response.GEAR_REPORT:
            if len(payload) >= 4:
                st.grinder.position = struct.unpack_from("<I", payload, 0)[0]
        elif response == Response.CURRENT_WEIGHT2:
            if len(payload) >= 4:
                st.scale.weight = struct.unpack_from("<f", payload, 0)[0]
        elif response == Response.CURRENT_WEIGHT:
            # Same float32 layout as CURRENT_WEIGHT2 (20501) — a second
            # weight-telemetry cmd some firmwares/sessions send instead.
            if len(payload) >= 4:
                st.scale.weight = struct.unpack_from("<f", payload, 0)[0]
        elif response == Response.BREWER_TEMPERATURE:
            if len(payload) >= 4:
                st.brewer.temperature = struct.unpack_from("<I", payload, 0)[0] / 10.0
        elif response == Response.GRINDER_BEGIN:
            st.grinder.is_running = True
            st.state = DeviceState.GRINDING
        elif response == Response.GRINDER_STOP:
            st.grinder.is_running = False
            st.state = DeviceState.IDLE
            # 0 RPM is a real, meaningful reading here, not "unknown".
            st.grinder.speed = 0
        elif response == Response.BREWER_BEGIN:
            st.brewer.is_running = True
            st.state = DeviceState.BREWING
        elif response == Response.BREWER_STOP:
            st.brewer.is_running = False
            st.state = DeviceState.IDLE
        elif response == Response.BLOOM:
            st.state = DeviceState.BREWING
        elif response == Response.BREWER_PAUSE:
            st.state = DeviceState.PAUSED
        elif response == Response.BREWER_COFFEE_START:
            st.brewer.is_running = True
            st.state = DeviceState.BREWING
        elif response == Response.WATER_VOLUME:
            if len(payload) >= 4:
                st.water_volume = int(struct.unpack_from("<f", payload, 0)[0])
        elif response == Response.IN_BREWER:
            if len(payload) >= 12:
                volume, temperature, pattern = struct.unpack_from("<3I", payload, 0)
                st.brewer.temperature = float(temperature)
                st.brewer.is_running = True
                st.state = DeviceState.BREWING
                _LOGGER.info("BREWER STATE: vol=%s temp=%sC pattern=%s", volume, temperature, pattern)
        elif response == Response.GRINDER_SIZE:
            if len(payload) >= 4:
                raw = struct.unpack_from("<I", payload, 0)[0]
                st.grinder.size = max(raw - _GRIND_SIZE_RAW_OFFSET, 1)
        elif response == Response.GRINDER_SPEED:
            if len(payload) >= 4:
                st.grinder.speed = struct.unpack_from("<I", payload, 0)[0]
        elif response == Response.CURRENT_GRINDER:
            # Same LE u32 grind-size value as GRINDER_SIZE (identical -30
            # offset), but fires in contexts our own brew flow doesn't
            # otherwise trigger (standalone Grinder screen, calibration).
            # Also the calibration-done signal: the official app treats
            # value == 85 as "calibration complete" while a calibration is
            # in progress — RD_Grinder_Stop is NOT a valid completion
            # signal (fires early, as part of the sweep's own homing move;
            # see project memory xbloom-grinder-calibration-completion-
            # signal-saga).
            if len(payload) >= 4:
                raw = struct.unpack_from("<I", payload, 0)[0]
                st.grinder.size = max(raw - _GRIND_SIZE_RAW_OFFSET, 1)
                if st.is_calibrating_grinder and raw == _GRINDER_CALIBRATION_DONE_RAW:
                    st.is_calibrating_grinder = False
                    self._fire_event("notification", "grinder_calibration_complete")
        elif response == Response.CALIBRATE_START:
            # Best-effort only: at least one real unit never sends this —
            # async_calibrate_grinder() already sets the flag at send time.
            st.is_calibrating_grinder = True
        elif response == Response.MACHINE_SLEEPING:
            st.is_sleeping = True
        elif response in (Response.MACHINE_NOT_SLEEPING, Response.MACHINE_ACTIVITY):
            st.is_sleeping = False
        elif response == Response.BREWER_MODE:
            if len(payload) >= 4:
                raw = struct.unpack_from("<I", payload, 0)[0]
                if raw in _VALID_POUR_PATTERNS:
                    st.pour_pattern_live = raw
        elif response == Response.UNIT_CHANGE:
            # Machine-initiated display-units/water-source sync (e.g. the
            # user changed them on the touchscreen). Payload: 3 LE u32s —
            # weight unit, temp unit, water source. Fired as a "settings"
            # event (not "notification") so it reaches the coordinator
            # without surfacing on the notification event entity.
            if len(payload) >= 12:
                weight_raw, temp_raw, water_raw = struct.unpack_from("<3I", payload, 0)
                self._fire_event(
                    "settings", "unit_change",
                    {"weight_unit": weight_raw, "temp_unit": temp_raw, "water_source": water_raw},
                )

        if response == Response.EASYMODE_TYPE:
            # ACK for a mode-switch command (cmd 11511) — the machine
            # echoes the newly-applied mode code back as its payload.
            if len(payload) >= 4:
                st.mode_ack_hex = payload[:4].hex()
                _LOGGER.info("Mode switch ACK: mode=%s", self._machine_mode())

        if response in _NOTIFICATION_MAP:
            event_type = _NOTIFICATION_MAP[response]
            attrs: dict = {}
            if response == Response.BLOOM:
                if len(payload) >= 4:
                    attrs["pour_index"] = struct.unpack_from("<I", payload, 0)[0]
            elif response == Response.PODS:
                # xid is the first 6 raw payload bytes (12 hex chars,
                # hex-decoded to ASCII).
                attrs["xid"] = strict_ascii(payload[:6])
            elif response == Response.EASYMODE_BEGIN:
                if len(payload) >= 4:
                    raw = struct.unpack_from("<I", payload, 0)[0]
                    if 0 <= raw <= 2:
                        attrs["slot"] = chr(ord("A") + raw)
            if event_type in ("grinding_started", "grinding_complete") and st.is_calibrating_grinder:
                # A grinder calibration sweep genuinely stops/restarts the
                # motor several times while searching for the zero
                # position — suppress the generic pair so an automation
                # listening for "my coffee grind finished" doesn't
                # false-trigger mid-calibration. grinder_calibration_* is
                # the dedicated signal for that.
                pass
            else:
                self._fire_event("notification", event_type, attrs)
        elif response == Response.ERROR_LACK_OF_WATER:
            # Bidirectional tank-state notification, not a one-shot error:
            # payload value 0 = empty, 1 = refilled — the firmware sends it
            # again on refill.
            value = struct.unpack_from("<I", payload, 0)[0] if len(payload) >= 4 else 0
            st.water_level_ok = value == 1
            _LOGGER.info(
                "RD_ErrorLackOfWater: value=%d (%s)", value, "restored" if value == 1 else "shortage"
            )
            if value == 1:
                self._fire_event("notification", "water_refilled")
            else:
                self._fire_event("error", "water_shortage")
        elif response in _ERROR_MAP:
            self._fire_event("error", _ERROR_MAP[response])
