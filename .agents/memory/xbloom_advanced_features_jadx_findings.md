---
name: xbloom-advanced-features-jadx-findings
description: "jadx (not androguard) decompilation revealed pour-radius/vibration-amplitude are 5/6-level discrete GET/SET pairs, grinder calibration trigger is a fixed cmd 3502 payload, display brightness is a 3-preset setter with no GET; descale and scale calibration triggers were NOT found despite the same treatment."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

`androguard`'s bytecode access finds command-*id* literals but not payload
*encoding* (parameter types, scaling, response parsing). `jadx` decompiles
to near-source Kotlin/Java, which resolved payload semantics in one pass
(2026-07-16) from `MachineSetPourRadiusActivity`/
`MachineSetVibrationAmplitudeActivity`/`MachineAdvancedFeaturesJ15Activity`:

- **Pour radius**: GET `11506`/SET `11507`, a **5-level discrete control**
  (not continuous) centered on a per-device value read back from the
  machine, each level ±80 apart (`radius = center - (2 - level) * 80`).
- **Vibration amplitude**: GET `11508`/SET `11509`, same shape, 6 levels.
- Response format: `it.substring(0,8)` → `reverseHex()` → parse as hex int
  — byte-reversing a big-endian hex dump is the same operation as reading
  little-endian, matching every other integer `RD_*` payload in this
  codebase.
- Neither `11506` nor `11508` are in the vendored `XBloomResponse` enum, so
  they need the raw pre-scan pattern described in
  [[xbloom-advanced-settings-transport-bugs]] — confirmed as the right
  model to extend by reading `AppBleManager`'s own source: the official app
  keeps no fixed response registry either, just parallel `codeList`/
  callback lists matched against incoming raw cmd ids.
- **Grinder calibration**: `CalibrateGrinderActivity`'s confirm button is
  `CodeModule(3502, "磨豆档位归0", 1000)` — cmd `3502`, single fixed
  payload `[1000]`. The ~120s sweep then runs autonomously. See
  [[xbloom-grinder-calibration-completion-signal-saga]] for how completion
  is actually detected.
- **Display brightness** (found 2026-07-17 chasing a follow-up question,
  same method): `MachineDisplayActivity`'s save button sends
  `BleCodeFactory.switchLed(value)` → cmd `8103`
  (`CommandParams.RD_LetType`, a gap in the command table between 8102 and
  8104), 3 fixed presets (L1/L2/L3 → raw `1`/`8`/`15`), **no GET
  counterpart** — the app reads the current value from its own cached
  account/device record, not a fresh BLE read.

All four surfaced as a single `advanced_settings` service
(`coordinator.async_set_advanced_settings`) plus two read-only sensors
(`pour_radius`, `vibration_amplitude`) rather than several always-visible
entities — deliberate choice, matching "settings nobody adjusts often." The
service takes **levels** (0-4 / 0-5 / 1-3), not raw values, matching the
official app's own L1-L5/L1-L6/L1-L3 picker UIs.

**Descale and scale calibration were NOT found**, despite the same `jadx`
treatment: `DescaleActivity`/`DescaleFragment` is a pure 7-page tutorial
image carousel with zero `CodeModule` calls anywhere in its class hierarchy;
`CalibrateScaleJ15Activity` likewise has none in its own methods. The actual
trigger is delegated somewhere neither `androguard`'s const-sweep nor a
`CodeModule(` grep across all decompiled sources could reach — candidates:
the separate `ScaleActivity` class's `8003`/`8014` scale-mode entry/exit
commands, or the `AppWsManager` websocket manager. Genuinely unresolved, not
deprioritized.

**Why**: this is the template for "found a command id via androguard but
need to know what the payload means" — jadx first, not more const-sweeping.

**How to apply**: if descale or scale-calibration ever needs implementing,
start from `AppWsManager` or the `8003`/`8014` scale-mode commands, not
another const sweep — those dead ends have already been ruled out.
