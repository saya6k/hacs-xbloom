"""Shared constants and pure helper functions for the coordinator package.

Phase 3 of the de-vendoring refactor: split out of the former monolithic
coordinator.py — see AGENTS.md and adr/001-clean-room-reimplementation-of-xbloom-ble.md.
Structural only; no behavior changed by this split.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

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

# Reconnect-supervisor backoff. Without it the supervisor retries on every
# poll tick forever, which floods the log with an ERROR every ~5s for as long
# as the machine is off or out of range (observed 2026-07-19 on a real HA run).
# The nth consecutive failure blocks the *supervisor* for
# min(5 * 2**(n-1), _RECONNECT_BACKOFF_MAX_S) seconds; on-demand connects
# (_async_ensure_connected) deliberately ignore the gate, so a user action
# still reconnects immediately. Reset on any successful connect.
_RECONNECT_BACKOFF_BASE_S = 5.0
_RECONNECT_BACKOFF_MAX_S = 300.0

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
# retries) before giving up. Confirming the ACK requires ble/client.py's
# _split_and_parse marker-byte fix (same date) — cmd 11511's response is
# a type-2 frame (marker 0xC2) that was previously silently dropped
# before ever reaching _mode_ack_hex, so this retry loop would otherwise
# always exhaust every attempt for nothing.
#
# The retry itself is further gated on AppDeviceManager.isSleeping()
# (decompiled 2026-07-17, see ble/client.py's sleep-state-tracking comment):
# createDisposable's ACK-timeout handler only retries while the machine
# last reported itself asleep (cmd 8009/8011/8023) — if it's awake, a
# missed ACK fails immediately on the first timeout, no retry at all.
# _async_switch_mode_with_retry mirrors this via client.is_sleeping().
_MODE_SWITCH_HEX = {"pro": "00000000", "easy": "91327856"}
_MODE_SWITCH_ACK_TIMEOUT_S = 1.5
# Same sendMessage retry mechanism as _WAKE_RETRY_MAX_ATTEMPTS below —
# 3 total sends per the app (retryCount starts at 1, resends while < 3).
_MODE_SWITCH_MAX_ATTEMPTS = 3

# General sleep-retry wrapper (coordinator._async_retry_while_sleeping),
# for every other user-triggered action (grind/pour/tare/calibrate/execute
# recipe/easy-slot write) — not just mode-switch. Decompiled 2026-07-17/18:
# AppBleManager's `DefaultTimeOut = 1500L` (the same 1.5s used by
# _MODE_SWITCH_ACK_TIMEOUT_S above) is the *universal* default timeout for
# every command sent via sendMessage()/createDisposable(), not a
# mode-switch-specific value — every one of the app's commands goes
# through the identical "on ACK timeout, resend the same command while
# isSleeping() is true, up to 3 retries (4 total sends); the instant it's
# not sleeping, stop" pattern this integration had only implemented for
# mode-switch. Hardware-reported 2026-07-17: commands sent while the
# machine was asleep silently did nothing, since nothing else retried.
#
# We have no per-command ACK to wait on the way the app's own
# response-correlation system does — our writes are write-without-response
# and most commands here have no dedicated confirmation notification (mode
# switch is the one exception, via mode_ack_hex) — so unlike
# _async_switch_mode_with_retry, this generic wrapper can't verify the
# retried send actually landed; it only knows whether the machine is still
# reporting itself asleep after the wait, the same signal the app itself
# gates its own retry on. Values kept in sync with the mode-switch
# constants above (same underlying DefaultTimeOut) but named separately
# since they're a distinct, more approximate retry mechanism.
_WAKE_RETRY_DELAY_S = 1.5
# 3 total sends, not 4 — miscounted before the AppBleManager decompile was
# re-read (2026-07-19): its timeout path resends only while
# retryCount < 3 with retryCount starting at 1, i.e. initial + 2 retries.
_WAKE_RETRY_MAX_ATTEMPTS = 3

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
