---
name: rc19-hardware-verification
description: "v1.5.0-rc.19 shipped 4 decompile-derived BLE changes pending real-hardware verification (8015/4508 sync, split writes, tea events)"
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

If any fail, capture the actual BLE traffic before doubting the decompiled semantics — see AGENTS.md's matching bullets. Related: [[xbloom-studio-review-adoptions]]
