---
name: xbloom-grinder-calibration-completion-signal-saga
description: "Six-round debugging saga to correctly detect grinder calibration completion - wrong RD_Grinder_Stop signal, a duplicate implementation, a sensor ENUM crash, and noisy generic grinding events all had to be found and fixed via repeated hardware feedback before the real signal (RD_CurrentGrinder==85) worked cleanly."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Grinder calibration (trigger: cmd `3502`, see
[[xbloom-advanced-features-jadx-findings]]) took six rounds of real
hardware feedback to get right — each round fixed a genuine bug that the
previous round's fix had either introduced or failed to catch.

**Round 1**: 50038/50039 (`RD_CalibrateStart`/`RD_Calibrating`, best-effort
start/progress pulses) never arrived at all during a real ~120s calibration
run on at least one unit, so a design that only sets `is_calibrating_
grinder` on receiving 50038 never fires the started/progress/complete
events. Fixed: `async_calibrate_grinder()` sets the flag and fires
`grinder_calibration_started` itself at **send** time; 50038/50039 stay
wired as best-effort bonus signals only.

**Round 2 (duplicate implementation)**: a prior session had already added
`async_set_advanced_settings(calibrate_grinder=True)` using cmd 3502; a
later session, searching for prior art with a case-sensitive `CALIBRATE`
grep, missed it and built a second, redundant `button.calibrate_grinder` +
`brewing.async_calibrate_grinder()` trigger path before the duplication was
caught and reverted the same day.

**Round 3 (sensor crash)**: `"calibrating"` was added to the state-
derivation chain and translation files but never to `sensor.py`'s
`XBloomStateSensor._attr_options` (the `SensorDeviceClass.ENUM` allow-list)
— pressing the button crashed `async_write_ha_state()` on **every**
coordinator refresh (multi-Hz telemetry stream) for the whole ~120s window.
User's report of this crash ("그냥 버튼으로 원복하고 advanced settings에서는
이걸 삭제해") is also what triggered re-splitting calibration back out of
`advanced_settings` into its own standalone `button.calibrate_grinder` —
a button doesn't depend on `config_entry_id` resolution (see
[[xbloom-service-config-entry-targeting]], a separate bug reported at the
same time) and matches how every other one-shot action (cancel, tare,
grind, pour) in this integration is exposed. Fixed the crash by adding
`"calibrating"` to `_attr_options`; `tests/test_sensor_state_enum_
registration.py` now pins `_attr_options` against the translation files via
AST parse (HA's cached-property descriptor magic breaks direct class
attribute access in tests).

**Round 4 (wrong completion signal)**: with the crash fixed, a real test
showed calibration reported "complete" after 1 second while telemetry
showed it clearly still running. A prior fix had treated `RD_Grinder_Stop`
as a completion fallback alongside `RD_CurrentGrinder==85`. A fuller
decompile of `CalibrateGrinderActivity.onEventBusEvent` this time (not just
its confirm-button call site) showed the official app checks
`CurrentGrinderBleModel.value == 85` **exclusively**, alongside a 180s
client-side timeout (`Observable.just(0).delay(180000, ...)`, disposed if
85 arrives first). Removed the `RD_Grinder_Stop` fallback; added
`coordinator._async_calibration_timeout_fallback()` mirroring the 180s
timeout exactly.

**Round 5 (RD_Grinder_Stop's real role)**: even after round 4, a second,
longer test showed `RD_Grinder_Stop` fires within ~5s of send — part of
the calibration sequence's own startup/homing move — a full minute before
the real `RD_CurrentGrinder==85` reading (telemetry kept moving, settling
at `55 == 85-30` about a minute later). `is_calibrating_grinder` must
survive an early `RD_Grinder_Stop`; only the real 85 reading or the 180s
timeout may clear it. `RD_Grinder_Stop` still zeroes `grinder.speed`
(correct, unrelated). Hardware-confirmed clean afterward: a full ~73s run
completed correctly, `grinder_calibration_complete` fired exactly once.

**Round 6 (noise, not a bug)**: the same clean run showed generic
`grinding_started`/`grinding_complete` firing several times over the ~73s
window — expected mechanical behavior (the sequence genuinely stops/
restarts the grinder motor searching for the zero position) but noisy for
an automation listening for "my coffee grind finished." `_handle_response`
now suppresses the generic pair specifically while `is_calibrating_
grinder()` is true — the dedicated `grinder_calibration_*` events already
cover progress.

**Why**: every round's fix was individually correct and individually
insufficient — a strong argument for never declaring a hardware-dependent
fix done without a full, clean end-to-end run afterward.

**How to apply**: `RD_Grinder_Stop` must never be treated as a calibration
signal again — only `RD_CurrentGrinder==85` (or the 180s timeout) may clear
`is_calibrating_grinder`. If calibration events seem to misfire again,
re-run a full clean round rather than trusting a partial/crashed prior test.
