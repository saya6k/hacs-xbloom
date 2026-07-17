---
name: rc19-hardware-verification
description: "v1.5.0-rc.19+ shipped decompile-derived BLE changes pending real-hardware verification (8015/4508 sync, split writes, tea events, sleep-state mode-switch gating, pause/resume 40518/40524 swap)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 30eb5041-96db-453d-bdd0-8d5fa6cdcc64
---

v1.5.0-rc.19 (published 2026-07-17) bundles PRs #80-83, all decompile-derived and **not yet hardware-verified**. User plans to verify via this prerelease:

1. **8015/4508 unit & water-source sync (#82)** — change units/water source on the machine touchscreen while connected → expect `RD_UNIT_CHANGE:` log line + select entity follows; flip `select.water_source` → machine's own settings screen should follow. Payload order (weight/temp/water 3× LE u32) and Studio values (tank=0, direct=1) are from the app's `DeviceUnitBleModel`/`WaterSourceType.ordinal()`.
2. **≤100-byte split writes (#80)** — matters only on low-MTU paths (ESPHome BLE proxy); normal adapters unchanged.
3. **`tea_resumed` (9011) + `tea_soak_time_changed` registration (#83)** — needs a multi-steep tea brew to observe.
4. Still outstanding from rc.18: connection supervisor/15s silence watchdog behavior, water-refill (40522 value=1) clearing the shortage gate.
5. **Sleep-state tracking (8009/8011/8023) gating mode-switch retry, added 2026-07-17 (not yet in a numbered PR/release)** — `client.is_sleeping()` now gates `coordinator._async_switch_mode_with_retry()`: a missed ACK while the machine is awake fails after one send (no retry), matching the app's `AppDeviceManager.isSleeping()` check. Needs a mode switch attempted while the machine has genuinely gone idle-to-sleep to observe the retry path at all; a normal awake-machine switch should behave the same as before (single-attempt success).
6. **Recipe pause/resume button switched from `APP_GRINDER_PAUSE`/`APP_BREWER_PAUSE` (8018/8019) to the whole-recipe 40518/40524, added 2026-07-17 (not yet in a numbered PR/release)** — decompile showed 8018/8019 are only ever used by the app's separate standalone manual Grinder/Brewer screens, never for pausing an in-progress Auto recipe (that's exclusively 40518/40524). **Highest-risk item in this list** — genuinely swaps the live BLE commands a user-facing button sends, with zero hardware confirmation either way. Test: start a coffee brew, press pause mid-grind/mid-pour, confirm it actually pauses (not resets to armed/aborts), then press resume and confirm it continues from where it left off (not restarts). If resume fails, capture the actual BLE traffic before reverting to 8018/8019 — see AGENTS.md's matching bullet.

If any fail, capture the actual BLE traffic before doubting the decompiled semantics — see AGENTS.md's matching bullets. Related: [[xbloom-studio-review-adoptions]]
