"""XBloom DataUpdateCoordinator — manages BLE lifecycle and state."""
from __future__ import annotations

import asyncio
import copy
import logging
import struct
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service as service_helper
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCOUNT_RECIPES_SEEDED,
    CONF_EASY_SLOTS,
    CONF_RECIPES,
    CONF_RECIPES_SEEDED,
    DATA_COORDINATOR,
    DOMAIN,
    DEFAULT_MODE,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WATER_SOURCE,
    DEFAULT_WEIGHT_UNIT,
)
from ._client import HABleakConnection, XBloomClientWithEvents as XBloomClient, strict_ascii
from ._cloud_client import (
    XBloomCloudClient,
    cloud_recipe_to_local,
    local_recipe_to_cloud,
    validate_pour_volume_consistency,
)
from . import brewing
from .schema import (
    RECIPE_SCHEMA,
    compute_total_water_ml,
    dedupe_name,
    find_recipe,
    new_recipe_uid,
    scale_pours_to_total,
    strip_protected_recipe_fields,
)
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

    Reads the local schema's cloud-shaped field names (``dose_g``,
    ``ratio``, ``pours[].volume_ml/temperature_c/pause_seconds``) but
    still constructs the vendored ``XBloomRecipe``/``PourStep`` with
    THEIR field names (``bean_weight``, ``total_water``, ``volume``,
    ``temperature``, ``pausing``) — that vendored class is untouched, so
    the translation happens only here.
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
                volume=int(p["volume_ml"]),
                temperature=int(p["temperature_c"]),
                flow_rate=float(p.get("flow_rate", 3.0)),
                pausing=int(p.get("pause_seconds", 0)),
                pattern=PourPattern(int(p.get("pattern", 2))),
                vibration=vib,
            )
        )

    # total_water = dose_g * ratio (matches the XBloom cloud API's own
    # dose/grandWater relationship), rounded to the nearest ml to absorb
    # float drift from a repeating-decimal ratio. Falls back to summing
    # pour volumes when ratio/dose_g can't produce a total (tea recipes
    # have no weighed dose) — see schema.compute_total_water_ml, shared
    # so this and the LLM-facing recipe summary can't disagree on the
    # actual brewed total. A zero footer byte 2 causes the machine to
    # skip grinding (hot water only) on Easy Mode slots and may also
    # confuse live brew, so the fallback still matters here.
    total_water = int(round(compute_total_water_ml(raw)))

    return XBloomRecipe(
        grind_size=int(raw.get("grind_size", 0)),
        total_water=total_water,
        rpm=int(raw.get("rpm", 80)),
        cup_type=cup_val,
        name=str(raw.get("name", "Unknown")),
        bean_weight=float(raw.get("dose_g", 0.0)),
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
    "live_grind_size": None,
    "live_grind_speed": None,
    "voltage": None,
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

# Machine display-unit values for commands 8005 (weight) / 8010 (temp).
# Config-only (config_flow's Settings step) — unlike mode/water_source
# there's no dashboard toggle, since neither has a live BLE readback to
# reflect back (confirmed live 2026-07-04: both ACKs are bare status
# bytes with no echoed value, unlike the 11511 mode-switch ACK). Applied
# once per connection in async_connect(), not on every recipe/telemetry
# refresh — see _apply_unit_preferences.
WEIGHT_UNIT_OPTIONS = {"g": 0, "oz": 1, "ml": 2}
TEMP_UNIT_OPTIONS = {"c": 0, "f": 1}

# Pour pattern names ↔ ints, shared by the manual-pour select entity and
# the per-pour LLM override. Mirrors schema.py's _PATTERN_NAME_TO_INT and
# PourPattern (0=center, 1=circular, 2=spiral).
POUR_PATTERN_OPTIONS = {"center": 0, "circular": 1, "spiral": 2}

# Cloud-only fields the local RECIPE_SCHEMA doesn't model (color swatch,
# app placement, etc.) — an edit must preserve these verbatim from the
# fetched current recipe rather than resetting them to create's defaults.
_CLOUD_EDIT_PRESERVE_KEYS = (
    "theColor", "theSubsetId", "isShortcuts", "appPlace", "adaptedModel", "subSetType",
)

# Cap on how many of XBloom's official public recipes the one-time seed
# (async_seed_recipes) pulls in when no cloud account is configured. Each
# one needs its own fetch_shared_recipe() round-trip (the collective hub's
# list endpoint only returns summaries, no pourList).
_OFFICIAL_RECIPE_SYNC_LIMIT = 20


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
        initial_weight_unit: str = DEFAULT_WEIGHT_UNIT,
        initial_temp_unit: str = DEFAULT_TEMP_UNIT,
        cloud_email: Optional[str] = None,
        cloud_password: Optional[str] = None,
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

        # Cloud account (recipe sync) — entirely optional. The client is
        # always constructed (fetch_shared_recipe needs no login at all),
        # but authenticated calls (search/create/edit/delete, added later)
        # must check ``cloud_login_configured`` first and fail gracefully
        # rather than assume credentials exist.
        self._cloud_email = cloud_email
        self._cloud_password = cloud_password
        self.cloud_client = XBloomCloudClient(async_get_clientsession(hass))

        # Merged recipe view (name → dict) — YAML < entry.options; see
        # _rebuild_recipes. The options layer (the local store) is the
        # source of truth; the cloud is only consulted by the one-time
        # seed (async_seed_recipes) and the explicit import/export
        # services.
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

        # Recipe-execution pour tracking, so sensor.xbloom_flow_rate can
        # report the *current* pour's flow rate instead of a fixed manual
        # setpoint — recipes vary it per pour (see default_recipes.py).
        # Populated by async_execute_recipe(); advanced live by each
        # RD_BLOOM ("bloom") notification's pour_index (see
        # _client.py/_dispatch_event below). Cleared on recipe completion
        # or cancel, at which point self.flow_rate reverts to being the
        # manual-pour setpoint again.
        self._executing_recipe: bool = False
        self._active_recipe_pours: Optional[List] = None
        self.current_pour_index: Optional[int] = None

        # Water source for MANUAL POUR only (0=tank, 1=direct).
        # Loaded from entry.options so it survives HA restarts.
        # Recipe execution (APP_RECIPE_EXECUTE) does NOT use this value.
        self.water_source: int = initial_water_source

        # Machine operating mode ("pro" / "easy").  Persisted in entry.options
        # so the user's preference survives restarts and reconnects.
        self._mode: str = initial_mode

        # Machine display units (config_flow's Settings step only — see
        # WEIGHT_UNIT_OPTIONS/TEMP_UNIT_OPTIONS). Pushed to the machine
        # once per connection by _apply_unit_preferences.
        self._weight_unit: str = initial_weight_unit
        self._temp_unit: str = initial_temp_unit

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

        # Same idea as _water_shortage, driven by RD_ErrorIdling ("no_beans")
        # instead of RD_ErrorLackOfWater — the machine WAITS in this state
        # rather than refusing outright, so it's worth surfacing as a
        # distinct sensor.state value instead of leaving it generic.
        self._no_beans: bool = False

        # Track whether we temporarily switched to Pro Mode for an HA
        # operation.  When the operation completes we switch back to the
        # default (Easy) mode so the physical slot buttons work again.
        self._auto_switched_to_pro: bool = False

        # Set just before a user/HA-initiated disconnect so
        # _handle_unexpected_disconnect() can tell it apart from the
        # machine dropping the link on its own (observed on Easy<->Pro
        # mode switches) and skip reconnecting in the former case.
        self._manual_disconnect: bool = False

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
                # Layer the richer states our own event/status tracking can
                # see on top of the vendored DeviceState value: no_beans /
                # water_shortage (the machine WAITS rather than refusing),
                # and starting/brewing/ready from the raw status-heartbeat
                # stream. The cmd-tagged path alone is unreliable here —
                # hardware-confirmed 2026-07-15: RD_GRINDER_BEGIN never
                # fired during ~11s of real grinding, RD_BREWER_BEGIN fires
                # immediately after commit (well before real pouring
                # starts), and RD_Grinder_Stop flips vendored state to IDLE
                # right as grinding *ends*, moments before pouring begins.
                # See _client.py's _scan_for_status_frame /
                # _RAW_STATE_LABEL_MAP and coordinator._no_beans /
                # _water_shortage for provenance.
                raw_label = getattr(s, "_raw_state_label", None)
                if self._no_beans:
                    state_str = "no_beans"
                elif self._water_shortage:
                    state_str = "water_shortage"
                elif raw_label:
                    state_str = raw_label
                else:
                    state_str = s.state.value
                data = {
                    "connected": True,
                    "weight": round(s.scale.weight, 1),
                    "temperature": round(s.brewer.temperature, 1),
                    "state": state_str,
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
                    # Live readings from the machine's own knobs/heartbeat —
                    # see _client.py's RD_GRINDER_SIZE/SPEED/BREWER_MODE and
                    # RD_MachineInfo handling. None until first observed;
                    # 0 (the dataclass default) is not a real reading.
                    "live_grind_size": s.grinder.size or None,
                    "live_grind_speed": s.grinder.speed or None,
                    "voltage": getattr(s, "voltage", None),
                }
                # Mirror the physical temperature/pattern knobs onto the
                # manual-pour setpoints so number.temperature and
                # select.*_pour_pattern track knob turns in real time — but
                # only while idle. The knobs (and the app) are locked out
                # during an active grind/brew/pause, so any RD_
                # BREWER_TEMPERATURE (8108) seen in that window is the
                # machine's own in-progress reading (e.g. heating toward a
                # recipe's target), not a knob turn — mirroring it would
                # clobber the user's manual-pour setpoint with brew-transient
                # noise. Once back to idle, the knob is live again and the
                # setpoint should track it as normal.
                if data["state"] == "idle":
                    if s.brewer.temperature:
                        self.temperature = round(s.brewer.temperature)
                    live_pattern = getattr(s, "pour_pattern_live", None)
                    if live_pattern is not None:
                        self.pour_pattern = live_pattern
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
            self._manual_disconnect = False
            try:
                self.client = XBloomClient(
                    mac_address=self.mac_address,
                    connection=HABleakConnection(
                        self.hass, disconnected_callback=self._handle_unexpected_disconnect
                    ),
                )
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
                    await self._apply_unit_preferences()
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
        """Reconnect after the machine drops the BLE link on its own.

        Live-observed 2026-07-04: the machine briefly drops the link when
        switching Easy<->Pro mode, and this integration had no watchdog for
        that — the connection switch entity just stayed "off" until the
        user flipped it back on manually. Skipped when the drop was caused
        by our own ``async_disconnect()`` (``_manual_disconnect``), so
        turning the connection switch off doesn't immediately reconnect.
        """
        if self._manual_disconnect:
            return
        _LOGGER.warning("XBloom BLE link dropped unexpectedly — reconnecting")
        if self._machine_info_task and not self._machine_info_task.done():
            self._machine_info_task.cancel()
        self._machine_info_task = None
        self.client = None
        self.hass.async_create_task(self.async_connect())

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

        # Drive the water-shortage / no-beans flags from the BLE event stream.
        prev_shortage = self._water_shortage
        prev_no_beans = self._no_beans
        if category == "error" and event_type == "water_shortage":
            self._water_shortage = True
        elif category == "error" and event_type == "no_beans":
            self._no_beans = True
        elif category == "notification" and event_type in (
            "brewing_started", "pour_complete", "recipe_complete",
        ):
            # A successful brew implies water and beans were both available.
            self._water_shortage = False
            self._no_beans = False
        if (
            (prev_shortage != self._water_shortage or prev_no_beans != self._no_beans)
            and self.hass and self.hass.loop
        ):
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_refresh())
            )

        # ── Track the active pour during recipe execution ──
        # RD_BLOOM ("bloom") fires per pour, coffee or manual, with a
        # 0-based pour_index (see _client.py). Only meaningful while a
        # recipe execute is in flight (async_execute_recipe snapshots
        # _active_recipe_pours) — a manual pour's single bloom event is
        # ignored here since there's no recipe pour list to look up.
        pour_index_changed = False
        if (
            category == "notification" and event_type == "bloom"
            and self._executing_recipe and self._active_recipe_pours
        ):
            idx = attributes.get("pour_index")
            if isinstance(idx, int) and 0 <= idx < len(self._active_recipe_pours):
                self.current_pour_index = idx
                self.flow_rate = float(self._active_recipe_pours[idx].flow_rate)
                pour_index_changed = True
        elif category == "notification" and event_type in (
            "pour_complete", "recipe_complete",
        ):
            self._executing_recipe = False
            self._active_recipe_pours = None
            self.current_pour_index = None
        if pour_index_changed and self.hass and self.hass.loop:
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
        overrides: Optional[dict] = None,
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

        ``overrides`` replaces top-level recipe scalars (``dose_g`` /
        ``ratio`` / ``cup_type``) for this brew only — the stored recipe
        is untouched. Changing ``dose_g``/``ratio`` changes the total
        brew water, so the pours are proportionally rescaled to keep
        ``sum(pours) + bypass == dose_g * ratio`` (the machine's own
        invariant). Grind/RPM overrides go through the number-entity
        values above instead.
        """
        if not self._check_connected():
            return
        # Check water BEFORE touching the machine (mode switch, BLE writes,
        # etc.) — without this, a low-water recipe attempt runs the whole
        # brew sequence and only fails once the firmware fires
        # RD_ErrorLackOfWater, so the user finds out mid-attempt instead of
        # up front. Skipped when the user has told us they're on a direct
        # (hose) feed: water_level_ok tracks the internal tank sensor, which
        # stays empty/unreliable by design on a hose setup and would
        # otherwise block every brew. (This is the same water_source select
        # that otherwise only affects manual pour — here it's just the
        # user's declaration of which feed is actually plumbed in.)
        if self.water_source == WATER_SOURCE_TANK and not self.data.get(
            "water_level_ok", True
        ):
            raise HomeAssistantError(
                "XBloom water level is too low — refill the tank before brewing."
            )
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
            if overrides:
                raw = {**raw, **overrides}
                if "dose_g" in overrides or "ratio" in overrides:
                    dose = float(raw.get("dose_g", 0) or 0)
                    ratio = raw.get("ratio")
                    if dose > 0 and ratio:
                        effective_bypass = (
                            float(raw.get("bypass_volume", 0.0) or 0.0)
                            if bypass_volume is None else float(bypass_volume)
                        )
                        raw["pours"] = scale_pours_to_total(
                            raw.get("pours", []),
                            dose * float(ratio) - effective_bypass,
                        )
            recipe = _build_recipe_from_yaml(raw)
            is_tea = brewing.is_tea_recipe(recipe)
            if not is_tea and recipe.grind_size > 0:
                recipe.grind_size = int(self.grind_size)
                recipe.rpm = int(self.rpm)
            if pour_overrides:
                _apply_pour_overrides(recipe, pour_overrides)
            # Snapshot the final (post-override, post-rescale) pour list so
            # the "bloom" handler in _dispatch_event can look up each
            # pour's actual flow_rate as the brew progresses.
            self._active_recipe_pours = recipe.pours
            self._executing_recipe = True
            self.current_pour_index = None
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
            self._executing_recipe = False
            self._active_recipe_pours = None

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
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
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

    async def _apply_unit_preferences(self) -> None:
        """Push the configured display units to the machine (8005 weight,
        8010 temp) once per connection.

        Config-only (config_flow's Settings step) — there is no live ACK
        to read the applied unit back from (confirmed live 2026-07-04:
        both ACKs are bare status bytes, unlike 11511's mode-switch ACK
        which echoes the value), so unlike mode there is no dashboard
        select entity for this — just re-assert the stored preference on
        every fresh connection. Never raises; a failure here shouldn't
        block the rest of async_connect().
        """
        try:
            weight_code = WEIGHT_UNIT_OPTIONS.get(self._weight_unit, WEIGHT_UNIT_OPTIONS["g"])
            await self.client._send_command_raw(8005, bytes([weight_code]), type_code=1)
            temp_code = TEMP_UNIT_OPTIONS.get(self._temp_unit, TEMP_UNIT_OPTIONS["c"])
            await self.client._send_command_raw(8010, bytes([temp_code]), type_code=1)
            _LOGGER.info(
                "Applied display units: weight=%s temp=%s", self._weight_unit, self._temp_unit
            )
        except Exception as exc:
            _LOGGER.warning("Failed to apply display unit preferences: %s", exc)

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

    async def async_write_easy_slot(
        self, slot_letter: str, identifier: Optional[str] = None
    ) -> dict:
        """Write a recipe to Easy Mode slot A/B/C (11510, type-2 packet).

        ``identifier`` (uid / cloud table id / share URL/id / name)
        selects the recipe; omitted, the currently-selected recipe (the
        Recipe ``select`` entity) is written — that's what the slot
        button entities do. A share URL/id not present locally is
        auto-imported first (clone + uid), so "write this shared recipe
        to slot B" is one call. On success the slot → recipe mapping is
        persisted in ``entry.options["easy_slots"]`` so the slot text
        entities can show (and restore) what HA last wrote; the machine
        itself never reports slot contents.

        Live-verified 2026-07-15 (cross-referenced against
        Janczykkkko/xbloom-ble's independent capture): the machine only
        *persists* a slot when all three (A/B/C) are written together —
        writing one alone leaves it hung at "saving" (RETRY) — and only
        accepts slot writes in Pro Mode. So this call fills in the other
        two slots from ``entry.options["easy_slots"]`` (falling back to
        the target recipe for a slot HA has never written — the machine
        has no readback, so there's nothing else to preserve it with),
        force-switches to Pro Mode if needed, writes all three, then
        restores whatever mode the machine was in before.
        """
        if identifier:
            resolved = find_recipe(self.recipes or {}, identifier)
            if resolved is None and self._looks_like_share_ref(str(identifier)):
                imported = await self.async_import_cloud_recipe(str(identifier))
                if not imported.get("success"):
                    return imported
                resolved = find_recipe(self.recipes or {}, imported["uid"])
            if resolved is None:
                return {
                    "success": False,
                    "error": "recipe_not_found",
                    "message": f"No local recipe matches {identifier!r}.",
                }
            name, raw = resolved
        else:
            name = self.selected_recipe
            if not name or name not in (self.recipes or {}):
                _LOGGER.warning(
                    "Easy slot write ignored — no recipe selected (%s)", name
                )
                return {
                    "success": False,
                    "error": "no_recipe_selected",
                    "message": "No recipe is selected.",
                }
            raw = self.recipes[name]

        if not self._check_connected():
            return {
                "success": False,
                "error": "not_connected",
                "message": "The XBloom is not connected over Bluetooth.",
            }

        target_letter = slot_letter.strip().upper()
        if target_letter not in ("A", "B", "C"):
            return {
                "success": False,
                "error": "invalid_slot",
                "message": f"slot must be A, B, or C — got {slot_letter!r}",
            }

        # Fill in the other two slots from our own record of what HA last
        # wrote (the machine can't be asked what's actually there). A
        # slot HA has never written mirrors the target recipe rather than
        # being left as an unknown/blank.
        slot_names = {target_letter: name}
        slot_raws = {target_letter: raw}
        for other in ("A", "B", "C"):
            if other == target_letter:
                continue
            contents = self.easy_slot_contents(other)
            other_resolved = (
                find_recipe(self.recipes or {}, contents["uid"])
                if contents and contents.get("uid") else None
            )
            if other_resolved:
                slot_names[other], slot_raws[other] = other_resolved
            else:
                slot_names[other], slot_raws[other] = name, raw

        try:
            slot_recipes = {
                letter: _build_recipe_from_yaml(slot_raws[letter])
                for letter in ("A", "B", "C")
            }
        except Exception as exc:
            _LOGGER.error(
                "Easy slot write error building recipes (%s): %s",
                target_letter, exc, exc_info=True,
            )
            return {
                "success": False,
                "error": "write_failed",
                "message": f"Slot write failed: {exc}",
            }

        switched_to_pro = False
        try:
            if (self.data or {}).get("mode", "pro") == "easy":
                await self.client._send_command_raw(
                    11511, bytes.fromhex("00000000"), type_code=2,
                )
                switched_to_pro = True
                await asyncio.sleep(0.5)

            await brewing.async_write_easy_slots(self.client, slot_recipes)
        except Exception as exc:
            _LOGGER.error(
                "Easy slot write error (%s): %s", target_letter, exc, exc_info=True
            )
            return {
                "success": False,
                "error": "write_failed",
                "message": f"Slot write failed: {exc}",
            }
        finally:
            if switched_to_pro:
                try:
                    await asyncio.sleep(0.5)
                    await self.client._send_command_raw(
                        11511, bytes.fromhex("91327856"), type_code=2,
                    )
                    await self.async_refresh()
                except Exception as exc:
                    _LOGGER.warning("Restoring Easy Mode after slot write failed: %s", exc)

        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is not None:
            slots = dict(entry.options.get(CONF_EASY_SLOTS) or {})
            for letter in ("A", "B", "C"):
                slots[letter] = {
                    "uid": slot_raws[letter].get("uid"), "name": slot_names[letter],
                }
            new_options = dict(entry.options)
            new_options[CONF_EASY_SLOTS] = slots
            self.hass.config_entries.async_update_entry(entry, options=new_options)
        self.async_update_listeners()
        return {"success": True, "slot": target_letter, "name": name,
                "uid": raw.get("uid")}

    def easy_slot_contents(self, slot_letter: str) -> Optional[dict]:
        """What HA last wrote to a slot — ``{"uid", "name"}`` or None."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return None
        slots = entry.options.get(CONF_EASY_SLOTS) or {}
        return slots.get(slot_letter.upper())

    # ------------------------------------------------------------------
    # Cloud account (recipe sync) — all optional, never required for BLE use
    # ------------------------------------------------------------------

    @property
    def cloud_login_configured(self) -> bool:
        """Whether an XBloom cloud email/password were set up.

        Only gates AUTHENTICATED cloud calls (search/create/edit/delete —
        added in a later phase). Does NOT gate :meth:`async_import_cloud_recipe`
        — fetching a shared recipe needs no login at all on the wire.
        """
        return bool(self._cloud_email and self._cloud_password)

    async def async_ensure_cloud_login(self) -> bool:
        """Log in if an account is configured and not already logged in.

        Returns False (never raises) when no account is configured or the
        login itself fails — callers should turn that into a structured
        error rather than let an exception propagate.
        """
        if not self.cloud_login_configured:
            return False
        if self.cloud_client.logged_in:
            return True
        return await self.cloud_client.login(self._cloud_email, self._cloud_password)

    async def async_import_cloud_recipe(self, share_url_or_id: str) -> dict:
        """Fetch a recipe from an XBloom cloud share URL/id and save it locally.

        No login required — ``RecipeDetail.html`` is a public,
        unauthenticated endpoint, so this works even with no cloud account
        configured. Returns a structured ``{"success": bool, ...}`` dict
        rather than raising, so the service handler / LLM tool can surface
        a clean error either way.
        """
        local_raw = await self.cloud_client.fetch_shared_recipe(share_url_or_id)
        if local_raw is None:
            return {
                "success": False,
                "error": "fetch_failed",
                "message": (
                    "Could not fetch that recipe — check the share URL/id, "
                    "or the XBloom cloud API may be unreachable."
                ),
            }
        try:
            validated = RECIPE_SCHEMA(local_raw)
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Fetched recipe failed validation: {exc}",
            }

        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return {
                "success": False,
                "error": "entry_not_found",
                "message": "Config entry not found.",
            }

        # Name collisions get the " (2)" suffix instead of a rejection —
        # same rule as create_local_recipe, so a re-import never silently
        # overwrites local edits.
        name = dedupe_name(validated["name"], self.recipes or {})
        validated["name"] = name
        validated["uid"] = new_recipe_uid()
        validated["source"] = "import"
        # Remember where it came from so find_recipe can resolve the same
        # share URL/id back to this local copy later.
        if "://" not in share_url_or_id:
            validated.setdefault(
                "share_url",
                f"https://share-h5.xbloom.com/?id={share_url_or_id.strip()}",
            )
        else:
            validated.setdefault("share_url", share_url_or_id.strip())

        options_recipes = dict(entry.options.get(CONF_RECIPES) or {})
        options_recipes[name] = validated
        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = options_recipes
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._rebuild_recipes()
        self.async_update_listeners()
        return {
            "success": True,
            "uid": validated["uid"],
            "name": name,
            "recipe": validated,
        }

    def _rebuild_recipes(self) -> None:
        """Recompute ``self.recipes`` from both layers, lowest precedence
        first: YAML (``hass.data[DOMAIN]["yaml_recipes"]``) < the local
        store (``entry.options[CONF_RECIPES]``). A ``None`` value in the
        store is a tombstone — it hides that name from the YAML layer
        rather than being a recipe itself (used when deleting a YAML
        recipe via the UI). Mirrored by ``config_flow._all_visible_recipes``.
        Safe to call at any time; does not touch the network.
        """
        merged: Dict[str, dict] = {}
        merged.update(self.hass.data.get(DOMAIN, {}).get("yaml_recipes", {}))
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        options_recipes = (entry.options.get(CONF_RECIPES) if entry else None) or {}
        if isinstance(options_recipes, dict):
            for name, recipe in options_recipes.items():
                if recipe is None:
                    merged.pop(name, None)
                else:
                    merged[name] = recipe
        self.recipes = merged
        # _rebuild_recipes is sync (called from many non-async contexts —
        # see its own callers), but the schema refresh needs to await
        # async_get_all_descriptions, so it can't be called inline here.
        # Fire-and-forget via the event loop instead of awaiting inline.
        self.hass.async_create_task(self._async_refresh_recipe_service_schemas())

    # Services whose `recipe` field is a select selector (services.yaml
    # ships it with empty static options + custom_value: true) that we
    # keep populated with the live recipe list — see
    # _async_refresh_recipe_service_schemas.
    _RECIPE_SELECTOR_SERVICES = (
        "execute_recipe",
        "edit_recipe",
        "delete_recipe",
        "write_recipe_to_easy_slot",
        "cloud_export_recipe",
    )

    async def _async_refresh_recipe_service_schemas(self) -> None:
        """Populate the `recipe` dropdown on recipe-taking services.

        A plain text field for "which recipe" is exactly what let a typo
        (e.g. calling delete_recipe with a garbled name) fail with no
        autocomplete to catch it. services.yaml selectors can't be
        dynamic, so instead we patch the registered service schema at
        runtime via async_set_service_schema — HA re-reads it on every
        Developer Tools render. custom_value stays on, so a share URL /
        cloud id that isn't in this list yet can still be typed directly.

        Recipes are per-config-entry, but services are per-domain, so
        this merges the recipe list across every configured XBloom
        machine (deduped by uid) rather than just this coordinator's own.
        Called after every recipe-list change (see _rebuild_recipes);
        never touches the network.
        """
        merged: Dict[str, dict] = {}
        for data in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(data, dict) or DATA_COORDINATOR not in data:
                continue
            other: XBloomCoordinator = data[DATA_COORDINATOR]
            for name, recipe in (other.recipes or {}).items():
                uid = recipe.get("uid") or name
                merged.setdefault(uid, (name, recipe))
        options = [
            {"value": uid, "label": name}
            for uid, (name, _recipe) in sorted(merged.items(), key=lambda kv: kv[1][0].lower())
        ]

        descriptions = (await service_helper.async_get_all_descriptions(self.hass)).get(
            DOMAIN, {}
        )
        for svc_name in self._RECIPE_SELECTOR_SERVICES:
            current = descriptions.get(svc_name)
            if not current or "recipe" not in current.get("fields", {}):
                continue
            updated = copy.deepcopy(current)
            recipe_field = updated["fields"]["recipe"]
            selector = recipe_field.get("selector") or {}
            if "select" not in selector:
                continue  # not our dynamic selector (unexpected shape) — leave alone
            selector["select"]["options"] = options
            service_helper.async_set_service_schema(self.hass, DOMAIN, svc_name, updated)

    # ------------------------------------------------------------------
    # Local recipe store CRUD — the source of truth behind the recipe
    # select entity and the list/create/edit/delete services & LLM tools.
    # ------------------------------------------------------------------

    def _write_options_recipes(self, options_recipes: Dict[str, Any]) -> None:
        """Persist the store and refresh the merged view + entities."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = options_recipes
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._rebuild_recipes()
        self.async_update_listeners()

    def _options_recipes(self) -> Dict[str, Any]:
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        raw = (entry.options.get(CONF_RECIPES) if entry else None) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    @staticmethod
    def _looks_like_share_ref(identifier: str) -> bool:
        """Heuristic: could this unresolved identifier be a share URL/id?

        Used by edit/write-slot to decide between auto-importing and a
        plain recipe_not_found error, so a typo'd recipe name doesn't
        trigger a pointless network fetch. Share ids are base64
        (possibly percent-encoded) — recipe names practically never
        contain these characters.
        """
        s = identifier.strip()
        return "://" in s or any(c in s for c in "%=+/")

    @staticmethod
    def _summarize_local_recipe(name: str, recipe: dict) -> dict:
        summary = {
            "uid": recipe.get("uid"),
            "name": name,
            "source": recipe.get("source"),
            "dose_g": recipe.get("dose_g"),
            "ratio": recipe.get("ratio"),
            "grind_size": recipe.get("grind_size"),
            "rpm": recipe.get("rpm"),
            "cup_type": recipe.get("cup_type"),
            "pour_count": len(recipe.get("pours") or []),
        }
        if recipe.get("cloud_table_id") is not None:
            summary["cloud_table_id"] = recipe["cloud_table_id"]
        if recipe.get("share_url"):
            summary["share_url"] = recipe["share_url"]
        return summary

    def list_local_recipes(self, query: Optional[str] = None) -> dict:
        """List every local recipe (merged YAML + store view), optionally
        filtered by a case-insensitive name substring."""
        rows = [
            self._summarize_local_recipe(name, recipe)
            for name, recipe in (self.recipes or {}).items()
        ]
        if query:
            needle = query.strip().lower()
            rows = [r for r in rows if needle in (r["name"] or "").lower()]
        return {"success": True, "recipes": rows}

    def create_local_recipe(self, recipe: dict) -> dict:
        """Validate and save a new local recipe (uid assigned here).

        A name collision gets the `` (2)`` suffix rather than a rejection
        — same rule as import, so callers never silently overwrite.
        User input is never trusted for identity/cloud metadata — a
        create_recipe YAML that includes ``uid``/``cloud_table_id``/
        ``share_url``/``source`` (accidentally or otherwise) has all four
        stripped before validation; every new recipe starts as its own
        local-only identity.
        """
        try:
            validated = RECIPE_SCHEMA(strip_protected_recipe_fields(recipe))
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Recipe failed validation: {exc}",
            }
        options_recipes = self._options_recipes()
        # Dedupe against the *visible* names — a tombstoned name is free
        # to reuse (writing it just replaces the tombstone).
        name = dedupe_name(validated["name"], self.recipes or {})
        validated["name"] = name
        validated["uid"] = new_recipe_uid()
        validated["source"] = "manual"
        options_recipes[name] = validated
        self._write_options_recipes(options_recipes)
        return {"success": True, "uid": validated["uid"], "name": name}

    async def async_edit_local_recipe(self, identifier: str, changes: dict) -> dict:
        """Patch a local recipe in place (uid and cloud metadata kept).

        If ``identifier`` is a share URL/id not present locally, the
        recipe is auto-imported first (clone + uid) and the edit lands on
        the local copy — cloud recipes are never edited directly.
        """
        resolved = find_recipe(self.recipes or {}, identifier)
        if resolved is None and self._looks_like_share_ref(str(identifier)):
            imported = await self.async_import_cloud_recipe(str(identifier))
            if not imported.get("success"):
                return imported
            resolved = find_recipe(self.recipes or {}, imported["uid"])
        if resolved is None:
            return {
                "success": False,
                "error": "recipe_not_found",
                "message": f"No local recipe matches {identifier!r}.",
            }
        old_name, current = resolved

        # Identity is never patchable — it's what the edit is anchored to.
        # Stripping (rather than "restore if current already has one")
        # also blocks injecting a field current doesn't have yet, e.g.
        # a never-exported recipe's changes claiming a cloud_table_id.
        merged = {**current, **strip_protected_recipe_fields(changes or {})}
        try:
            validated = RECIPE_SCHEMA(merged)
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Edited recipe failed validation: {exc}",
            }

        options_recipes = self._options_recipes()
        new_name = validated["name"]
        if new_name != old_name and new_name in (self.recipes or {}):
            return {
                "success": False,
                "error": "name_taken",
                "message": f"A recipe named {new_name!r} already exists.",
            }
        yaml_names = set(self.hass.data.get(DOMAIN, {}).get("yaml_recipes") or {})
        if new_name != old_name:
            options_recipes.pop(old_name, None)
            if old_name in yaml_names:
                # Renaming a YAML-layer recipe must not resurface the
                # YAML original under the old name.
                options_recipes[old_name] = None
        options_recipes[new_name] = validated
        if self.selected_recipe == old_name:
            self.selected_recipe = new_name
        self._write_options_recipes(options_recipes)
        return {
            "success": True,
            "uid": validated.get("uid"),
            "name": new_name,
            "recipe": validated,
        }

    def delete_local_recipe(self, identifier: str) -> dict:
        """Delete a local recipe (the cloud copy, if any, is untouched)."""
        resolved = find_recipe(self.recipes or {}, identifier)
        if resolved is None:
            return {
                "success": False,
                "error": "recipe_not_found",
                "message": f"No local recipe matches {identifier!r}.",
            }
        name, recipe = resolved
        options_recipes = self._options_recipes()
        options_recipes.pop(name, None)
        if name in (self.hass.data.get(DOMAIN, {}).get("yaml_recipes") or {}):
            # Tombstone so the YAML layer's copy stays hidden.
            options_recipes[name] = None
        if self.selected_recipe == name:
            self.selected_recipe = None
        self._write_options_recipes(options_recipes)
        return {"success": True, "uid": recipe.get("uid"), "name": name}

    def seed_bundled_recipes(self) -> None:
        """Fresh-install fallback: write the bundled defaults as local recipes.

        Runs synchronously at setup (no network) so the recipe dropdown is
        never empty before the one-time cloud seed (a background task)
        completes. Only acts when ``entry.options[CONF_RECIPES]`` is
        empty/absent — on any later boot the store is non-empty (or the
        user deleted everything on purpose, which we respect via the
        ``CONF_RECIPES_SEEDED`` flag).
        """
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        if entry.options.get(CONF_RECIPES) or entry.options.get(CONF_RECIPES_SEEDED):
            return
        seeded: Dict[str, dict] = {}
        defaults = self.hass.data.get(DOMAIN, {}).get("default_recipes") or {}
        for name, recipe in defaults.items():
            local = dict(recipe)
            local["uid"] = new_recipe_uid()
            local["source"] = "seed_bundled"
            seeded[name] = local
        if not seeded:
            return
        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = seeded
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info("Seeded %d bundled recipe(s) into the local store", len(seeded))

    async def async_seed_recipes(self) -> None:
        """One-time seed of the local recipe store from the cloud.

        Replaces the old always-on hourly sync layer: the local store
        (``entry.options[CONF_RECIPES]``) is the source of truth, and the
        cloud is consulted exactly once per install — the account's own
        recipes if a cloud account is configured (tracked by
        ``CONF_ACCOUNT_RECIPES_SEEDED``, so adding an account later
        triggers one more seed on the reload that follows), else XBloom's
        official public recipes (``CONF_RECIPES_SEEDED``). Fetched recipes
        become ordinary local recipes (uid + source metadata); names
        already taken locally — including tombstones (= user deletions)
        and YAML recipes — are skipped. A failed fetch leaves the flag
        unset so the next HA start retries; never raises.
        """
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        account = self.cloud_login_configured
        flag = CONF_ACCOUNT_RECIPES_SEEDED if account else CONF_RECIPES_SEEDED
        if entry.options.get(flag):
            return

        fetched: Optional[list] = None
        source = ""
        if account:
            if await self.async_ensure_cloud_login():
                cloud_list = await self.cloud_client.list_recipes()
                if cloud_list is not None:
                    fetched = []
                    for raw in cloud_list:
                        local = cloud_recipe_to_local(raw)
                        # Keep the cloud identity alongside the local uid so
                        # cloud_export_recipe can update in place later.
                        if raw.get("tableId") is not None:
                            local["cloud_table_id"] = raw["tableId"]
                        if raw.get("shareRecipeLink"):
                            local["share_url"] = raw["shareRecipeLink"]
                        fetched.append(local)
                    source = "seed_cloud"
        else:
            official = await self.cloud_client.fetch_official_recipes(
                limit=_OFFICIAL_RECIPE_SYNC_LIMIT
            )
            if official is not None:
                fetched = official
                source = "seed_official"

        if fetched is None:
            _LOGGER.info(
                "One-time recipe seed fetch failed (account=%s); "
                "will retry on next HA start", account,
            )
            return

        options_recipes = dict(entry.options.get(CONF_RECIPES) or {})
        yaml_names = set(self.hass.data.get(DOMAIN, {}).get("yaml_recipes") or {})
        added = 0
        for local in fetched:
            try:
                validated = RECIPE_SCHEMA(local)
            except vol.Invalid as exc:
                _LOGGER.warning(
                    "Skipping seed recipe %r: %s", local.get("name"), exc
                )
                continue
            name = validated["name"]
            # Existing local recipes, tombstones (user deletions), and
            # YAML recipes all win over the seed.
            if name in options_recipes or name in yaml_names:
                continue
            validated["uid"] = new_recipe_uid()
            validated["source"] = source
            options_recipes[name] = validated
            added += 1

        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = options_recipes
        new_options[flag] = True
        if account:
            # An account seed also satisfies the initial seed — don't pull
            # official recipes on top if the account is removed later.
            new_options[CONF_RECIPES_SEEDED] = True
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._rebuild_recipes()
        self.async_update_listeners()
        _LOGGER.info("Recipe seed complete: source=%s added=%d", source, added)

    async def async_search_collective_recipes(self, **filters) -> dict:
        """Search the public collective.xbloom.com community recipe hub.

        Unlike the private cloud-account calls (login required), this is a
        completely separate, unauthenticated API — no XBloom account
        needed at all. ``filters``
        are passed straight through to
        :meth:`_cloud_client.XBloomCloudClient.search_collective_recipes`
        (keyword/category/src/machine/cup_type/origin/varietal/process/
        roast/flavor/sort/sort_direction). Returns a structured
        ``{"success": bool, ...}`` dict rather than raising, matching the
        error-shape convention of the rest of this class.
        """
        result = await self.cloud_client.search_collective_recipes(**filters)
        if result is None:
            return {
                "success": False,
                "error": "search_failed",
                "message": "Could not search the XBloom collective recipe hub.",
            }
        return {"success": True, **result}

    async def async_export_recipe(self, identifier: str) -> dict:
        """Export a local recipe to the XBloom cloud account.

        Not logged in: no network call at all — returns just
        ``{"recipe": ...}`` (no id/link, matching the "generated locally
        only" contract). Logged in: creates the recipe on the account if
        the local copy has no ``cloud_table_id`` yet, otherwise updates
        that same cloud recipe in place (keeping id and share link
        stable), then stores the server-assigned ``cloud_table_id`` /
        ``share_url`` back on the local copy and returns
        ``{"id", "link", "recipe"}``. The share link is always the
        server's own value, never derived client-side.

        Recipes with a non-zero ``bypass_volume`` get a ``warning`` field:
        bypass-ON cloud payload requirements are still unverified live
        (see AGENTS.md) — the export proceeds anyway.
        """
        resolved = find_recipe(self.recipes or {}, identifier)
        if resolved is None:
            return {
                "success": False,
                "error": "recipe_not_found",
                "message": f"No local recipe matches {identifier!r}.",
            }
        name, raw = resolved
        warning = None
        if float(raw.get("bypass_volume") or 0) > 0:
            warning = (
                "This recipe has bypass enabled; the cloud API's bypass-ON "
                "payload requirements are unverified, so the exported copy "
                "may be rejected or altered by XBloom's servers."
            )

        if not self.cloud_login_configured:
            out: Dict[str, Any] = {"success": True, "recipe": raw}
            if warning:
                out["warning"] = warning
            return out

        try:
            validated = RECIPE_SCHEMA(dict(raw))
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Recipe does not match the schema: {exc}",
            }
        # Only enforced for bypass-off recipes — that's the formula
        # actually confirmed live (see AGENTS.md). For bypass>0 the
        # `warning` above already covers it; hard-rejecting here would
        # contradict "the export proceeds anyway" and block recipes
        # where bypass water sits on top of the dose*ratio budget
        # instead of inside it (confirmed against a live account recipe
        # 2026-07-04).
        if not warning:
            mismatch = validate_pour_volume_consistency(validated)
            if mismatch:
                return {
                    "success": False,
                    "error": "pour_volume_mismatch",
                    "message": f"Recipe rejected before sending to the cloud: {mismatch}",
                }
        if not await self.async_ensure_cloud_login():
            return {
                "success": False,
                "error": "login_failed",
                "message": (
                    "Could not log in to the XBloom cloud account — check "
                    "the configured email/password."
                ),
            }

        result: Optional[dict] = None
        table_id = raw.get("cloud_table_id")
        if table_id:
            current_raw = await self.cloud_client.get_recipe(int(table_id))
            if current_raw is None:
                # The cloud copy is gone (deleted in the app) — fall
                # through to a fresh create below.
                table_id = None
            else:
                cloud_fields = local_recipe_to_cloud(validated)
                for key in _CLOUD_EDIT_PRESERVE_KEYS:
                    if key in current_raw:
                        cloud_fields[key] = current_raw[key]
                if not await self.cloud_client.update_recipe(
                    int(table_id), cloud_fields
                ):
                    return {
                        "success": False,
                        "error": "export_failed",
                        "message": (
                            "Could not update the recipe on the XBloom "
                            "cloud account."
                        ),
                    }
                result = {
                    "table_id": int(table_id),
                    "share_url": raw.get("share_url")
                    or current_raw.get("shareRecipeLink"),
                }
        if result is None:
            created = await self.cloud_client.create_recipe(validated)
            if created is None:
                return {
                    "success": False,
                    "error": "export_failed",
                    "message": (
                        "Could not create the recipe on the XBloom cloud "
                        "account."
                    ),
                }
            result = created

        # Persist the cloud identity on the local copy so the next export
        # updates in place and find_recipe resolves the cloud id/link.
        options_recipes = self._options_recipes()
        stored = dict(options_recipes.get(name) or raw)
        stored["cloud_table_id"] = result["table_id"]
        if result.get("share_url"):
            stored["share_url"] = result["share_url"]
        options_recipes[name] = stored
        self._write_options_recipes(options_recipes)

        out = {
            "success": True,
            "id": result["table_id"],
            "link": result.get("share_url"),
            "recipe": stored,
        }
        if warning:
            out["warning"] = warning
        return out

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

    def _sub_device_info(self, key: str, name: str) -> DeviceInfo:
        """Child DeviceInfo for a physical sub-component (grinder/scale/brewer).

        Same config entry, separate device-registry entry — nested under
        the main device via ``via_device`` so its page only shows that
        component's entities instead of everything at once. unique_ids
        are untouched, so this is a pure device-registry regrouping: no
        entity_id changes, no automation/dashboard breakage.
        """
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{key}")},
            name=name,
            manufacturer="XBloom",
            via_device=(DOMAIN, self.entry_id),
        )

    @property
    def grinder_device_info(self) -> DeviceInfo:
        return self._sub_device_info("grinder", "Grinder")

    @property
    def scale_device_info(self) -> DeviceInfo:
        return self._sub_device_info("scale", "Scale")

    @property
    def brewer_device_info(self) -> DeviceInfo:
        return self._sub_device_info("brewer", "Brewer")

    @property
    def recipe_names(self) -> list[str]:
        return list(self.recipes.keys()) if self.recipes else ["No recipes configured"]
