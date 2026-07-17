"""XBloom DataUpdateCoordinator — manages BLE lifecycle and state."""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import struct
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
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

# Connection-supervisor watchdog: if a still-"connected" client hasn't seen a
# single BLE notification in this long, the link is presumed stale/wedged and
# force-reconnected. Mirrors the official Android app's AppDeviceManager
# heartbeat watchdog (see AGENTS.md's BLE connection management section),
# which uses ~2s — widened here since our telemetry-flood assumption is
# unverified on real hardware in this environment (no BLE-capable devcontainer
# host) and a false-positive reconnect is more disruptive for an
# always-running HA integration than for a foregrounded phone app.
_BLE_SILENCE_TIMEOUT_S = 15.0

# Firmware version gates for BLE features that don't exist on older
# firmware — the machine silently ignores commands it doesn't understand
# rather than refusing cleanly, so we check first and give a clear error.
# This integration never flashes firmware itself; that's a much
# higher-risk operation (bricking a real device with no rollback we
# control) — see update.py's XBloomFirmwareUpdateEntity, which only reads
# xBloom's own live "latest version" API for an informational comparison.
#
# Source: xBloom's own support docs (Zendesk "xBloom Studio Firmware Update
# Summary" section, https://tbdxsupport.zendesk.com/hc/en-us/sections/25914689676443,
# fetched 2026-07-16): V12.0D.122 (2024-07-12) -> V12.0D.210 (2024-12-24,
# introduces Auto/Easy Mode — cmd 11510/11511/11512 don't exist before this)
# -> V12.0D.300 (2025-03-20, introduces tea recipes — cmd 4512/4513 don't
# exist before this) -> V12.0D.400 (2025-07-02, extends tea steep to 360s +
# multi-temperature brewing). These two thresholds are historical facts
# that never change, unlike "the latest version" — that's fetched live,
# not hardcoded (see update.py).
MIN_FIRMWARE_EASY_MODE = "V12.0D.210"
MIN_FIRMWARE_TEA = "V12.0D.300"

_FIRMWARE_BUILD_RE = re.compile(r"^V12\.0D\.(\d+)$")


def _firmware_build(version: Optional[str]) -> Optional[int]:
    """Parse the trailing build number out of a ``V12.0D.NNN`` firmware
    string (the only scheme xBloom has used so far). Returns ``None`` for
    blank/unrecognized strings — MachineInfo hasn't arrived yet, or a
    future version scheme this doesn't understand — callers must treat
    that as "can't tell", not "outdated"."""
    if not version:
        return None
    m = _FIRMWARE_BUILD_RE.match(version.strip())
    return int(m.group(1)) if m else None


def _firmware_at_least(version: Optional[str], minimum: str) -> bool:
    """True if ``version`` is parseable and >= ``minimum``. An unparseable
    or unknown current version fails open (returns True) — we'd rather let
    a firmware-gated brew attempt hit the machine's own silent refusal than
    block a real feature on a version string we can't read."""
    current = _firmware_build(version)
    required = _firmware_build(minimum)
    if current is None or required is None:
        return True
    return current >= required


# Advanced Features level->raw conversion. Decompiled from the official
# app 2026-07-16 (MachineSetPourRadiusActivity / MachineSetVibrationAmplitudeActivity)
# — see AGENTS.md's command-id validation sweep and
# async_set_advanced_settings's docstring for the pour-radius "center"
# caveat.
def _vibration_level_to_raw(level: int) -> int:
    """L1-L6 (0-5) -> raw device value. Fixed absolute scale, no
    per-device reference needed."""
    return 1000 + level * 100


def _pour_radius_level_to_raw(level: int, center: int) -> int:
    """L1-L5 (0-4) -> raw device value, 80 apart, centered on ``center``
    (level 2 == center). ``center`` should be the machine's own most
    recently read pour_radius value — see the caller's docstring for why
    we don't have the official app's true factory-default reference."""
    return center - (2 - level) * 80


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
    "temperature": None,
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
    "pour_radius": None,
    "vibration_amplitude": None,
}

# Water source integer values. Used both in the APP_BREWER_START manual-pour
# payload and as the machine's own water-feed setting via cmd 4508
# (switchWaterFeed in the official app's BleCodeFactory) — same 0/1 codes in
# both places (Studio uses WaterSourceType.ordinal(); the app's 8/50 values
# are J20-only). Recipe execution (APP_RECIPE_EXECUTE) still doesn't take a
# water_source parameter — the machine controls its own pours internally,
# honoring its persisted 4508 setting.
WATER_SOURCE_TANK   = 0   # Built-in tank
WATER_SOURCE_DIRECT = 1   # Direct plumbed line

WATER_SOURCE_OPTIONS = {
    "tank":   WATER_SOURCE_TANK,
    "direct": WATER_SOURCE_DIRECT,
}

# Machine display-unit values for commands 8005 (weight) / 8010 (temp).
# Config-only (config_flow's Settings step) — no dashboard toggle. The 8005/
# 8010 ACKs carry no echoed value (confirmed live 2026-07-04), but the
# machine DOES push cmd 8015 (RD_UNIT_CHANGE) with all three values —
# weight unit, temp unit, water source — when they change on its own
# touchscreen; _async_sync_units_from_machine() folds that back into these
# stored preferences. Applied once per connection in async_connect(), not on
# every recipe/telemetry refresh — see _apply_unit_preferences.
WEIGHT_UNIT_OPTIONS = {"g": 0, "oz": 1, "ml": 2}
TEMP_UNIT_OPTIONS = {"c": 0, "f": 1}
_RAW_TO_WEIGHT_UNIT = {v: k for k, v in WEIGHT_UNIT_OPTIONS.items()}
_RAW_TO_TEMP_UNIT = {v: k for k, v in TEMP_UNIT_OPTIONS.items()}

# The machine's own water-feed setting (cmd 4508, official app's
# switchWaterFeed). A single LE uint32: 0=tank, 1=direct — see
# WATER_SOURCE_TANK/DIRECT above.
_CMD_SWITCH_WATER_FEED = 4508

# Whole-recipe pause/restart — decompiled 2026-07-17 (jadx) from
# com/chisalsoft/andite/manager/AppJ15AutoManager.java's pause()/restart(),
# the official app's only recipe-pause mechanism (bound to the single
# pause/resume button shown while an Auto recipe is running). Both are
# bare commands (``CodeModule(40518, ...)``/``CodeModule(40524, ...)``, no
# payload) — the app's own success handler does nothing but update local
# UI/timer bookkeeping, no readback.
#
# NOT ``APP_GRINDER_PAUSE``/``APP_BREWER_PAUSE`` (8018/8019) — those only
# ever appear in the app's separate, standalone manual Grinder/Brewer
# screens (``GrinderActivity``/``BrewerActivity``, reached from the home
# screen's own Grind/Brew quick-action icons via a distinct
# ``APP_GRINDER_IN``/``RD_BREWER_IN`` "enter mode" handshake first) — a
# completely different machine mode from the onboard Auto-recipe state our
# own 8001/8004+8002-driven brews put the machine into, which is exactly
# what 40518/40524 target. This coordinator used to send 8018/8019 (and
# 8020/8021 to resume) here — inherited unchanged from the vendored
# PyBloom library's naming, never actually decompile- or hardware-verified
# for this use. See AGENTS.md for the full investigation.
_CMD_RECIPE_PAUSE = 40518
_CMD_RECIPE_RESTART = 40524

# Mode-switch (cmd 11511) hex codes and retry spec. Matches the official
# app's own AppBleManager.sendMessage retry logic, decompiled 2026-07-17
# (com/chisalsoft/andite/manager/AppBleManager.java): 1.5s ACK timeout,
# retry while retryCount < 3 — i.e. up to 4 total sends (1 initial + 3
# retries) before giving up. Confirming the ACK requires _client.py's
# _split_and_parse marker-byte fix (same date) — cmd 11511's response is
# a type-2 frame (marker 0xC2) that was previously silently dropped
# before ever reaching _mode_ack_hex, so this retry loop would otherwise
# always exhaust every attempt for nothing.
#
# The retry itself is further gated on AppDeviceManager.isSleeping()
# (decompiled 2026-07-17, see _client.py's sleep-state-tracking comment):
# createDisposable's ACK-timeout handler only retries while the machine
# last reported itself asleep (cmd 8009/8011/8023) — if it's awake, a
# missed ACK fails immediately on the first timeout, no retry at all.
# _async_switch_mode_with_retry mirrors this via client.is_sleeping().
_MODE_SWITCH_HEX = {"pro": "00000000", "easy": "91327856"}
_MODE_SWITCH_ACK_TIMEOUT_S = 1.5
_MODE_SWITCH_MAX_ATTEMPTS = 4

# General sleep-retry wrapper (coordinator._async_retry_while_sleeping),
# for every other user-triggered action (grind/pour/tare/calibrate/execute
# recipe/easy-slot write) — not just mode-switch. Decompiled 2026-07-17/18:
# AppBleManager's `DefaultTimeOut = 1500L` (the same 1.5s used by
# _MODE_SWITCH_ACK_TIMEOUT_S above) is the *universal* default timeout for
# every command sent via sendMessage()/createDisposable(), not a
# mode-switch-specific value. See _async_retry_while_sleeping's docstring.
_WAKE_RETRY_DELAY_S = 1.5
_WAKE_RETRY_MAX_ATTEMPTS = 4

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

        # Whether the machine is currently showing its own local "start
        # this pod?" prompt (RD_Pods/pod_detected, cmd 40501) — nothing has
        # been armed/executed yet. async_cancel() branches on this to send
        # the one command (8017/quitRecipeStart) the official app itself
        # uses to dismiss that exact prompt, instead of the heavier
        # stop/quit sequence meant for an in-progress recipe.
        self._pod_prompt_active: bool = False

        # Which kind of operation is currently running, if any — one of
        # "recipe" / "manual_grind" / "manual_pour" / None. Lets
        # async_pause_resume()/async_cancel() target the right underlying
        # command family: a manual grind/pour started via async_grind()/
        # async_pour() must use the GrinderController/BrewerController's
        # own pause/restart/stop (cmds 8018/8020/3505 grinder,
        # 8019/8021/4507 brewer — decompile-confirmed real, see AGENTS.md),
        # not the whole-recipe 40518/40524/40519 family, which only applies
        # to an actual recipe execution. Cleared in _dispatch_event() on
        # the matching completion event.
        self._active_operation: Optional[str] = None

        # Track whether we temporarily switched to Pro Mode for an HA
        # operation.  When the operation completes we switch back to the
        # default (Easy) mode so the physical slot buttons work again.
        self._auto_switched_to_pro: bool = False

        # Set just before a user/HA-initiated disconnect so
        # _handle_unexpected_disconnect() can tell it apart from the
        # machine dropping the link on its own (observed on Easy<->Pro
        # mode switches) and skip reconnecting in the former case.
        self._manual_disconnect: bool = False

        # Guards against the silence watchdog spawning a second overlapping
        # _async_force_reconnect() task if it fires again on a later poll
        # tick while the first one is still mid-teardown (disconnect() is
        # awaited, so self.client briefly still reports connected).
        self._force_reconnect_pending: bool = False

    # ------------------------------------------------------------------
    # DataUpdateCoordinator contract
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> Dict[str, Any]:
        """Pull fresh data from the BLE status object (no I/O needed).

        Also drives the connection supervisor, on the same tick cadence as
        the official Android app's AppDeviceManager poll loop (see
        AGENTS.md): reconnect if not connected (unless the user explicitly
        disconnected this session), and force a reconnect if the link has
        gone silent for too long (``_BLE_SILENCE_TIMEOUT_S``).
        """
        if self.client and self.client.is_connected:
            if (
                not self._force_reconnect_pending
                and self.client.seconds_since_last_notification() > _BLE_SILENCE_TIMEOUT_S
            ):
                self._force_reconnect_pending = True
                self.hass.async_create_task(self._async_force_reconnect())
                return {**DEFAULT_STATE}
            try:
                s = self.client.status
                # Never trust the raw water_level_ok flag directly — it's
                # only ever set from the one-shot connect-time
                # RD_MachineInfo snapshot (payload[33]), which multiple
                # firmwares report as False at idle regardless of the
                # tank's real state (see the firmware-quirks section in
                # AGENTS.md). Hardware-reported 2026-07-17: this used to
                # trust the flag once MachineInfo had been observed
                # (proxied by serial_number), which showed a permanent
                # "problem" after a normal reconnect on a unit whose
                # connect-time snapshot happened to read False and never
                # fired a follow-up RD_ErrorLackOfWater (40522) to correct
                # it. Always derive from the event-driven flag instead —
                # it starts optimistic (no shortage) and only flips on an
                # actual water_shortage/water_refilled notification.
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
                if self.client.is_calibrating_grinder():
                    # Highest priority — a deliberate, HA-triggered action
                    # (see async_calibrate_grinder()) we know is actually
                    # running, not inferred from ambiguous telemetry.
                    state_str = "calibrating"
                elif self._no_beans:
                    state_str = "no_beans"
                elif self._water_shortage:
                    state_str = "water_shortage"
                elif raw_label:
                    state_str = raw_label
                else:
                    state_str = s.state.value
                    if state_str == "unknown":
                        # Vendored DeviceState defaults to UNKNOWN and only
                        # ever transitions to IDLE on a Grinder/Brewer
                        # Begin/Stop event (src/xbloom/core/client.py) — on
                        # a connection where the machine has never
                        # ground/brewed yet, nothing ever sets it, so a
                        # genuinely idle, connected machine reports
                        # "unknown" forever (hardware-reported 2026-07-17).
                        # We're inside the `client.is_connected` branch
                        # here, so treat "connected + no error + no
                        # activity ever observed" as idle rather than a
                        # permanent placeholder.
                        state_str = "idle"
                data = {
                    "connected": True,
                    "weight": round(s.scale.weight, 1),
                    # None (not 0.0) when no real reading has ever arrived --
                    # RD_BREWER_TEMPERATURE (8108) rarely fires on some units
                    # (hardware-confirmed 2026-07-15: zero signal across 4
                    # separate brews on one unit), and 0.0C is never a real
                    # brewer reading, so treating it as "unknown" is safe and
                    # avoids showing a misleading temperature.
                    "temperature": round(s.brewer.temperature, 1) if s.brewer.temperature else None,
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
                    # RD_MachineInfo handling. live_grind_size: None until
                    # first observed — 0 (the dataclass default) is never a
                    # real grind size, so it means "not yet seen".
                    "live_grind_size": s.grinder.size or None,
                    # live_grind_speed: 0 IS a real, meaningful reading
                    # (the grinder isn't currently spinning) — unlike grind
                    # size, don't coerce it to None/Unknown. _client.py's
                    # RD_Grinder_Stop handling explicitly zeroes this on
                    # stop so it doesn't linger at a stale nonzero RPM.
                    "live_grind_speed": s.grinder.speed,
                    "voltage": getattr(s, "voltage", None),
                    # Advanced Features (Pour Radius / Vibration Amplitude) —
                    # only populated once a GET/SET response has actually
                    # arrived (client._scan_for_advanced_settings); these
                    # aren't part of the passive telemetry heartbeat.
                    "pour_radius": getattr(s, "pour_radius", None),
                    "vibration_amplitude": getattr(s, "vibration_amplitude", None),
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
        self._maybe_schedule_reconnect()
        return {**DEFAULT_STATE}

    def _maybe_schedule_reconnect(self) -> None:
        """Reconnect backstop for the supervisor poll above.

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
        """
        if self._manual_disconnect or self._connect_lock.locked():
            return
        _LOGGER.debug("XBloom not connected — reconnect supervisor retrying")
        self.hass.async_create_task(self.async_connect())

    async def _async_force_reconnect(self) -> None:
        """Tear down a stale-looking link and reconnect immediately.

        Triggered when the BLE GATT link still reports connected but no
        notification has arrived in over ``_BLE_SILENCE_TIMEOUT_S`` — the
        telemetry stream floods at multi-Hz under normal operation, so a gap
        this large means the link is wedged, not just quiet. Goes through
        ``async_disconnect()`` for proper teardown (cancels the MachineInfo
        retry task, etc.), then immediately clears ``_manual_disconnect``
        again so this doesn't look like a user-requested disconnect to the
        reconnect supervisor above or to ``_handle_unexpected_disconnect``.
        """
        _LOGGER.warning(
            "No BLE notification in over %.0fs — link looks stale, forcing reconnect",
            _BLE_SILENCE_TIMEOUT_S,
        )
        try:
            await self.async_disconnect()
            self._manual_disconnect = False
            await self.async_connect()
        finally:
            self._force_reconnect_pending = False

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
                def _on_status(_status) -> None:
                    if self.hass:
                        self.hass.loop.call_soon_threadsafe(
                            lambda: self.hass.async_create_task(self.async_refresh())
                        )

                client.on_status_update(_on_status)
                client.on_event(self._dispatch_event)

                connected = await client.connect(timeout=20.0)
                if connected:
                    _LOGGER.info("XBloom connected ✓")
                    await self._log_gatt_inventory()
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
                        self.hass.async_create_task(self._async_refresh_advanced_settings())
                    self.client = client
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

        # ── Machine-side unit/water-source change (cmd 8015) ──
        # "settings" is a coordinator-internal category: the event entities
        # filter on "error"/"notification", so this never surfaces there.
        if category == "settings" and event_type == "unit_change":
            if self.hass and self.hass.loop:
                attrs_copy = dict(attributes)
                self.hass.loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(
                        self._async_sync_units_from_machine(attrs_copy)
                    )
                )
            return

        # Drive the water-shortage / no-beans flags from the BLE event stream.
        prev_shortage = self._water_shortage
        prev_no_beans = self._no_beans
        if category == "error" and event_type == "water_shortage":
            self._water_shortage = True
        elif category == "error" and event_type == "no_beans":
            self._no_beans = True
        elif category == "notification" and event_type == "water_refilled":
            # The firmware's own "tank refilled" notification (cmd 40522
            # with value=1 — see _client.py). Without this, the only clear
            # path was a successful brew, which async_execute_recipe's own
            # low-water gate blocks — a deadlock the user could only escape
            # by reconnecting (real-hardware report 2026-07-17).
            self._water_shortage = False
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

        # ── Track the machine's local "start this pod?" prompt ──
        if category == "notification" and event_type == "pod_detected":
            self._pod_prompt_active = True
        elif category == "notification" and event_type in (
            "grinding_started", "brewing_started",
        ):
            # A real brew actually started — the official app's own
            # arm+execute flow never sends 8017, so the prompt is
            # implicitly resolved by this point. Clear the flag so a
            # later cancel doesn't send 8017 mid-brew (never verified
            # safe in that state) instead of the real stop/quit sequence.
            self._pod_prompt_active = False

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
            self._active_operation = None
        elif (
            category == "notification" and event_type == "grinding_complete"
            and self._active_operation == "manual_grind"
        ):
            # Only a *manual* grind is fully done here — a coffee recipe's
            # own grind phase also fires this, but the recipe (brewing
            # next) isn't done yet, so _active_operation stays "recipe"
            # until pour_complete/recipe_complete above.
            self._active_operation = None
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
        """Start a manual pour with current slider values.

        The actual start send is wrapped in ``_async_retry_while_sleeping``
        (2026-07-18, hardware-reported): a pour started while the machine
        was asleep silently did nothing, since nothing resent it — see
        that method's docstring.
        """
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()

            async def _do() -> None:
                # 8007 (RD_BREWER_IN) — "enter pour page" parity with the
                # official app's standalone manual pour screen. Not
                # functionally required (4506 alone is hardware-confirmed
                # sufficient, see AGENTS.md), sent for parity/robustness.
                await self.client._send_command(brewing._CMD_BREWER_IN)
                await self.client.brewer.start(
                    volume=float(self.volume),
                    temperature=float(self.temperature),
                    flow_rate=self.flow_rate,
                    water_source=self.water_source,
                    pattern=self.pour_pattern,
                )

            self._active_operation = "manual_pour"
            await self._async_retry_while_sleeping(_do)
        except Exception as exc:
            _LOGGER.error("Pour error: %s", exc)

    async def async_grind(self) -> None:
        """Start grinding with current slider values.

        See ``async_pour``'s docstring — same sleep-retry wrapping.
        """
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
            self._active_operation = "manual_grind"
            await self._async_retry_while_sleeping(
                lambda: self.client.grinder.start(size=self.grind_size, speed=self.rpm)
            )
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
        # Tea (cmd 4512/4513) doesn't exist on firmware older than
        # V12.0D.300 — the machine would silently ignore it rather than
        # refuse cleanly, so check before touching the machine at all
        # (mode switch included). See MIN_FIRMWARE_TEA's docstring above.
        raw_cup_type = self.recipes[self.selected_recipe].get("cup_type")
        if overrides and "cup_type" in overrides:
            raw_cup_type = overrides["cup_type"]
        if str(raw_cup_type).lower() == "tea" and not _firmware_at_least(
            self.data.get("version"), MIN_FIRMWARE_TEA
        ):
            raise HomeAssistantError(
                f"Tea recipes require XBloom firmware {MIN_FIRMWARE_TEA} or newer "
                f"(current: {self.data.get('version') or 'unknown'})."
            )
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
            self._active_operation = "recipe"
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
            # Sleep-retry wrapped (2026-07-18) — see
            # _async_retry_while_sleeping's docstring. If the machine was
            # asleep, none of this sequence's writes took effect, so
            # retrying the whole thing from the top is safe.
            await self._async_retry_while_sleeping(
                lambda: brewing.async_execute_recipe(
                    self.client, recipe,
                    bypass_volume=bypass_vol,
                    bypass_temperature=bypass_temp,
                )
            )
        except Exception as exc:
            _LOGGER.error("Recipe execute error: %s", exc, exc_info=True)
            self._executing_recipe = False
            self._active_recipe_pours = None
            self._active_operation = None

    async def async_pause_resume(self) -> None:
        """Toggle between pause and resume based on machine state.

        Branches on ``_active_operation`` (2026-07-17): a manual grind or
        pour (started via ``async_grind()``/``async_pour()``) must use the
        ``GrinderController``/``BrewerController``'s own pause/restart
        (cmds 8018/8020 grinder, 8019/8021 brewer — decompile-confirmed
        real, see AGENTS.md), not the whole-recipe pause/restart (40518/
        40524 — see ``_CMD_RECIPE_PAUSE``/``_CMD_RECIPE_RESTART``'s module
        comment), which only applies to an actual recipe execution.

        When the machine is brewing or grinding the button PAUSES.
        When paused the button RESUMES.
        When idle the button is a no-op.
        """
        if not self._check_connected():
            return
        state = (self.data or {}).get("state", "unknown")
        try:
            if self._active_operation == "manual_grind":
                if state == "paused":
                    await self.client.grinder.restart()
                else:
                    await self.client.grinder.pause()
            elif self._active_operation == "manual_pour":
                if state == "paused":
                    await self.client.brewer.restart()
                else:
                    await self.client.brewer.pause()
            else:
                if state == "paused":
                    await self.client._send_command(_CMD_RECIPE_RESTART)
                else:
                    await self.client._send_command(_CMD_RECIPE_PAUSE)
        except Exception as exc:
            _LOGGER.error("Pause/resume error (state=%s): %s", state, exc)

    async def async_cancel(self) -> None:
        """Emergency stop all operations.

        Branches on ``_pod_prompt_active`` (2026-07-17, folded in from a
        separate ``button.dismiss_pod`` — logically the same "cancel"
        action from the user's perspective, just targeting a different
        machine state): if the machine is only showing its own local
        "start this pod?" prompt (RD_Pods/pod_detected) with nothing
        actually armed or executing, the heavier stop/quit sequence below
        doesn't apply — 8017/quitRecipeStart is the one command the
        official app itself uses to dismiss that exact prompt (decompiled
        2026-07-17, see AGENTS.md).

        Also branches on ``_active_operation``: a manual grind or pour
        must be stopped via the ``GrinderController``/``BrewerController``'s
        own ``stop()`` (cmds 3505/4507), not the whole-recipe stop/quit
        sequence below, which targets an actual recipe execution.
        """
        if not self._check_connected():
            return
        active_operation = self._active_operation
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        try:
            if self._pod_prompt_active:
                await brewing.async_dismiss_pod_prompt(self.client)
                self._pod_prompt_active = False
            elif active_operation == "manual_grind":
                await self.client.grinder.stop()
            elif active_operation == "manual_pour":
                await self.client.brewer.stop()
            else:
                await self.client.stop_recipe()
                await asyncio.sleep(0.3)
                await self.client.grinder.stop()
                await self.client.brewer.stop()
                await asyncio.sleep(0.3)
                # Reset the machine's UI/mode state to the home screen.
                # Without this the machine stays in whatever screen was
                # active (e.g. tea recipe UI) after the hardware stops.
                await self.client._send_command(brewing._CMD_BACK_TO_HOME)
        except Exception as exc:
            _LOGGER.error("Cancel error: %s", exc)
        self._active_operation = None
        # Restore the user's persisted mode if we had auto-switched to Pro
        # for an HA operation that is now cancelled.
        await self._restore_persisted_mode("cancel")

    async def _apply_unit_preferences(self, client=None) -> None:
        """Push the configured display units (8005 weight, 8010 temp) and
        water-feed setting (4508) to the machine, once per connection.

        The 8005/8010 ACKs carry no echoed value (confirmed live
        2026-07-04), so this re-asserts the stored preferences on every
        fresh connection; changes made on the machine's own touchscreen
        *while connected* flow back via cmd 8015 (RD_UNIT_CHANGE — see
        _async_sync_units_from_machine) and update the stored values, so
        the re-assert never fights an in-session machine-side change.
        Never raises; a failure here shouldn't block the rest of
        async_connect().

        ``client`` lets ``async_connect()`` pass its own local client
        reference instead of this method reading ``self.client`` —
        hardware-reported 2026-07-17: a disconnect racing in mid-connect
        (see ``async_connect()``'s docstring) could null ``self.client``
        out from under this call, crashing with ``'NoneType' object has
        no attribute '_send_command_raw'`` instead of a clean "not
        connected" error. Defaults to ``self.client`` for the other call
        site (``_handle_unit_options_change``), which already checks
        ``self.client.is_connected`` immediately before scheduling this.
        """
        client = client or self.client
        try:
            weight_code = WEIGHT_UNIT_OPTIONS.get(self._weight_unit, WEIGHT_UNIT_OPTIONS["g"])
            await client._send_command_raw(8005, bytes([weight_code]), type_code=1)
            temp_code = TEMP_UNIT_OPTIONS.get(self._temp_unit, TEMP_UNIT_OPTIONS["c"])
            await client._send_command_raw(8010, bytes([temp_code]), type_code=1)
            await client._send_command(_CMD_SWITCH_WATER_FEED, [self.water_source])
            _LOGGER.info(
                "Applied display units: weight=%s temp=%s water_source=%d",
                self._weight_unit, self._temp_unit, self.water_source,
            )
        except Exception as exc:
            _LOGGER.warning("Failed to apply display unit preferences: %s", exc)

    def _persist_unit_options(self) -> None:
        """Persist the current unit/water-source values to entry.options.

        All three keys are in __init__.py's _NO_RELOAD_OPTION_KEYS, so
        this never reloads the entry (and therefore never drops the BLE
        connection). No-op if the options already match.
        """
        from .const import CONF_TEMP_UNIT, CONF_WATER_SOURCE, CONF_WEIGHT_UNIT

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

    async def async_set_water_source(self, value: int) -> None:
        """Set the machine's water-feed setting (cmd 4508) and persist it.

        Unlike the pre-2026-07-17 behavior (an HA-local preference only
        used in the manual-pour payload), this writes the machine's own
        setting — the same command the official app's water-source screen
        sends — so the machine's own water-shortage logic follows suit.
        If not connected, the value is still persisted and applied on the
        next connection by _apply_unit_preferences().
        """
        if value not in (WATER_SOURCE_TANK, WATER_SOURCE_DIRECT):
            raise ValueError(f"water_source must be 0 or 1, got {value!r}")
        self.water_source = value
        if self.client and self.client.is_connected:
            try:
                await self.client._send_command(_CMD_SWITCH_WATER_FEED, [value])
            except Exception as exc:
                _LOGGER.error("Water-source switch (4508) send error: %s", exc)
        self._persist_unit_options()
        self.async_update_listeners()

    async def _async_sync_units_from_machine(self, attrs: dict) -> None:
        """Fold a machine-reported unit/water-source change (cmd 8015,
        RD_UNIT_CHANGE — fired when they're changed on the machine's own
        touchscreen) back into the stored preferences, so the next
        connection's _apply_unit_preferences() re-asserts what the machine
        actually shows instead of a stale value.
        """
        weight = _RAW_TO_WEIGHT_UNIT.get(attrs.get("weight_unit"))
        temp = _RAW_TO_TEMP_UNIT.get(attrs.get("temp_unit"))
        water = attrs.get("water_source")
        changed = False
        if weight is not None and weight != self._weight_unit:
            self._weight_unit = weight
            changed = True
        if temp is not None and temp != self._temp_unit:
            self._temp_unit = temp
            changed = True
        if water in (WATER_SOURCE_TANK, WATER_SOURCE_DIRECT) and water != self.water_source:
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
        echo of our own _persist_unit_options() (select entity or an 8015
        sync) — nothing to apply. Otherwise adopt the new values and, if
        connected, push them to the machine right away; a reload used to do
        that implicitly by reconnecting.
        """
        from .const import CONF_TEMP_UNIT, CONF_WATER_SOURCE, CONF_WEIGHT_UNIT

        weight = options.get(CONF_WEIGHT_UNIT, self._weight_unit)
        temp = options.get(CONF_TEMP_UNIT, self._temp_unit)
        water = options.get(CONF_WATER_SOURCE, self.water_source)
        if (weight, temp, water) == (self._weight_unit, self._temp_unit, self.water_source):
            return
        self._weight_unit = weight
        self._temp_unit = temp
        self.water_source = water
        if self.client and self.client.is_connected:
            self.hass.async_create_task(self._apply_unit_preferences())

    async def _async_switch_mode_with_retry(self, mode: str) -> bool:
        """Send the mode-switch command (11511) and confirm it landed via
        its ACK (``_mode_ack_hex``), retrying on timeout.

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
                if getattr(self.client.status, "_mode_ack_hex", None) == target_hex:
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
        if not self._check_connected():
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
            from .const import CONF_MODE
            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if entry is not None:
                new_options = {**entry.options, CONF_MODE: mode}
                self.hass.config_entries.async_update_entry(entry, options=new_options)
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
            await self._async_switch_mode_with_retry("easy")
            self._auto_switched_to_pro = False
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
                await self._async_switch_mode_with_retry("pro")
                self._auto_switched_to_pro = True
                await self.async_refresh()
            except Exception as exc:
                _LOGGER.warning("Pro-mode switch failed: %s", exc)

    async def _async_retry_while_sleeping(
        self, action: Callable[[], Awaitable[None]]
    ) -> None:
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
        """
        for attempt in range(1, _WAKE_RETRY_MAX_ATTEMPTS + 1):
            await action()
            if not (self.client and self.client.is_sleeping()):
                return
            if attempt < _WAKE_RETRY_MAX_ATTEMPTS:
                _LOGGER.info(
                    "Action sent while machine reports asleep — retrying "
                    "(attempt %d/%d)", attempt, _WAKE_RETRY_MAX_ATTEMPTS,
                )
                await asyncio.sleep(_WAKE_RETRY_DELAY_S)

    async def async_tare_scale(self) -> None:
        """Zero the scale (cmd 8500). See ``async_pour``'s docstring —
        same sleep-retry wrapping."""
        if not self._check_connected():
            return
        try:
            await self._async_retry_while_sleeping(lambda: brewing.async_tare(self.client))
        except Exception as exc:
            _LOGGER.error("Tare error: %s", exc)

    async def async_calibrate_grinder(self) -> None:
        """Trigger the grinder gear-position calibration sweep (cmd 3502).

        Split back out from ``async_set_advanced_settings`` into its own
        ``button.calibrate_grinder`` on 2026-07-17 — a plain button fits
        a one-shot trigger action better than a settings-values service,
        and sidesteps ``config_entry_id`` service-call resolution
        entirely (unrelated hardware report the same day found that
        resolution was broken for *every* service — see
        ``__init__.py``'s ``_coordinators_for_call`` — reinforcing that a
        button was the simpler, more robust choice here regardless).

        Sets ``is_calibrating_grinder`` and fires
        ``grinder_calibration_started`` here, at send time, rather than
        waiting for the machine's own 50038 (RD_CalibrateStart) push —
        hardware-confirmed 2026-07-17 that 50038 never arrived at all
        during a real calibration run on at least one unit, which would
        otherwise leave the whole calibration flow (state, events,
        completion detection) silently inert.

        Completion is ``RD_CurrentGrinder`` (40526) reporting exactly 85
        (see _client.py) — the *only* signal the official app's own
        ``CalibrateGrinderActivity.onEventBusEvent`` checks (decompiled
        2026-07-17). Also schedules ``_async_calibration_timeout_fallback``,
        mirroring the same activity's own 180s client-side timeout
        (``Observable.just(0).delay(180000, MILLISECONDS)``) so a lost or
        delayed 85 reading doesn't leave ``is_calibrating_grinder`` (and
        ``sensor.state == "calibrating"``) stuck forever. ``RD_Grinder_Stop``
        is deliberately *not* a completion signal — an earlier version of
        this fix treated it as one, but hardware-confirmed 2026-07-17 (a
        second, longer test) that it fires within ~5s of send as part of
        the calibration sequence's own startup/homing move, a full minute
        before the real 85 reading arrives; treating it as "done" closed
        the gate early and made the genuine completion event unreachable.
        """
        if not self._check_connected():
            return
        try:
            # Only the raw send is retried while asleep (see
            # _async_retry_while_sleeping's docstring) — the bookkeeping
            # below must run exactly once regardless of how many attempts
            # the send took, or a retry would fire a duplicate
            # "grinder_calibration_started" event and schedule a second,
            # redundant 180s timeout fallback task.
            await self._async_retry_while_sleeping(self.client.async_calibrate_grinder)
            self.client.status.is_calibrating_grinder = True
            self.client._fire_event("notification", "grinder_calibration_started")
            await self.async_refresh()
            self.hass.async_create_task(self._async_calibration_timeout_fallback())
        except Exception as exc:
            _LOGGER.error("Calibrate grinder error: %s", exc)

    async def _async_calibration_timeout_fallback(self) -> None:
        """Mirror CalibrateGrinderActivity's own 180s client-side timeout:
        if the real completion signal (RD_CurrentGrinder == 85) hasn't
        arrived within 180s of send, declare it done anyway rather than
        leaving ``is_calibrating_grinder``/``sensor.state == "calibrating"``
        stuck indefinitely. A no-op if the real signal already cleared the
        flag (the common case) before this fires.
        """
        await asyncio.sleep(180)
        if self.client.is_calibrating_grinder():
            self.client.status.is_calibrating_grinder = False
            self.client._fire_event("notification", "grinder_calibration_complete")
            await self.async_refresh()

    async def _async_refresh_advanced_settings(self) -> None:
        """Fire-and-forget GET for pour_radius/vibration_amplitude, once
        per connect. These are request/response (not passive telemetry),
        so nothing populates the two sensors until this runs — see
        _client.py's CMD_GET_POUR_RADIUS module comment.

        Logged at INFO on our own logger (not the vendored xbloom.core.client
        one the SEND/RECV CMD lines use) — hardware debugging 2026-07-17
        found a real user setup where xbloom.core.client's output was
        entirely suppressed (a per-logger level override silencing that
        specific noisy namespace, common for the multi-Hz telemetry it
        logs) while custom_components.xbloom.* stayed visible, making the
        whole GET/response cycle unobservable without this.

        Callers must only invoke this once ``self.client.status.serial_number``
        is populated (RD_MachineInfo has actually arrived) — hardware-
        confirmed 2026-07-17 on the exact same user setup: firing this
        unconditionally right after ``client.connect()`` returns can lose
        the response entirely on a firmware that needs a *second* 8100
        handshake before MachineInfo shows up (the same "machine isn't
        really awake yet" quirk documented for the initial connect
        handshake — see AGENTS.md). This request/response command is just
        as vulnerable to that dead window as MachineInfo itself, so it's
        gated on the same signal (see ``async_connect``/
        ``_machine_info_retry_loop``, both of which now only call this
        once serial_number is confirmed non-empty).

        The two GETs need at least ~0.5s between them — hardware-confirmed
        2026-07-17 (four repeated trials on a real machine): a 0.3s gap
        made the vibration_amplitude GET consistently get no response at
        all (pour_radius always succeeded; the machine appears to still be
        busy replying to the first request when the second arrives, and
        silently drops it rather than queuing it), while 0.6s/1.0s/1.5s
        gaps all succeeded consistently. 0.8s below is used for margin.
        """
        _LOGGER.info("Requesting pour_radius / vibration_amplitude (cmd 11506/11508)…")
        try:
            await self.client.async_get_pour_radius()
            await asyncio.sleep(0.8)
            await self.client.async_get_vibration_amplitude()
            _LOGGER.info("Advanced settings GET sent (pour_radius/vibration_amplitude)")
        except Exception as exc:
            _LOGGER.warning("Advanced settings refresh failed: %s", exc)

    async def async_set_advanced_settings(
        self,
        *,
        pour_radius_level: Optional[int] = None,
        vibration_amplitude_level: Optional[int] = None,
        display_brightness_level: Optional[int] = None,
    ) -> dict:
        """Advanced Features — pour radius / vibration amplitude / display
        brightness, grouped into one service (matching the official app's
        own "Advanced Features" screen) rather than several always-visible
        entities for settings nobody adjusts often. At least one action
        must be requested.

        Grinder calibration used to be a fourth field here
        (``calibrate_grinder``) but was split back out to its own
        ``button.calibrate_grinder``/``async_calibrate_grinder()`` on
        2026-07-17 — hardware-reported: a real call with a real
        ``config_entry_id`` failed with "No XBloom machine matched the
        service call," which turned out to be an unrelated pre-existing
        bug in ``_coordinators_for_call`` (fixed the same day, see
        ``__init__.py``), but the report was reason enough to also
        reconsider bundling a one-shot trigger action into a
        settings-values service in the first place — a plain button is a
        better fit for "press to fire," and doesn't depend on
        ``config_entry_id`` resolution at all.

        Levels, not raw device values — mirrors the official app's own
        L1-L5 / L1-L6 / L1-L3 picker UIs (decompiled 2026-07-16, see
        AGENTS.md) rather than asking users to type an opaque number:

        - ``vibration_amplitude_level`` (0-5, L1-L6): a fixed absolute
          scale, ``raw = 1000 + level * 100`` — no ambiguity, matches
          MachineSetVibrationAmplitudeActivity exactly.
        - ``display_brightness_level`` (1-3, L1-L3): 3 fixed presets,
          ``raw`` one of 1/8/15 (see ``_client.CMD_SET_DISPLAY_BRIGHTNESS``)
          — matches MachineDisplayActivity exactly, also no ambiguity (no
          GET counterpart either — the official app tracks the current
          value from its own account/device record, not a fresh BLE read,
          so there's nothing for this integration to poll).
        - ``pour_radius_level`` (0-4, L1-L5): the official app centers
          these 5 levels on a **per-device factory value**
          (``Device.pouringRadiusInit``), fetched from xBloom's cloud
          account (see ``_cloud_client.get_pour_radius_init_center`` —
          reverse-engineered 2026-07-16, live-verified the same day
          against a real account/device, member_id 23237/serial
          J15A01B4CV030 returned a real 750). **Requires a logged-in
          cloud account** — rejected up front (``cloud_login_required``)
          otherwise, rather than silently substituting the current
          ``pour_radius`` reading as an approximate center; that
          approximation only holds on a machine nobody has ever changed
          the level on before, which isn't something this integration can
          verify, so it's no longer used. Still untested on real
          hardware — the BLE `SET` side (`11507`) is unverified even
          though the cloud lookup that feeds it now is.
        """
        if (
            pour_radius_level is None
            and vibration_amplitude_level is None
            and display_brightness_level is None
        ):
            return {
                "success": False,
                "error": "no_action",
                "message": "Specify at least one of pour_radius_level, vibration_amplitude_level, or display_brightness_level.",
            }
        if pour_radius_level is not None and not 0 <= pour_radius_level <= 4:
            return {
                "success": False,
                "error": "invalid_level",
                "message": "pour_radius_level must be 0-4 (L1-L5).",
            }
        if vibration_amplitude_level is not None and not 0 <= vibration_amplitude_level <= 5:
            return {
                "success": False,
                "error": "invalid_level",
                "message": "vibration_amplitude_level must be 0-5 (L1-L6).",
            }
        if display_brightness_level is not None and not 1 <= display_brightness_level <= 3:
            return {
                "success": False,
                "error": "invalid_level",
                "message": "display_brightness_level must be 1-3 (L1-L3).",
            }
        if pour_radius_level is not None and not self.cloud_client.logged_in:
            # Required, not opportunistic: without the cloud-fetched real
            # factory-default center, "level 2" is only an approximation
            # (the current value at call time) — see
            # _cloud_client.get_pour_radius_init_center's docstring. Reject
            # up front rather than silently shipping an unreliable value.
            return {
                "success": False,
                "error": "cloud_login_required",
                "message": "pour_radius_level requires an XBloom cloud account login (Options → Account) — this integration has no other way to know the machine's factory-default pour-radius center.",
            }
        if not self._check_connected():
            return {
                "success": False,
                "error": "not_connected",
                "message": "The XBloom is not connected over Bluetooth.",
            }
        try:
            if pour_radius_level is not None:
                current = self.data.get("pour_radius")
                if current is None:
                    await self.client.async_get_pour_radius()
                    await asyncio.sleep(0.5)
                    current = self.data.get("pour_radius")
                if current is None:
                    return {
                        "success": False,
                        "error": "pour_radius_unknown",
                        "message": "Could not read the current pour radius from the machine — try again once connected.",
                    }
                serial = self.data.get("serial_number")
                if not serial:
                    return {
                        "success": False,
                        "error": "serial_unknown",
                        "message": "The machine's serial number isn't known yet — try again once MachineInfo has been read.",
                    }
                center = await self.cloud_client.get_pour_radius_init_center(serial, current)
                if center is None:
                    return {
                        "success": False,
                        "error": "cloud_center_unavailable",
                        "message": "Could not fetch the factory-default pour-radius center from XBloom's cloud account — try again later.",
                    }
                await self.client.async_set_pour_radius(
                    _pour_radius_level_to_raw(pour_radius_level, center)
                )
                # 0.8s, not 0.3s -- hardware-confirmed 2026-07-17 (same
                # finding as the pour_radius/vibration_amplitude GET pair
                # in _async_refresh_advanced_settings): a 0.3s gap between
                # two back-to-back type-2 commands consistently drops the
                # second one's ACK; 0.8s consistently succeeds.
                await asyncio.sleep(0.8)
            if vibration_amplitude_level is not None:
                await self.client.async_set_vibration_amplitude(
                    _vibration_level_to_raw(vibration_amplitude_level)
                )
                await asyncio.sleep(0.8)
            if display_brightness_level is not None:
                await self.client.async_set_display_brightness(display_brightness_level)
                await asyncio.sleep(0.3)
        except Exception as exc:
            _LOGGER.error("Advanced settings error: %s", exc, exc_info=True)
            return {
                "success": False,
                "error": "write_failed",
                "message": f"Advanced settings call failed: {exc}",
            }
        await self.async_refresh()
        return {"success": True}

    async def async_write_easy_slot(
        self, slot_letter: str, identifier: Optional[str] = None
    ) -> dict:
        """Write a recipe to Easy Mode slot A/B/C (11510, type-2 packet).

        ``identifier`` (uid / cloud table id / share URL/id / name)
        selects the recipe; omitted, the currently-selected recipe (the
        Recipe ``select`` entity) is written — that's what the slot
        button entities do. A share URL/id not present locally is
        auto-imported first (clone + uid), so "write this shared recipe
        to slot B" is one call. On success **only the target letter's**
        slot → recipe mapping is persisted in ``entry.options["easy_slots"]``
        so the slot text entities can show (and restore) what HA last
        *intentionally* wrote; the machine itself never reports slot
        contents.

        Live-verified 2026-07-15 (cross-referenced against
        Janczykkkko/xbloom-ble's independent capture): the machine only
        *persists* a slot when all three (A/B/C) are written together —
        writing one alone leaves it hung at "saving" (RETRY) — and only
        accepts slot writes in Pro Mode. So this call fills in the other
        two slots from ``entry.options["easy_slots"]`` (falling back to
        the target recipe for a slot HA has never written — the machine
        has no readback, so there's nothing else to preserve it with),
        force-switches to Pro Mode if needed, writes all three, then
        restores whatever mode the machine was in before. That fallback
        recipe *is* sent to the machine for an unwritten slot (there's no
        other valid payload to send), but it is deliberately **not**
        recorded as that slot's own assignment — otherwise the first
        write to any slot would make every other never-configured slot's
        sensor falsely flip from unknown to "registered" too (hardware-
        confirmed 2026-07-17: writing only slot A with B/C both unknown
        made all three sensors show as registered).
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

        # Auto/Easy Mode (cmd 11510/11511/11512) doesn't exist on firmware
        # older than V12.0D.210 — check before any mode-switch/slot-write
        # BLE traffic. See MIN_FIRMWARE_EASY_MODE's docstring above.
        if not _firmware_at_least(self.data.get("version"), MIN_FIRMWARE_EASY_MODE):
            return {
                "success": False,
                "error": "firmware_too_old",
                "message": (
                    f"Easy Mode requires XBloom firmware {MIN_FIRMWARE_EASY_MODE} "
                    f"or newer (current: {self.data.get('version') or 'unknown'})."
                ),
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
                await self._async_switch_mode_with_retry("pro")
                switched_to_pro = True

            # Sleep-retry wrapped (2026-07-18) — see
            # _async_retry_while_sleeping's docstring.
            await self._async_retry_while_sleeping(
                lambda: brewing.async_write_easy_slots(self.client, slot_recipes)
            )
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
                    await self._async_switch_mode_with_retry("easy")
                    await self.async_refresh()
                except Exception as exc:
                    _LOGGER.warning("Restoring Easy Mode after slot write failed: %s", exc)

        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is not None:
            slots = dict(entry.options.get(CONF_EASY_SLOTS) or {})
            # Only the target letter was actually requested by the user —
            # the other two were mirrored purely to satisfy the hardware's
            # all-three-at-once write requirement above. Recording them
            # here too would make untouched slots' sensors falsely show as
            # "registered" the first time any slot is written.
            slots[target_letter] = {
                "uid": slot_raws[target_letter].get("uid"),
                "name": slot_names[target_letter],
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
        contain these characters. A bare all-digit string is also treated
        as a possible ref (a collective.xbloom.com community recipe id —
        see fetch_shared_recipe's docstring); by the time this heuristic
        runs, find_recipe has already tried it as a local cloud table id
        and failed, so this only risks one extra (cleanly-failing) network
        round-trip for the rare purely-numeric recipe name, not a wrong
        match.
        """
        s = identifier.strip()
        return "://" in s or any(c in s for c in "%=+/") or s.isdigit()

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
            # cup_type="Omni" only -- the collective hub's cup-type facet
            # also has a same-ish-sounding "Omni Tea Brewer" entry (its
            # actual name on the hub is "Omni Brewer"), which is the tea
            # accessory (our CupType.TEA), not a coffee cup type. Coffee
            # brewing never uses that cup type, and tea already has its
            # own curated defaults in default_recipes.py plus the
            # dedicated execute_tea_recipe path -- this seed should only
            # ever contribute coffee recipes.
            official = await self.cloud_client.fetch_official_recipes(
                limit=_OFFICIAL_RECIPE_SYNC_LIMIT, cup_type=["Omni"]
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

    def _sub_device_info(self, key: str) -> DeviceInfo:
        """Child DeviceInfo for a physical sub-component (grinder/scale/brewer).

        Same config entry, separate device-registry entry — nested under
        the main device via ``via_device`` so its page only shows that
        component's entities instead of everything at once. unique_ids
        are untouched, so this is a pure device-registry regrouping: no
        entity_id changes, no automation/dashboard breakage.

        ``translation_key`` (not a literal ``name``) + the top-level
        ``device.<key>.name`` block in strings.json/translations — a
        literal ``name`` would ship English-only device names regardless
        of the user's HA UI language (confirmed live 2026-07-15: showed
        untranslated "Grinder"/"Scale"/"Brewer" on a Korean-language
        instance).

        ``via_device`` only nests the device-registry entry under the
        main device (the "connected via" grouping on its page) — HA does
        NOT propagate area assignment through it (confirmed live
        2026-07-16: setting the main device's area left the sub-devices
        unassigned). ``suggested_area`` fills that gap for first-time
        creation only: it pre-fills the sub-device's area with whatever
        the main device is *currently* assigned to, without overriding a
        later manual change on either device — same one-time-only
        semantics HA already uses for the initial area suggestion on
        newly discovered devices.
        """
        info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{key}")},
            translation_key=key,
            manufacturer="XBloom",
            via_device=(DOMAIN, self.entry_id),
        )
        if self.hass:
            main_device = dr.async_get(self.hass).async_get_device(
                identifiers={(DOMAIN, self.entry_id)}
            )
            if main_device and main_device.area_id:
                area = ar.async_get(self.hass).async_get_area(main_device.area_id)
                if area:
                    info["suggested_area"] = area.name
        return info

    @property
    def grinder_device_info(self) -> DeviceInfo:
        return self._sub_device_info("grinder")

    @property
    def scale_device_info(self) -> DeviceInfo:
        return self._sub_device_info("scale")

    @property
    def brewer_device_info(self) -> DeviceInfo:
        return self._sub_device_info("brewer")

    @property
    def recipe_names(self) -> list[str]:
        return list(self.recipes.keys()) if self.recipes else ["No recipes configured"]
