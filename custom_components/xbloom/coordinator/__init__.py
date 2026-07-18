"""XBloomCoordinator — manages BLE lifecycle and state.

Package split from a single ~2900-line coordinator.py (Phase 3 of the
de-vendoring refactor, structural only — see AGENTS.md and
adr/001-clean-room-reimplementation-of-xbloom-ble.md). Composed via mixins
so every method body carried over unchanged from the original file; this
module defines only ``__init__`` and the handful of methods too small to
warrant their own module (connectivity check, device-registry properties).

- ``connection.py`` — connect/disconnect, reconnect supervisor, silence
  watchdog, mode switching, display-unit/water-source sync.
- ``state.py`` — the ``DataUpdateCoordinator`` contract (state derivation)
  and BLE event dispatch.
- ``recipes.py`` — recipe selection/execution, Easy Mode slot writes,
  local recipe store CRUD, cloud import/export/search.
- ``advanced_settings.py`` — pour radius / vibration amplitude / display
  brightness / grinder calibration.
- ``operations.py`` — manual grind/pour/tare and pause/resume/cancel.

The composed ``XBloomCoordinator`` class is still the single object every
entity/service/LLM tool imports and calls — its public method surface is
unchanged from the pre-split file.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .._cloud_client import XBloomCloudClient
from ..ble.client import XBloomClient
from ..const import DEFAULT_MODE, DEFAULT_TEMP_UNIT, DEFAULT_WATER_SOURCE, DEFAULT_WEIGHT_UNIT, DOMAIN
from .advanced_settings import AdvancedSettingsMixin
from .connection import ConnectionMixin
from .operations import OperationsMixin
from .recipes import RecipesMixin
from .state import StateMixin

# Re-exported for backward-compatible imports — other modules import these
# names via `from .coordinator import X` (now a package, same import path).
from .constants import (  # noqa: F401
    DEFAULT_STATE,
    MIN_FIRMWARE_EASY_MODE,
    MIN_FIRMWARE_TEA,
    POUR_PATTERN_OPTIONS,
    TEMP_UNIT_OPTIONS,
    WATER_SOURCE_DIRECT,
    WATER_SOURCE_OPTIONS,
    WATER_SOURCE_TANK,
    WEIGHT_UNIT_OPTIONS,
    _firmware_at_least,
    _firmware_build,
    _pour_radius_level_to_raw,
    _vibration_level_to_raw,
)

_LOGGER = logging.getLogger(__name__)


class XBloomCoordinator(
    ConnectionMixin,
    StateMixin,
    RecipesMixin,
    AdvancedSettingsMixin,
    OperationsMixin,
    DataUpdateCoordinator[Dict[str, Any]],
):
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
        # ble/client.py/_dispatch_event below). Cleared on recipe completion
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
        # WEIGHT_UNIT_OPTIONS/TEMP_UNIT_OPTIONS). Only pushed to the machine
        # (_apply_unit_preferences) when _unit_preferences_dirty is set — see
        # that flag's own comment for why this isn't unconditional per
        # connection anymore.
        self._weight_unit: str = initial_weight_unit
        self._temp_unit: str = initial_temp_unit

        # Set whenever a unit/water-source preference is changed via the
        # config_flow Settings step while not connected (connection.py's
        # _handle_unit_options_change) — the change is stored locally but
        # couldn't be pushed to the machine yet. async_connect() checks this
        # and pushes once, then clears it. Deliberately NOT set on every
        # connect: the official app (decompiled 2026-07-18, MachineJ15Fragment)
        # only ever sends the 8005/8010/4508 SET commands from an explicit
        # button tap in its own Settings screen, never automatically on
        # connect — hardware-reported that unconditionally resending them on
        # every reconnect (the previous behavior) made the machine's own
        # unit-settings screen pop up first on every single reconnect, since
        # receiving those SET commands is indistinguishable to the firmware
        # from a user tapping that screen's buttons.
        self._unit_preferences_dirty: bool = False

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

        # Two-stage arm/confirm manual button flow (2026-07-18) — a first
        # button press queues the operation on the machine (enter grinder/
        # pour mode, or queue a recipe) without starting anything
        # irreversible, giving the user time to place a cup etc.; a second
        # press on the SAME button sends the actual go/start command.
        # HA-button-only by design (button.py) — the execute_recipe /
        # execute_tea_recipe services, async_grind()/async_pour(), and
        # every LLM tool still act in one call, unchanged. One of "grind" /
        # "pour" / "recipe" / None. No timeout: stays armed until confirmed
        # or cancelled (async_cancel() clears it via a Back to Home reset).
        # sensor.state surfaces it as "armed_grind"/"armed_pour"/
        # "armed_recipe" (see state.py) so the user knows a second press is
        # needed.
        self._armed_operation: Optional[str] = None
        # Only meaningful while _armed_operation == "recipe" — which go
        # command async_confirm_recipe() must send, and (tea only) the
        # exact payload bytes 4512 must re-send (brewing.async_confirm_recipe
        # can't rebuild them itself; the firmware expects the identical
        # bytes from the matching 4513).
        self._armed_recipe_is_tea: bool = False
        self._armed_recipe_tea_payload: Optional[bytes] = None

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
