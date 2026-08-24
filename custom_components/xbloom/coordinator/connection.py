"""Connection lifecycle, reconnect supervisor, and mode/unit sync.

Part of the coordinator package split (Phase 3, structural only — see
constants.py's module docstring).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from homeassistant.helpers import device_registry as dr

from custom_components.xbloom.ble.client import AckTimeout, XBloomClient, strict_ascii
from custom_components.xbloom.ble.connection import HABleakConnection
from custom_components.xbloom.ble.models import DeviceStatus
from custom_components.xbloom.const import (
    CONF_MODE,
    CONF_TEMP_UNIT,
    CONF_WATER_SOURCE,
    CONF_WEIGHT_UNIT,
    DOMAIN,
)

from .constants import (
    _BLE_SILENCE_TIMEOUT_S,
    _CMD_SWITCH_WATER_FEED,
    _DI_FIRMWARE_UUID,
    _DI_SERIAL_UUID,
    _DI_SOFTWARE_UUID,
    _MACHINE_INFO_RETRY_DELAYS_S,
    _MODE_SWITCH_ACK_TIMEOUT_S,
    _MODE_SWITCH_HEX,
    _MODE_SWITCH_MAX_ATTEMPTS,
    _RAW_TO_TEMP_UNIT,
    _RAW_TO_WEIGHT_UNIT,
    _RECONNECT_BACKOFF_BASE_S,
    _RECONNECT_BACKOFF_MAX_S,
    _WAKE_RETRY_DELAY_S,
    _WAKE_RETRY_MAX_ATTEMPTS,
    TEMP_UNIT_OPTIONS,
    WATER_SOURCE_DIRECT,
    WATER_SOURCE_TANK,
    WEIGHT_UNIT_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# Option keys backing a machine settings command, in send order — one
# command each (see _apply_unit_preferences/_unit_push_command). Only the
# keys the user actually changed are ever sent.
_UNIT_PUSH_ORDER = (CONF_WEIGHT_UNIT, CONF_TEMP_UNIT, CONF_WATER_SOURCE)


class ConnectionMixin:
    """Connect/disconnect, reconnect supervisor, mode switching, unit sync."""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _maybe_schedule_reconnect(self) -> None:
        """Reconnect backstop for the supervisor poll (state.py's
        ``_async_update_data``).

        ``_handle_unexpected_disconnect`` only fires once per BLE-level drop
        event and gives up silently if that one attempt fails (e.g. the
        adapter is briefly busy). This runs on every poll tick instead, so a
        failed attempt just gets retried on the next tick — matching the
        official app's AppDeviceManager poll loop, which keeps calling
        connect() every tick as long as the device isn't connected or
        already connecting. Session-only: skipped after a user-initiated
        disconnect (``_manual_disconnect``), and skipped while a connect
        attempt is already in flight (``_connect_lock``) to avoid piling up
        redundant tasks.

        Also skipped while in idle standby (``_idle_disconnected``, see
        that flag in ``__init__.py``) — that link was dropped deliberately
        and stays down until an action needs it again, which is the whole
        point of the timeout.

        Backs off exponentially after consecutive failures so a machine
        that is simply off or out of range doesn't have us retrying (and
        logging) every tick indefinitely. Only this backstop is gated —
        ``_async_ensure_connected()`` still connects on demand, so a user
        action never waits out the backoff.
        """
        if self._manual_disconnect or self._idle_disconnected:
            return
        if self._connect_lock.locked():
            return
        if time.monotonic() < self._reconnect_blocked_until:
            return
        _LOGGER.debug("XBloom not connected — reconnect supervisor retrying")
        self.hass.async_create_task(self.async_connect())

    def _note_connect_failure(self) -> int:
        """Record a failed connect and arm the supervisor's backoff.

        Returns the consecutive-failure count so the caller can log the
        first failure loudly and the rest quietly.
        """
        self._reconnect_failures += 1
        delay = min(
            _RECONNECT_BACKOFF_BASE_S * (2 ** (self._reconnect_failures - 1)),
            _RECONNECT_BACKOFF_MAX_S,
        )
        self._reconnect_blocked_until = time.monotonic() + delay
        return self._reconnect_failures

    def _note_connect_success(self) -> None:
        self._reconnect_failures = 0
        self._reconnect_blocked_until = 0.0

    async def _async_drop_stale_link(self) -> None:
        """Tear down a link that has gone silent, and let the supervisor
        pick it back up on a later poll tick.

        Triggered when the BLE GATT link still reports connected but no
        notification has arrived in over ``_BLE_SILENCE_TIMEOUT_S`` — the
        telemetry stream floods at multi-Hz under normal operation, so a gap
        this large means the link is wedged, not just quiet. Goes through
        ``async_disconnect()`` for proper teardown (cancels the MachineInfo
        retry task, etc.), then immediately clears ``_manual_disconnect``
        again so this doesn't look like a user-requested disconnect to the
        reconnect supervisor above or to ``_handle_unexpected_disconnect``.

        Deliberately does NOT reconnect inline (it did until 2026-07-19).
        The official app's equivalent — AppDeviceManager's "heart check",
        which arms a ``disconnect(true)`` 2s after every 5s tick and cancels
        it from ``onCharacteristicChanged`` — only ever disconnects, and
        leaves reconnecting to the next tick of its ordinary poll loop
        (decompiled 2026-07-19, see project memory). Reconnecting inline
        here made a machine that stops talking (asleep, or wedged) get
        hammered with back-to-back connect cycles for as long as it stayed
        quiet; the supervisor's own 5s cadence is the app's cadence.
        """
        _LOGGER.warning(
            "No BLE notification in over %.0fs — link looks stale, dropping it",
            _BLE_SILENCE_TIMEOUT_S,
        )
        try:
            await self.async_disconnect()
            self._manual_disconnect = False
        finally:
            self._force_reconnect_pending = False

    async def _async_enter_idle_standby(self) -> None:
        """Drop the link after ``_session_timeout`` seconds of doing nothing.

        Mirrors the official app's actual connection lifetime rather than
        its reconnect logic: AppDeviceManager's supervise-and-reconnect
        loop is skipped entirely while the app is backgrounded, so the
        vendor's own client simply does not hold an unattended link
        (decompiled 2026-07-19, see project memory). Holding one 24/7 is
        what this integration used to do, and a machine left connected
        overnight locked up hard enough to need a power cycle.

        ``_idle_disconnected`` keeps the reconnect supervisor off until
        something actually wants the machine — see
        ``_async_ensure_connected()``, which every coordinator action goes
        through, and the connection switch, which clears the flag directly.
        """
        _LOGGER.info(
            "Idle for over %ds — disconnecting until the next action "
            "(set the idle disconnect timeout to 0 to stay connected)",
            self._session_timeout,
        )
        self._idle_disconnected = True
        try:
            await self.async_disconnect()
        finally:
            self._idle_standby_pending = False

    def _maybe_update_device_registry(self, data: dict[str, Any]) -> None:
        """Push updated serial/firmware version to the HA device registry."""
        serial = data.get("serial_number", "")
        version = data.get("version", "")

        if serial == self._last_serial and version == self._last_version:
            return  # nothing changed

        self._last_serial = serial
        self._last_version = version

        if not serial and not version:
            return  # nothing useful to push yet

        try:
            registry = dr.async_get(self.hass)
            device = registry.async_get_device(identifiers={(DOMAIN, self.entry_id)})
            if device is not None:
                updates: dict[str, Any] = {}
                if serial and device.serial_number != serial:
                    updates["serial_number"] = serial
                if version and device.sw_version != version:
                    updates["sw_version"] = version
                if updates:
                    registry.async_update_device(device.id, **updates)
                    _LOGGER.info("Device registry updated: %s", updates)
        except Exception as exc:
            _LOGGER.debug("Device registry update failed: %s", exc)

    async def async_connect(self) -> bool:
        """Establish a BLE connection. Safe to call when already connected.

        Uses a local ``client`` variable throughout its body instead of
        repeatedly re-reading ``self.client`` — hardware-reported
        2026-07-17: ``_handle_unexpected_disconnect()`` (bleak's
        ``disconnected_callback``, fired independently of
        ``_connect_lock``) sets ``self.client = None`` the instant a
        disconnect happens, including one that fires again on this very
        connection shortly after it succeeds (a brief real flap, or the
        original drop's callback landing late). That raced an in-flight
        ``async_connect()`` call already past ``connect()`` — one still
        using ``self.client`` for the follow-up steps below — crashing
        with ``'NoneType' object has no attribute ...`` instead of a
        proper "not connected" BLE error. The local variable can't be
        raced out from under this call; ``self.client`` is restored at
        the very end so the common (no-race) case is unaffected, and if a
        genuine reconnect got scheduled concurrently, it'll find
        ``client.is_connected`` false and replace it properly once this
        call releases the lock.
        """
        async with self._connect_lock:
            if self.client and self.client.is_connected:
                return True

            _LOGGER.info("Connecting to XBloom at %s …", self.mac_address)
            self._manual_disconnect = False
            # Whatever the reason for connecting, we are no longer in idle
            # standby, and the idle countdown starts fresh from here.
            self._idle_disconnected = False
            self._note_activity()
            try:
                client = XBloomClient(
                    mac_address=self.mac_address,
                    connection=HABleakConnection(
                        self.hass, disconnected_callback=self._handle_unexpected_disconnect
                    ),
                )
                self.client = client
                client._cleanup_on_disconnect = False

                # Propagate BLE notifications → coordinator refresh
                def _on_status(_status: DeviceStatus) -> None:
                    if self.hass:
                        self.hass.loop.call_soon_threadsafe(
                            lambda: self.hass.async_create_task(self.async_refresh())
                        )

                client.on_status_update(_on_status)
                client.on_event(self._dispatch_event)

                connected = await client.connect(timeout=20.0)
                if connected:
                    self._note_connect_success()
                    _LOGGER.info("XBloom connected ✓")
                    await self._log_gatt_inventory()
                    # Only push settings a user actually changed that
                    # couldn't reach the machine while disconnected — see
                    # _pending_unit_pushes' docstring in __init__.py.
                    # Otherwise this stays passive, like the official app:
                    # the machine's own value flows back to HA via cmd 8015
                    # (_async_sync_units_from_machine) instead of being
                    # overwritten on every reconnect.
                    if self._pending_unit_pushes:
                        await self._apply_unit_preferences(client)
                    await self.async_refresh()
                    self._schedule_machine_info_retry()
                    # Only fire the advanced-settings GET once the machine is
                    # confirmed awake (serial_number populated means
                    # RD_MachineInfo already arrived, i.e. the 8100 handshake
                    # actually landed) — see the docstring on
                    # _async_refresh_advanced_settings for why firing it
                    # unconditionally here silently loses the response on
                    # firmwares that need a handshake retry (hardware-
                    # confirmed 2026-07-17). If MachineInfo hasn't arrived
                    # yet, _machine_info_retry_loop fires this once it does.
                    if self.hass and client.status.serial_number:
                        self.hass.async_create_task(
                            self._async_refresh_advanced_settings(client)
                        )
                    self.client = client
                    return True

                self._log_connect_failure("XBloom connect returned False")
                self.client = None
                return False

            except Exception as exc:
                self._log_connect_failure("XBloom connection error: %s", exc)
                self.client = None
                return False

    def _log_connect_failure(self, msg: str, *args: Any) -> None:
        """Log a failed connect loudly once, then quietly while it persists.

        A machine that is off or out of range would otherwise emit an ERROR
        on every supervisor tick for as long as it stays away.
        """
        failures = self._note_connect_failure()
        if failures == 1:
            _LOGGER.error(msg, *args)
        else:
            _LOGGER.debug(
                "%s (consecutive failure %d; next supervisor retry in ≤%.0fs)",
                msg % args if args else msg,
                failures,
                max(0.0, self._reconnect_blocked_until - time.monotonic()),
            )

    async def async_disconnect(self) -> None:
        """Disconnect from the BLE device."""
        self._manual_disconnect = True
        if self._machine_info_task and not self._machine_info_task.done():
            self._machine_info_task.cancel()
        self._machine_info_task = None
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as exc:
                _LOGGER.warning("Error during disconnect: %s", exc)
            finally:
                self.client = None
        await self.async_refresh()

    def _handle_unexpected_disconnect(self) -> None:
        """Note that the machine dropped the BLE link on its own, and let
        the reconnect supervisor pick it back up on its next poll tick.

        Live-observed 2026-07-04: the machine briefly drops the link when
        switching Easy<->Pro mode, and this integration had no watchdog for
        that — the connection switch entity just stayed "off" until the
        user flipped it back on manually. Skipped when the drop was caused
        by our own ``async_disconnect()`` (``_manual_disconnect``), so
        turning the connection switch off doesn't immediately reconnect.

        Deliberately does NOT reconnect inline (it did until 2026-08-24),
        for the same reason ``_async_drop_stale_link`` stopped doing so on
        2026-07-19: the official app's supervisor reconnects at most once
        per 5s tick, and this was the last path still racing back in
        milliseconds. That mattered in practice — hardware-measured
        2026-08-24, the machine re-advertises 1.0-1.9s after a disconnect
        and another central can take it 2.0-3.0s after, but a phone needs
        the user to open the app and scan first. Reconnecting instantly
        meant HA won that window every time, so "the machine dropped HA to
        give the phone its slot" turned into HA snatching it straight back
        and the phone never connecting. The supervisor runs on the poll
        tick (the telemetry interval, 5s by default), which leaves a wide
        enough handover window; a user action doesn't wait for it either
        way, since those go through ``_async_ensure_connected()``.
        """
        if self._manual_disconnect:
            return
        _LOGGER.warning(
            "XBloom BLE link dropped unexpectedly — the reconnect supervisor "
            "will pick it up on the next poll tick"
        )
        if self._machine_info_task and not self._machine_info_task.done():
            self._machine_info_task.cancel()
        self._machine_info_task = None
        self.client = None

    def _schedule_machine_info_retry(self) -> None:
        """Kick off a background retry task to populate MachineInfo if missing.

        XBloom firmware pushes RD_MachineInfo as a notification triggered by
        certain commands. The xbloom client waits briefly after connect, but
        the notification sometimes arrives later (or not at all on a session).
        This task re-sends APP_RECIPE_STOP — the same trigger _reset_state()
        uses — at increasing intervals until serial/version are populated.

        The retry only fires while the machine reports a safe (non-brewing)
        state so we don't interrupt an active recipe.
        """
        if self._machine_info_task and not self._machine_info_task.done():
            return
        if self.client and self.client.status.serial_number:
            return  # already have it
        self._machine_info_task = self.hass.async_create_task(
            self._machine_info_retry_loop()
        )

    async def _machine_info_retry_loop(self) -> None:
        _LOGGER.info(
            "MachineInfo retry loop started — schedule=%s",
            _MACHINE_INFO_RETRY_DELAYS_S,
        )
        for attempt, delay in enumerate(_MACHINE_INFO_RETRY_DELAYS_S, start=1):
            await asyncio.sleep(delay)
            if not self.client or not self.client.is_connected:
                _LOGGER.info("MachineInfo retry aborted — client disconnected")
                return
            if self.client.status.serial_number:
                _LOGGER.info(
                    "MachineInfo arrived after %d attempt(s): serial=%r version=%r",
                    attempt - 1,
                    self.client.status.serial_number,
                    self.client.status.version,
                )
                await self.async_refresh()
                if self.hass:
                    self.hass.async_create_task(self._async_refresh_advanced_settings())
                return

            _LOGGER.info(
                "MachineInfo attempt %d/%d (after %.1fs) — "
                "current cache: serial=%r version=%r",
                attempt, len(_MACHINE_INFO_RETRY_DELAYS_S), delay,
                self.client.status.serial_number,
                self.client.status.version,
            )

            # First attempt: read the standard GATT Device Information chars
            # directly. Some firmwares populate these but never push the
            # proprietary RD_MachineInfo notification.
            if await self._try_read_device_info_chars():
                _LOGGER.info(
                    "MachineInfo populated via GATT 180A: serial=%r version=%r",
                    self.client.status.serial_number,
                    self.client.status.version,
                )
                await self.async_refresh()
                if self.hass:
                    self.hass.async_create_task(self._async_refresh_advanced_settings())
                return

            # Re-send the 8100 MTU handshake — per the upstream xbloom-ble's PROTOCOL.md
            # this is what actually triggers RD_MachineInfo on the wire.
            # APP_RECIPE_STOP (used previously) does not provoke it; brAzzi64's
            # connect() retries the handshake when MachineInfo doesn't arrive.
            # The handshake is also safe to send while brewing — no side
            # effects on machine state — so the safe-state gate is gone.
            try:
                _LOGGER.info(
                    "Re-sending 8100 handshake to retrigger MachineInfo (attempt %d)",
                    attempt,
                )
                await self.client.async_send_handshake()
            except Exception as exc:
                _LOGGER.warning("Handshake retry failed: %s", exc)

        if self.client and not self.client.status.serial_number:
            _LOGGER.warning(
                "MachineInfo never received from XBloom after %d retries — "
                "serial/firmware sensors will remain 'unknown'. "
                "Final cache: serial=%r version=%r",
                len(_MACHINE_INFO_RETRY_DELAYS_S),
                self.client.status.serial_number,
                self.client.status.version,
            )

    async def _try_read_device_info_chars(self) -> bool:
        """Read GATT 180A characteristics directly to populate MachineInfo.

        The vendored xbloom.connection.BleakConnection doesn't expose a
        read_gatt_char helper, so we reach through to its underlying bleak
        BleakClient. Returns True once serial_number is populated so the
        caller can stop the retry loop.
        """
        if not self.client or not self.client.is_connected:
            _LOGGER.debug("180A read skipped — not connected")
            return False
        connection = getattr(self.client, "_connection", None)
        bleak_client = getattr(connection, "_client", None)
        if bleak_client is None or not hasattr(bleak_client, "read_gatt_char"):
            _LOGGER.warning(
                "180A read unavailable — no bleak client on connection (%r)",
                connection,
            )
            return False

        status = self.client._status
        # Probe Serial / Firmware Rev plus the SW Rev fallback. Model
        # chars (2A24 / 2A27 / 2A29) are skipped — the firmware leaves
        # them blank on every observed unit and we no longer surface a
        # model entity.
        targets = (
            (_DI_SERIAL_UUID, "serial_number"),
            (_DI_FIRMWARE_UUID, "version"),
            (_DI_SOFTWARE_UUID, "version"),
        )
        for uuid, attr in targets:
            if getattr(status, attr, ""):
                _LOGGER.debug("180A %s skipped — already cached: %r",
                              attr, getattr(status, attr))
                continue
            try:
                raw = await bleak_client.read_gatt_char(uuid)
            except Exception as exc:
                _LOGGER.info(
                    "180A read %s (%s) failed: %s: %s",
                    attr, uuid, type(exc).__name__, exc,
                )
                continue
            raw_bytes = bytes(raw) if raw else b""
            _LOGGER.info(
                "180A read %s (%s) → %d bytes %s",
                attr, uuid, len(raw_bytes), raw_bytes.hex() or "(empty)",
            )
            if not raw_bytes:
                continue
            text = strict_ascii(raw_bytes)
            if text:
                setattr(status, attr, text)
                _LOGGER.info("180A %s populated: %r", attr, text)
            else:
                _LOGGER.info(
                    "180A %s decoded empty after strict-ASCII filter (raw=%s)",
                    attr, raw_bytes.hex(),
                )

        # Partial population (e.g. version without serial) is still useful,
        # so report success when either is now non-empty.
        return bool(status.serial_number or status.version)

    async def _log_gatt_inventory(self) -> None:
        """One-shot dump of every GATT service & characteristic after connect.

        Helps diagnose whether the firmware exposes the standard 180A Device
        Information service, custom XBloom service, and which chars carry
        notify/read properties — drives the MachineInfo recovery strategy.
        """
        if not self.client or not self.client.is_connected:
            return
        connection = getattr(self.client, "_connection", None)
        bleak_client = getattr(connection, "_client", None)
        services = getattr(bleak_client, "services", None)
        if not services:
            _LOGGER.warning("GATT inventory unavailable (services=%r)", services)
            return
        try:
            for service in services:
                _LOGGER.info("GATT service %s", service.uuid)
                for char in service.characteristics:
                    _LOGGER.info(
                        "  char %s props=%s",
                        char.uuid, ",".join(char.properties),
                    )
        except Exception as exc:
            _LOGGER.warning("GATT inventory walk failed: %s", exc)

    # ------------------------------------------------------------------
    # Display units / water source
    # ------------------------------------------------------------------

    async def _apply_unit_preferences(self, client: XBloomClient | None = None) -> None:
        """Push the pending unit/water-source SET commands to the machine.

        Only the settings the user actually changed go out —
        ``_pending_unit_pushes`` holds their option keys, and each key
        maps to exactly one command (8005 weight unit, 8010 temp unit,
        4508 water feed). Hardware-reported 2026-08-24: pushing all three
        on every change dropped the machine into its own settings wizard
        at the *weight-unit* page ("mL first"), forcing the user to walk
        through every setting again — receiving one of these SETs is
        indistinguishable to the firmware from a tap on that page's own
        button (see ``_pending_unit_pushes`` in __init__.py), so a
        water-source change must not send the two unit commands too.

        Each send is ACK-gated (``send_and_wait``) instead of fired
        back-to-back: the same capture showed all three leaving within
        5 ms of each other and only the first one ever being echoed — the
        documented "back-to-back sends can drop the second command" quirk
        (docs/en/protocol.md), which is exactly why the water-source
        change never reached the machine. The official app's own Settings
        buttons go through the same ACK-gated ``sendMessage`` path.
        A timed-out send is retried once, then given up on (with a
        warning) rather than left pending: a key that can never be
        acknowledged would otherwise re-open the machine's settings
        screen on every single connect.

        Never raises; a failure here shouldn't block the rest of
        async_connect(). Keys whose send couldn't even be attempted (the
        link went away mid-sequence) stay pending for the next connect.

        ``client`` lets ``async_connect()`` pass its own local client
        reference instead of this method reading ``self.client`` —
        hardware-reported 2026-07-17: a disconnect racing in mid-connect
        (see ``async_connect()``'s docstring) could null ``self.client``
        out from under this call, crashing with ``'NoneType' object has
        no attribute '_send_command_raw'`` instead of a clean "not
        connected" error. Defaults to ``self.client`` for the other call
        site (``_async_push_unit_preferences``).
        """
        client = client or self.client
        for key in _UNIT_PUSH_ORDER:
            if key not in self._pending_unit_pushes:
                continue
            command, payload, shown = self._unit_push_command(key)
            try:
                await self._async_send_unit_command(client, command, payload)
            except AckTimeout as exc:
                _LOGGER.warning(
                    "Machine never acknowledged %s (%s) — it may not have "
                    "been applied: %s", key, shown, exc,
                )
            except Exception as exc:
                _LOGGER.warning("Failed to apply %s (%s): %s", key, shown, exc)
                return
            else:
                _LOGGER.info("Applied machine setting %s=%s", key, shown)
            # Not in a `finally`: the hard-failure `return` above must
            # leave the key pending for the next connect, while an
            # attempted-but-unacknowledged send is given up on.
            self._pending_unit_pushes.discard(key)

    def _unit_push_command(self, key: str) -> tuple[int, bytes | list, str]:
        """(command id, payload, human-readable value) for one option key."""
        if key == CONF_WEIGHT_UNIT:
            code = WEIGHT_UNIT_OPTIONS.get(self._weight_unit, WEIGHT_UNIT_OPTIONS["g"])
            return 8005, bytes([code]), self._weight_unit
        if key == CONF_TEMP_UNIT:
            code = TEMP_UNIT_OPTIONS.get(self._temp_unit, TEMP_UNIT_OPTIONS["c"])
            return 8010, bytes([code]), self._temp_unit
        return _CMD_SWITCH_WATER_FEED, [self.water_source], str(self.water_source)

    async def _async_send_unit_command(
        self, client: XBloomClient, command: int, payload: bytes | list
    ) -> None:
        """ACK-gated send of one settings command, resent once on timeout."""
        kwargs: dict[str, Any] = (
            {"raw": payload} if isinstance(payload, bytes) else {"data": payload}
        )
        try:
            await client.send_and_wait(command, type_code=1, **kwargs)
        except AckTimeout:
            _LOGGER.info(
                "No ACK for settings command %s — resending once", command,
            )
            await client.send_and_wait(command, type_code=1, **kwargs)

    def _persist_unit_options(self) -> None:
        """Persist the current unit/water-source values to entry.options.

        All three keys are in __init__.py's _NO_RELOAD_OPTION_KEYS, so
        this never reloads the entry (and therefore never drops the BLE
        connection). No-op if the options already match.
        """
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        new_options = {
            **entry.options,
            CONF_WATER_SOURCE: self.water_source,
            CONF_WEIGHT_UNIT: self._weight_unit,
            CONF_TEMP_UNIT: self._temp_unit,
        }
        if new_options != dict(entry.options):
            self.hass.config_entries.async_update_entry(entry, options=new_options)

    async def _async_sync_units_from_machine(self, attrs: dict) -> None:
        """Fold a machine-reported unit/water-source change (cmd 8015,
        RD_UNIT_CHANGE — fired when they're changed on the machine's own
        touchscreen) back into the stored preferences, so HA's own display
        matches what the machine actually shows instead of a stale value.
        This is a machine-wins sync (never adds to _pending_unit_pushes) —
        the machine is the source of truth here, there's nothing to push
        back to it. The one exception is a setting with an outstanding
        push of our own (_pending_unit_pushes): the machine reports its
        *pre-change* value in the 8015 that arrives during the connect
        handshake, so adopting it there would silently revert the change
        the user just made in the Settings step. Skipped per key, so an
        unrelated machine-side change still syncs while one setting waits
        to be delivered.
        """
        pending = self._pending_unit_pushes
        if pending:
            _LOGGER.debug(
                "Ignoring the machine's own %s report — a Settings-step "
                "change is still pending delivery to the machine",
                ", ".join(sorted(pending)),
            )
        weight = _RAW_TO_WEIGHT_UNIT.get(attrs.get("weight_unit"))
        temp = _RAW_TO_TEMP_UNIT.get(attrs.get("temp_unit"))
        water = attrs.get("water_source")
        changed = False
        if (
            weight is not None
            and weight != self._weight_unit
            and CONF_WEIGHT_UNIT not in pending
        ):
            self._weight_unit = weight
            changed = True
        if (
            temp is not None
            and temp != self._temp_unit
            and CONF_TEMP_UNIT not in pending
        ):
            self._temp_unit = temp
            changed = True
        if (
            water in (WATER_SOURCE_TANK, WATER_SOURCE_DIRECT)
            and water != self.water_source
            and CONF_WATER_SOURCE not in pending
        ):
            self.water_source = water
            changed = True
        if changed:
            _LOGGER.info(
                "Machine-side unit change synced: weight=%s temp=%s water_source=%d",
                self._weight_unit, self._temp_unit, self.water_source,
            )
            self._persist_unit_options()
            self.async_update_listeners()

    def _handle_unit_options_change(self, options: dict) -> None:
        """React to a unit/water-source change in entry.options (called by
        __init__.py's update listener on its no-reload path, i.e. after the
        config flow's Settings step edits them).

        When the options match the coordinator's current values this is an
        echo of our own _persist_unit_options() (an 8015 sync, or this same
        method having just applied a change) — nothing to apply. Otherwise
        adopt the new values and push them to the machine right away (this
        is the explicit-user-action case the official app's own
        Settings-screen button taps mirror), reconnecting first if the
        link is down — with idle standby (_session_timeout) that is the
        normal state between uses, so deferring the push to "whenever
        something else happens to connect" left a water-source change
        unapplied indefinitely. A key stays in _pending_unit_pushes until
        its own send actually lands, so async_connect() covers the case
        where the reconnect fails (see that set's docstring for why the
        push isn't unconditional on every connect).

        Only the keys whose value really changed are queued: sending the
        unit commands as well would re-open the machine's unit wizard for
        a plain water-source change (hardware-reported 2026-08-24, see
        _apply_unit_preferences).
        """
        weight = options.get(CONF_WEIGHT_UNIT, self._weight_unit)
        temp = options.get(CONF_TEMP_UNIT, self._temp_unit)
        water = options.get(CONF_WATER_SOURCE, self.water_source)
        changed = {
            key
            for key, new_value, current in (
                (CONF_WEIGHT_UNIT, weight, self._weight_unit),
                (CONF_TEMP_UNIT, temp, self._temp_unit),
                (CONF_WATER_SOURCE, water, self.water_source),
            )
            if new_value != current
        }
        if not changed:
            return
        self._weight_unit = weight
        self._temp_unit = temp
        self.water_source = water
        self._pending_unit_pushes |= changed
        self.hass.async_create_task(self._async_push_unit_preferences())

    async def _async_push_unit_preferences(self) -> None:
        """Connect if needed, then push the pending unit/water-source values.

        Leaves _pending_unit_pushes populated if the machine can't be
        reached (off, out of range, or the connection switch turned off),
        so async_connect() picks the change up on the next successful
        connect.
        """
        try:
            await self._async_ensure_connected()
        except Exception as exc:
            _LOGGER.warning(
                "Display unit preferences not applied yet (%s) — will push "
                "on the next connection", exc,
            )
            return
        if not self._pending_unit_pushes:
            return  # async_connect() pushed them on the way in
        await self._apply_unit_preferences()

    # ------------------------------------------------------------------
    # Mode switching (Pro / Easy)
    # ------------------------------------------------------------------

    async def _async_switch_mode_with_retry(self, mode: str) -> bool:
        """Send the mode-switch command (11511) and confirm it landed via
        its ACK (``mode_ack_hex``), retrying on timeout.

        Matches the official app's own retry spec (see
        ``_MODE_SWITCH_ACK_TIMEOUT_S``/``_MODE_SWITCH_MAX_ATTEMPTS``'s
        module comment) rather than a blind fixed delay — the previous
        ``await asyncio.sleep(0.5)`` before every mode-switch call site
        had no way to tell whether the switch actually took effect.
        Returns ``True`` once the ACK confirms the target mode, ``False``
        if every attempt timed out (the command was still sent each
        time — this only affects whether we know it worked).

        Retries only continue while the machine last reported itself
        asleep (``client.is_sleeping()``) — matching the official app,
        which gives up after a single timeout when the machine is awake.
        """
        target_hex = _MODE_SWITCH_HEX[mode]
        mode_bytes = bytes.fromhex(target_hex)
        for attempt in range(1, _MODE_SWITCH_MAX_ATTEMPTS + 1):
            await self.client._send_command_raw(11511, mode_bytes, type_code=2)
            for _ in range(int(_MODE_SWITCH_ACK_TIMEOUT_S / 0.1)):
                await asyncio.sleep(0.1)
                if self.client.status.mode_ack_hex == target_hex:
                    _LOGGER.info(
                        "Mode switch to %s confirmed (attempt %d/%d)",
                        mode, attempt, _MODE_SWITCH_MAX_ATTEMPTS,
                    )
                    return True
            _LOGGER.info(
                "Mode switch to %s: no ACK after %.1fs (attempt %d/%d)",
                mode, _MODE_SWITCH_ACK_TIMEOUT_S, attempt, _MODE_SWITCH_MAX_ATTEMPTS,
            )
            if not self.client.is_sleeping():
                _LOGGER.info(
                    "Mode switch to %s: machine not asleep — matching official "
                    "app, no retry",
                    mode,
                )
                break
        _LOGGER.warning(
            "Mode switch to %s: no ACK after %d attempts — proceeding without confirmation",
            mode, _MODE_SWITCH_MAX_ATTEMPTS,
        )
        return False

    async def async_set_mode(self, mode: str) -> None:
        """Switch the machine's operating mode.

        ``mode`` must be ``pro`` or ``easy``.  Sends command 11511 with the
        appropriate mode code (type-2 packet) and waits for its ACK,
        retrying on timeout — see ``_async_switch_mode_with_retry``.

        The choice is persisted in ``entry.options`` so it survives HA
        restarts and is reapplied on the next connection.
        """
        if not await self._async_ensure_connected():
            return
        mode = mode.strip().lower()
        if mode not in ("pro", "easy"):
            raise ValueError(f"mode must be 'pro' or 'easy', got {mode!r}")
        try:
            confirmed = await self._async_switch_mode_with_retry(mode)
            _LOGGER.info("Mode switch requested: %s (confirmed=%s)", mode, confirmed)
            # Persist so the choice survives HA restarts, even if we
            # couldn't confirm the switch — this is the user's stated
            # preference regardless of whether we could verify it landed.
            self._mode = mode
            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if entry is not None:
                new_options = {**entry.options, CONF_MODE: mode}
                self.hass.config_entries.async_update_entry(entry, options=new_options)
            await self.async_refresh()
        except Exception as exc:
            _LOGGER.error("Mode switch error (%s): %s", mode, exc)

    # NOTE: there is deliberately no Easy→Pro auto-switch before brew
    # operations. An earlier `_ensure_pro_mode` (+ post-brew Easy restore)
    # existed on the belief that Easy Mode silently ignores the Pro brew
    # commands ("hot water only, grinder never runs") — hardware-refuted
    # 2026-07-19: recipe execution AND manual grind both run fine with the
    # machine in Easy Mode, and the official app sends its brew chain with
    # no mode gate. The original symptom was the ratio-footer grind-gate
    # bug. The one real Pro requirement left is the Easy-slot batch write,
    # which handles its own switch (see recipes.async_write_easy_slots).

    async def _async_retry_while_sleeping(
        self, action: Callable[[], Awaitable[_T]]
    ) -> _T:
        """Run ``action()``, retrying it while the machine reports itself
        asleep — the general form of ``_async_switch_mode_with_retry``'s
        pattern, for every other user-triggered action (grind/pour/tare/
        calibrate/execute recipe/easy-slot write).

        Decompiled 2026-07-17/18: the official app's ``AppBleManager.
        sendMessage``/``createDisposable`` wraps *every* command it sends
        in this exact retry — a 1.5s ACK timeout (``DefaultTimeOut``, the
        same value ``_MODE_SWITCH_ACK_TIMEOUT_S`` uses), and on timeout,
        if the machine was asleep at that moment, resend the identical
        command (up to 3 retries, 4 total sends); the instant it's not
        sleeping, stop — a non-sleep failure won't be fixed by resending.
        This integration had only implemented that pattern for the
        mode-switch command; every other action was a single blind send
        with no retry at all, so hardware-reported 2026-07-17: operating
        the machine while it was asleep silently did nothing.

        Unlike the mode-switch retry, this has no per-command ACK to wait
        on — our writes are write-without-response, and most commands
        here (unlike mode-switch's ``mode_ack_hex``) have no dedicated
        confirmation notification — so it can't verify the retried send
        actually landed. ``is_sleeping()`` after the wait is the same
        signal the app itself gates its own retry on, so it's used
        directly as the retry condition instead of a true per-command
        timeout. Safe to retry blindly on that condition: while the
        machine is confirmed still asleep, its application layer isn't
        processing incoming commands at all (the same "ignores everything
        until awake" behavior the 8100 handshake gate exhibits at
        connect), so a still-sleeping resend is very unlikely to double-
        fire whatever the first send was.

        Returns the last call's return value (2026-07-18, added for the
        two-stage arm/confirm recipe flow — ``async_arm_recipe`` needs the
        built tea payload back from ``brewing.async_arm_recipe`` so
        ``async_confirm_recipe`` can re-send those exact bytes for 4512).
        Every pre-existing caller ignores the return value, so this is
        backward compatible.
        """
        result: _T = None  # type: ignore[assignment]
        for attempt in range(1, _WAKE_RETRY_MAX_ATTEMPTS + 1):
            result = await action()
            if not (self.client and self.client.is_sleeping()):
                return result
            if attempt < _WAKE_RETRY_MAX_ATTEMPTS:
                _LOGGER.info(
                    "Action sent while machine reports asleep — retrying "
                    "(attempt %d/%d)", attempt, _WAKE_RETRY_MAX_ATTEMPTS,
                )
                await asyncio.sleep(_WAKE_RETRY_DELAY_S)
        return result
