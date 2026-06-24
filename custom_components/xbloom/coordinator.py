"""XBloom DataUpdateCoordinator — manages BLE lifecycle and state."""
from __future__ import annotations

import asyncio
import logging
import struct
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_WATER_SOURCE
from ._client import XBloomClientWithEvents as XBloomClient, strict_ascii
from . import brewing
from xbloom.models.types import (
    CupType,
    PourPattern,
    PourStep,
    VibrationPattern,
    XBloomRecipe,
)
_YAML_CUP_TYPE_MAP = {
    "x_pod": int(CupType.X_POD),
    "xpod": int(CupType.X_POD),
    "omni_dripper": int(CupType.OMNI_DRIPPER),
    "other": int(CupType.OTHER),
    "tea": int(CupType.TEA),
}

_YAML_VIBRATION_MAP = {
    "none": VibrationPattern.NONE,
    "before": VibrationPattern.BEFORE,
    "after": VibrationPattern.AFTER,
    "both": VibrationPattern.BOTH,
}


def _build_recipe_from_yaml(raw: dict) -> XBloomRecipe:
    """Build an XBloomRecipe from a validated YAML recipe dict.

    Bypasses xbloom.models.recipes.parse_recipe_json because that helper
    expects the upstream JSON shape (camelCase keys, `dose`, `cupType`)
    and treats `grind_size: 0` / `bean_weight: 0` as missing via `or`,
    silently substituting defaults — which routes tea recipes (no grind,
    no beans) into the coffee brew path.
    """
    cup_raw = raw.get("cup_type", 0)
    if isinstance(cup_raw, str):
        cup_val = _YAML_CUP_TYPE_MAP.get(cup_raw.strip().lower(), 0)
    else:
        cup_val = int(cup_raw)

    pours: List[PourStep] = []
    for p in raw.get("pours", []):
        vib_raw = p.get("vibration", "none")
        vib = (
            _YAML_VIBRATION_MAP.get(vib_raw.strip().lower(), VibrationPattern.NONE)
            if isinstance(vib_raw, str)
            else VibrationPattern(int(vib_raw))
        )
        pours.append(
            PourStep(
                volume=int(p["volume"]),
                temperature=int(p["temperature"]),
                flow_rate=float(p.get("flow_rate", 3.0)),
                pausing=int(p.get("pausing", 0)),
                pattern=PourPattern(int(p.get("pattern", 2))),
                vibration=vib,
            )
        )

    total_water = int(raw.get("total_water", 0))
    # If the YAML omits total_water, derive it from the pour volumes so the
    # recipe footer carries a meaningful value.  A zero footer byte 2 causes
    # the machine to skip grinding (hot water only) on Easy Mode slots and
    # may also confuse live brew.
    if total_water == 0:
        total_water = sum(int(p.get("volume", 0)) for p in raw.get("pours", []))

    return XBloomRecipe(
        grind_size=int(raw.get("grind_size", 0)),
        total_water=total_water,
        rpm=int(raw.get("rpm", 80)),
        cup_type=cup_val,
        name=str(raw.get("name", "Unknown")),
        bean_weight=float(raw.get("bean_weight", 0.0)),
        pours=pours,
    )

_MACHINE_INFO_RETRY_DELAYS_S = (3.0, 5.0, 10.0, 20.0, 30.0)

# Standard GATT Device Information service characteristic UUIDs.
# Some XBloom firmwares only populate MachineInfo via these GATT reads
# rather than the proprietary RD_MachineInfo notification.
# Diagnostic logs showed 2A24/25/26 return 0 bytes on this firmware, so we
# also probe the secondary char 2A28 (SW Rev) which is enumerated as
# readable in the same service. We no longer probe model-related chars
# (2A24 / 2A27 / 2A29) — the firmware leaves theModel blank on every
# observed unit, so the surfaced model entity has been removed.
_DI_SERIAL_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
_DI_FIRMWARE_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
_DI_SOFTWARE_UUID = "00002a28-0000-1000-8000-00805f9b34fb"

_LOGGER = logging.getLogger(__name__)

DEFAULT_STATE: Dict[str, Any] = {
    "connected": False,
    "weight": 0.0,
    "temperature": 0.0,
    "state": "unknown",
    "grinder_running": False,
    "brewer_running": False,
    "water_level_ok": False,
    "version": "",
    "serial_number": "",
    "mode": "pro",
    "error": None,
}

# Water source integer values used in APP_BREWER_START payload.
# NOTE: These only apply to MANUAL POUR (brewer.start / async_pour).
# Recipe execution (APP_RECIPE_EXECUTE) does not accept a water_source
# parameter — the machine controls its own pours internally.
WATER_SOURCE_TANK   = 0   # Built-in tank
WATER_SOURCE_DIRECT = 1   # Direct plumbed line

WATER_SOURCE_OPTIONS = {
    "tank":   WATER_SOURCE_TANK,
    "direct": WATER_SOURCE_DIRECT,
}

# Pour pattern names ↔ ints, shared by the manual-pour select entity and
# the per-pour LLM override. Mirrors schema.py's _PATTERN_NAME_TO_INT and
# PourPattern (0=center, 1=circular, 2=spiral).
POUR_PATTERN_OPTIONS = {"center": 0, "circular": 1, "spiral": 2}


def _apply_pour_overrides(recipe: XBloomRecipe, overrides: List[dict]) -> None:
    """Override individual pours' volume / flow_rate / pattern by index.

    Each entry is a dict with a 0-based ``pour_index`` plus any of
    ``volume`` / ``flow_rate`` / ``pattern`` (pattern as an int 0/1/2).
    Used by the LLM execute tool so an agent can tweak single pours
    without rewriting the saved recipe. Out-of-range indexes are skipped.
    The dataclass validates only at construction, so callers are
    responsible for passing in-range values (the tool schema enforces it).
    """
    for ov in overrides:
        idx = int(ov.get("pour_index", -1))
        if not 0 <= idx < len(recipe.pours):
            continue
        pour = recipe.pours[idx]
        if ov.get("volume") is not None:
            pour.volume = int(ov["volume"])
        if ov.get("flow_rate") is not None:
            pour.flow_rate = float(ov["flow_rate"])
        if ov.get("pattern") is not None:
            pour.pattern = PourPattern(int(ov["pattern"]))


class XBloomCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinate data updates from XBloom via BLE."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac_address: str,
        entry_id: str,
        update_interval: int = 5,
        initial_water_source: int = DEFAULT_WATER_SOURCE,
        initial_mode: str = DEFAULT_MODE,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.mac_address = mac_address
        self.entry_id = entry_id
        self.client: Optional[XBloomClient] = None
        self._connect_lock = asyncio.Lock()
        self._machine_info_task: Optional[asyncio.Task] = None

        # Recipes loaded from YAML config (name → dict)
        self.recipes: Dict[str, dict] = {}
        self.selected_recipe: Optional[str] = None

        # Slider/parameter values stored here; entities read & write these
        self.grind_size: int = 50
        self.rpm: int = 80
        self.temperature: int = 93
        self.volume: int = 200
        self.flow_rate: float = 3.0
        # Pour pattern for MANUAL POUR only (0=center, 1=circular, 2=spiral).
        # Default matches the app's per-pour default (center). Recipe
        # execution uses each pour's own pattern from the YAML.
        self.pour_pattern: int = 0

        # Water source for MANUAL POUR only (0=tank, 1=direct).
        # Loaded from entry.options so it survives HA restarts.
        # Recipe execution (APP_RECIPE_EXECUTE) does NOT use this value.
        self.water_source: int = initial_water_source

        # Machine operating mode ("pro" / "easy").  Persisted in entry.options
        # so the user's preference survives restarts and reconnects.
        # The coordinator applies this mode when it connects to the machine.
        self._mode: str = initial_mode

        # Event entity callbacks registered by event.py entities.
        # List (not set) so ordering is preserved; guarded by _event_lock.
        self._event_listeners: List[Callable[[str, str, dict], None]] = []

        # Track last-known device info so we can update the device registry
        # when MachineInfo notification arrives (possibly well after first setup).
        self._last_serial: str = ""
        self._last_version: str = ""

        # Water shortage is event-driven: firmwares that never emit
        # RD_MachineInfo also leave _status.water_level_ok at the dataclass
        # default (False) forever, which would show a permanent "problem".
        # Instead, default to "no shortage" and flip True only when the
        # machine actually fires RD_ErrorLackOfWater. Cleared by the next
        # successful brew/pour notification.
        self._water_shortage: bool = False

        # Track whether we temporarily switched to Pro Mode for an HA
        # operation.  When the operation completes we switch back to the
        # default (Easy) mode so the physical slot buttons work again.
        self._auto_switched_to_pro: bool = False

    # ------------------------------------------------------------------
    # DataUpdateCoordinator contract
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> Dict[str, Any]:
        """Pull fresh data from the BLE status object (no I/O needed)."""
        if self.client and self.client.is_connected:
            try:
                s = self.client.status
                # water_level_ok is only flipped True inside RD_MachineInfo;
                # on firmwares that never send it, the dataclass default
                # (False) would mean a permanent "problem". Trust the flag
                # only if MachineInfo has actually been observed (proxied by
                # serial_number), otherwise infer from the water_shortage
                # event stream.
                if s.serial_number:
                    water_ok = bool(s.water_level_ok)
                else:
                    water_ok = not self._water_shortage
                data = {
                    "connected": True,
                    "weight": round(s.scale.weight, 1),
                    "temperature": round(s.brewer.temperature, 1),
                    "state": s.state.value,
                    "grinder_running": s.grinder.is_running,
                    "brewer_running": s.brewer.is_running,
                    "water_level_ok": water_ok,
                    "version": s.version,
                    "serial_number": s.serial_number,
                    # Use the machine's reported mode when available;
                    # fall back to the persisted preference before
                    # MachineInfo arrives.
                    "mode": self.client._machine_mode() if s.serial_number else self._mode,
                    "error": None,
                }
                # If MachineInfo arrived since last poll, update the device registry
                # so HA shows the correct serial/firmware version in the device page.
                self._maybe_update_device_registry(data)
                return data
            except Exception as exc:
                _LOGGER.warning("Error reading XBloom status: %s", exc)
                return {**DEFAULT_STATE}
        return {**DEFAULT_STATE}

    def _maybe_update_device_registry(self, data: Dict[str, Any]) -> None:
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
                updates: Dict[str, Any] = {}
                if serial and device.serial_number != serial:
                    updates["serial_number"] = serial
                if version and device.sw_version != version:
                    updates["sw_version"] = version
                if updates:
                    registry.async_update_device(device.id, **updates)
                    _LOGGER.info("Device registry updated: %s", updates)
        except Exception as exc:
            _LOGGER.debug("Device registry update failed: %s", exc)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def async_connect(self) -> bool:
        """Establish a BLE connection. Safe to call when already connected."""
        async with self._connect_lock:
            if self.client and self.client.is_connected:
                return True

            _LOGGER.info("Connecting to XBloom at %s …", self.mac_address)
            try:
                self.client = XBloomClient(mac_address=self.mac_address)
                self.client._cleanup_on_disconnect = False

                # Propagate BLE notifications → coordinator refresh
                def _on_status(_status) -> None:
                    if self.hass:
                        self.hass.loop.call_soon_threadsafe(
                            lambda: self.hass.async_create_task(self.async_refresh())
                        )

                self.client.on_status_update(_on_status)
                self.client.on_event(self._dispatch_event)

                connected = await self.client.connect(timeout=20.0)
                if connected:
                    _LOGGER.info("XBloom connected ✓")
                    await self._log_gatt_inventory()
                    await self.async_refresh()
                    self._schedule_machine_info_retry()
                    return True

                _LOGGER.error("XBloom connect returned False")
                self.client = None
                return False

            except Exception as exc:
                _LOGGER.error("XBloom connection error: %s", exc)
                self.client = None
                return False

    async def async_disconnect(self) -> None:
        """Disconnect from the BLE device."""
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
                return

            # Re-send the 8100 MTU handshake — per src/xbloom-ble/PROTOCOL.md
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
    # Event listener management (used by event.py entities)
    # ------------------------------------------------------------------

    def register_event_listener(self, callback: Callable[[str, str, dict], None]) -> None:
        """Register an entity callback to receive BLE events."""
        if callback not in self._event_listeners:
            self._event_listeners.append(callback)

    def unregister_event_listener(self, callback: Callable[[str, str, dict], None]) -> None:
        """Unregister an entity event callback (safe to call even if not registered)."""
        try:
            self._event_listeners.remove(callback)
        except ValueError:
            pass  # already removed or never registered — harmless

    def _dispatch_event(self, category: str, event_type: str, attributes: dict) -> None:
        """Forward a BLE event to all registered HA event entities.

        This method is called from XBloomClient._fire_event() which runs inside
        the bleak notification handler.  Bleak may invoke the handler from a
        background thread, so we must schedule the actual HA work on the HA
        event loop via call_soon_threadsafe to avoid race conditions.
        """
        _LOGGER.debug("XBloom event [%s] %s %s", category, event_type, attributes)

        # Drive the water-shortage flag from the BLE event stream.
        prev_shortage = self._water_shortage
        if category == "error" and event_type == "water_shortage":
            self._water_shortage = True
        elif category == "notification" and event_type in (
            "brewing_started", "pour_complete", "recipe_complete",
        ):
            # A successful brew implies water is available again.
            self._water_shortage = False
        if prev_shortage != self._water_shortage and self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_refresh())
            )

        # ── Restore Easy Mode after HA-triggered operations finish ──
        # When we auto-switched to Pro for grind/pour/recipe, switch
        # back once the machine reports a completion event so the
        # physical slot buttons work again.
        if self._auto_switched_to_pro and category == "notification" and event_type in (
            "grinding_complete", "pour_complete", "recipe_complete",
        ):
            if self.hass and self.hass.loop:
                self.hass.loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(
                        self._restore_persisted_mode(event_type)
                    )
                )

        def _do_dispatch() -> None:
            # Snapshot the list in case a listener un-registers during iteration
            for cb in list(self._event_listeners):
                try:
                    cb(category, event_type, attributes)
                except Exception as exc:
                    _LOGGER.error("Event listener error: %s", exc)

        if self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(_do_dispatch)
        else:
            # Fallback: already on the right thread or hass not yet set
            _do_dispatch()

    # ------------------------------------------------------------------
    # Actions (called by button entities)
    # ------------------------------------------------------------------

    async def async_pour(self) -> None:
        """Start a manual pour with current slider values."""
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
            await self.client.brewer.start(
                volume=float(self.volume),
                temperature=float(self.temperature),
                flow_rate=self.flow_rate,
                water_source=self.water_source,
                pattern=self.pour_pattern,
            )
        except Exception as exc:
            _LOGGER.error("Pour error: %s", exc)

    async def async_grind(self) -> None:
        """Start grinding with current slider values."""
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
            await self.client.grinder.start(size=self.grind_size, speed=self.rpm)
        except Exception as exc:
            _LOGGER.error("Grind error: %s", exc)

    def select_recipe(self, name: Optional[str]) -> None:
        """Set the active recipe and sync the grind/RPM sliders to it.

        Only coffee recipes that actually grind push their grind_size /
        rpm onto the number entities — tea and no-grind recipes leave the
        sliders untouched (they don't grind, so their values are
        meaningless and would clobber the user's manual-grind settings).
        After syncing, the number entities are the source of truth: the
        user can tweak them and :meth:`async_execute_recipe` will brew
        with the tweaked values. (Bypass is recipe-scoped, not a slider —
        it stays on the YAML value unless overridden per brew.)
        """
        self.selected_recipe = name
        raw = (self.recipes or {}).get(name) if name else None
        if not raw:
            return
        cup = raw.get("cup_type", "omni_dripper")
        is_tea = str(cup).strip().lower() == "tea" or cup == int(CupType.TEA)
        grind = int(raw.get("grind_size", 0) or 0)
        if is_tea or grind <= 0:
            return
        self.grind_size = grind
        self.rpm = int(raw.get("rpm", self.rpm) or self.rpm)
        self.async_update_listeners()

    async def async_execute_recipe(
        self,
        *,
        pour_overrides: Optional[List[dict]] = None,
        bypass_volume: Optional[float] = None,
        bypass_temperature: Optional[float] = None,
    ) -> None:
        """Execute the currently selected YAML recipe.

        Routing lives in :mod:`brewing`. Coffee uses an inline sequence
        (mirrors brAzzi64/xbloom-ble) that threads bypass_volume /
        bypass_temperature into the 8102 packet; tea (cup_type=4) takes
        the separate tea sequence. See brewing.py.

        For coffee grinding recipes the live ``grind_size`` / ``rpm``
        number values override the YAML — :meth:`select_recipe` keeps
        them in sync with the recipe, so by execute time they hold either
        the recipe value or the user's tweak. Tea / no-grind recipes are
        brewed as configured. ``bypass_volume`` / ``bypass_temperature``
        (service / LLM only) override the recipe's bypass for this brew —
        ``None`` means use the recipe's YAML value; bypass can be added to
        a recipe that has none. Tea always brews with bypass off.
        ``pour_overrides`` (LLM-only) tweaks individual pours' volume /
        flow_rate / pattern.
        """
        if not self._check_connected():
            return
        if not self.selected_recipe or self.selected_recipe not in self.recipes:
            _LOGGER.warning("No valid recipe selected (%s)", self.selected_recipe)
            return
        try:
            # ── Auto-switch to PRO mode if the machine is in Easy mode ──
            # Easy Mode silences or misinterprets the 8001/8004/8002 Pro-mode
            # brew sequence, resulting in hot water only (grinder never runs).
            # We always switch to PRO before a live brew to guarantee the
            # sequence is honoured.  The user can switch back via the Mode
            # switch entity if they want physical slot buttons afterwards.
            await self._ensure_pro_mode()
            raw = self.recipes[self.selected_recipe]
            recipe = _build_recipe_from_yaml(raw)
            is_tea = brewing.is_tea_recipe(recipe)
            if not is_tea and recipe.grind_size > 0:
                recipe.grind_size = int(self.grind_size)
                recipe.rpm = int(self.rpm)
            if pour_overrides:
                _apply_pour_overrides(recipe, pour_overrides)
            # Bypass — coffee only. Default to the recipe's YAML value;
            # an explicit override (service / LLM) wins. The tea sequence
            # forces bypass off internally, so tea always passes 0/0.
            if is_tea:
                bypass_vol = bypass_temp = 0.0
            else:
                bypass_vol = (
                    float(raw.get("bypass_volume", 0.0) or 0.0)
                    if bypass_volume is None else float(bypass_volume)
                )
                bypass_temp = (
                    float(raw.get("bypass_temperature", 0.0) or 0.0)
                    if bypass_temperature is None else float(bypass_temperature)
                )
            await brewing.async_execute_recipe(
                self.client, recipe,
                bypass_volume=bypass_vol,
                bypass_temperature=bypass_temp,
            )
        except Exception as exc:
            _LOGGER.error("Recipe execute error: %s", exc, exc_info=True)

    async def async_pause_resume(self) -> None:
        """Toggle between pause and resume based on machine state.

        When the machine is brewing or grinding the button PAUSES.
        When paused the button RESUMES (brewer + grinder).
        When idle the button is a no-op.
        """
        if not self._check_connected():
            return
        state = (self.data or {}).get("state", "unknown")
        try:
            if state == "paused":
                await self.client.brewer.restart()
                await self.client.grinder.restart()
            else:
                await self.client.brewer.pause()
                await self.client.grinder.pause()
        except Exception as exc:
            _LOGGER.error("Pause/resume error (state=%s): %s", state, exc)

    async def async_cancel(self) -> None:
        """Emergency stop all operations."""
        if not self._check_connected():
            return
        try:
            await self.client.stop_recipe()
            await asyncio.sleep(0.3)
            await self.client.grinder.stop()
            await self.client.brewer.stop()
            await asyncio.sleep(0.3)
            # Reset the machine's UI/mode state to the home screen.
            # Without this the machine stays in whatever screen was active
            # (e.g. tea recipe UI) after the hardware stops.
            await self.client._send_command(brewing._CMD_BACK_TO_HOME)
        except Exception as exc:
            _LOGGER.error("Cancel error: %s", exc)
        # Restore the user's persisted mode if we had auto-switched to Pro
        # for an HA operation that is now cancelled.
        await self._restore_persisted_mode("cancel")

    async def async_set_mode(self, mode: str) -> None:
        """Switch the machine's operating mode.

        ``mode`` must be ``pro`` or ``easy``.  Sends command 11511 with the
        appropriate mode code (type-2 packet).  The next MachineInfo
        notification will reflect the new mode.

        The choice is persisted in ``entry.options`` so it survives HA
        restarts and is reapplied on the next connection.
        """
        if not self._check_connected():
            return
        mode = mode.strip().lower()
        if mode not in ("pro", "easy"):
            raise ValueError(f"mode must be 'pro' or 'easy', got {mode!r}")
        try:
            mode_code = (
                "00000000" if mode == "pro"
                else "91327856"
            )
            mode_bytes = bytes.fromhex(mode_code)
            # Mode switch is a type-2 packet (cmd 11511).
            await self.client._send_command_raw(11511, mode_bytes, type_code=2)
            _LOGGER.info("Mode switch requested: %s", mode)
            # Persist so the choice survives HA restarts.
            self._mode = mode
            from .const import CONF_MODE
            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if entry is not None:
                new_options = {**entry.options, CONF_MODE: mode}
                self.hass.config_entries.async_update_entry(entry, options=new_options)
            # The next MachineInfo notification will update coordinator data.
            await asyncio.sleep(0.5)
            await self.async_refresh()
        except Exception as exc:
            _LOGGER.error("Mode switch error (%s): %s", mode, exc)

    async def _restore_persisted_mode(self, trigger: str) -> None:
        """Restore the user's persisted mode preference after an HA operation.

        When the user has chosen Easy Mode (the default) we temporarily
        switch to Pro for grind/pour/recipe execution, then switch back
        once the machine reports idle.  If the user explicitly chose Pro
        Mode we leave the machine there — it is already in the right mode.
        """
        if self._mode != "easy":
            # User explicitly chose Pro — nothing to restore.
            self._auto_switched_to_pro = False
            return
        await asyncio.sleep(3.0)
        if not self._auto_switched_to_pro:
            return  # another codepath already handled it
        state = (self.data or {}).get("state", "unknown")
        if state not in ("idle", "unknown"):
            _LOGGER.debug(
                "Not restoring Easy Mode yet — machine is %s (trigger=%s)",
                state, trigger,
            )
            return
        _LOGGER.info("Restoring Easy Mode after %s", trigger)
        try:
            await self.client._send_command_raw(
                11511, bytes.fromhex("91327856"), type_code=2,
            )
            self._auto_switched_to_pro = False
            await asyncio.sleep(0.5)
            await self.async_refresh()
        except Exception as exc:
            _LOGGER.warning("Easy Mode restore failed: %s", exc)

    async def _ensure_pro_mode(self) -> None:
        """Switch the machine to Pro Mode if it is currently in Easy Mode.

        Called before operations that need the Pro Mode command set
        (grind, pour, recipe execution).  Easy Mode silently ignores
        the Pro brew commands, resulting in the grinder never running
        (hot water only).

        Sets ``_auto_switched_to_pro`` so the event dispatcher can
        restore Easy Mode when the operation finishes.  This switch is
        ephemeral — the user's persisted mode preference is not
        overwritten.
        """
        current = (self.data or {}).get("mode", "pro")
        if current == "easy":
            _LOGGER.info("Machine is in Easy Mode — switching to Pro for HA operation")
            try:
                await self.client._send_command_raw(
                    11511, bytes.fromhex("00000000"), type_code=2,
                )
                self._auto_switched_to_pro = True
                await asyncio.sleep(0.5)
                await self.async_refresh()
            except Exception as exc:
                _LOGGER.warning("Pro-mode switch failed: %s", exc)

    async def async_vibrate_scale(self) -> None:
        """Vibrate the scale tray."""
        if not self._check_connected():
            return
        try:
            await self.client.scale.vibrate()
        except Exception as exc:
            _LOGGER.error("Vibrate error: %s", exc)

    async def async_tare_scale(self) -> None:
        """Zero the scale (cmd 8500)."""
        if not self._check_connected():
            return
        try:
            await brewing.async_tare(self.client)
        except Exception as exc:
            _LOGGER.error("Tare error: %s", exc)

    async def async_write_easy_slot(self, slot_letter: str) -> None:
        """Write the currently-selected recipe to Easy Mode slot A/B/C.

        The user picks the recipe via the Recipe ``select`` entity; each
        slot button passes its own letter through.
        """
        if not self._check_connected():
            return
        if not self.selected_recipe or self.selected_recipe not in self.recipes:
            _LOGGER.warning(
                "Easy slot write ignored — no recipe selected (%s)",
                self.selected_recipe,
            )
            return
        try:
            raw = self.recipes[self.selected_recipe]
            recipe = _build_recipe_from_yaml(raw)
            await brewing.async_write_easy_slot(self.client, slot_letter, recipe)
        except Exception as exc:
            _LOGGER.error("Easy slot write error (%s): %s", slot_letter, exc, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_connected(self) -> bool:
        if not self.client or not self.client.is_connected:
            _LOGGER.warning("Action requested but XBloom is not connected")
            return False
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Dynamic DeviceInfo populated from BLE MachineInfo data.

        serial_number and sw_version may be empty at first entity setup
        because MachineInfo notification hasn't arrived yet.
        _maybe_update_device_registry() will push updates to the HA
        device registry as soon as they become available.

        ``model`` is intentionally omitted: the firmware fills the
        ``theModel`` slice of RD_MachineInfo with 0xFF padding (per
        src/xbloom-ble/PROTOCOL.md), so any value would be misleading.
        """
        data = self.data or {}
        serial = data.get("serial_number") or self.mac_address
        version = data.get("version") or None
        info = DeviceInfo(
            identifiers={(DOMAIN, self.entry_id)},
            name="XBloom Coffee Machine",
            manufacturer="XBloom",
            serial_number=serial,
        )
        if version:
            info["sw_version"] = version
        return info

    @property
    def recipe_names(self) -> list[str]:
        return list(self.recipes.keys()) if self.recipes else ["No recipes configured"]
