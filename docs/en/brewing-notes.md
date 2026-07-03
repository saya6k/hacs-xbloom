# Brewing Notes — Firmware Behavior & Known Limitations

> Source of truth — see [한국어](../ko/brewing-notes.md) for the Korean translation (may lag).

This document records the actual BLE sequence `brewing.py` sends, firmware behavior that neither upstream (`PyBloom` / `xbloom-ble`) covers, and the limitations we have not yet resolved. For user-facing quickstart see [`index.md`](./index.md).

Last updated: 2026-05-29

## Current brew sequences

### Coffee (`grind_size > 0 + bean_weight > 0`)

`brewing._async_brew_coffee`. 1.0 s spacing between packets. Does **not** call the vendored `XBloomClient.brew()` — handled inline so the YAML's bypass parameters actually reach packet 8102 (the vendored path hardcodes `set_bypass(0.0, 0.0, dose)`).

```
─ Prelude ─
8022  RD_BackToHome   (restores pour-pattern interpretation after a tea brew)
─ Standard brew ─
8102  APP_SET_BYPASS  [bypass_volume_f32, bypass_temperature*10_f32, dose_i32]
8104  APP_SET_CUP     [cup_max_f32, cup_min_f32]
8001  APP_RECIPE_SEND_AUTO    (grinding) / 8004 SEND_MANUAL (no grinding)
8002  APP_RECIPE_EXECUTE
```

Cup bounds (mirrors vendored `XBloomClient` values):
- omni_dripper (2): grind → (90, 40), no-grind → (90, 0)
- xpod (1): grind → (80, 40), no-grind → (80, 0)
- other (3): grind → (90, 40), no-grind → (90, 0)

brAzzi64's HCI capture measured (110, 90) for omni_dripper, but the vendored values brew correctly so they are kept. Bounds appear to affect only weight display thresholds, not brew behavior.

### Tea (`cup_type: tea`)

`brewing._async_brew_tea`. 2.0 s spacing between packets — tighter intervals (0.3 s tried) caused the firmware to ACK only the first command and silently drop the rest (observed 2026-05-13).

```
8022  RD_BackToHome
8102  APP_SET_BYPASS  [0, 0, 0]
8104  APP_SET_CUP     [200, 0]    ← tea bounds
4513  APP_TEA_RECIP_CODE  (build_tea_payload)
4512  APP_TEA_RECIP_MAKE  (re-sends payload, mirrors vendored execute_recipe)
```

`_build_tea_payload` caps each steep's wire volume at `_TEA_SIPHON_CAP` (90 ml, so the firmware soaks then auto-tops-up to drain instead of draining instantly), uses substep pattern=1 (circular — same as coffee), and writes the soak time into the timing block's byte[1]. See [Resolved — tea multi-steep flatten](#resolved--tea-multi-steep-flatten) for how this was found; an earlier pattern=3 hack (borrowed from AML225's cloud-API JSON) did not work and was replaced.

## Resolved — grinding after a tea brew (2026-05-29)

**Status: FIXED.** Previously the integration skipped the grinder on the first coffee brew after a tea recipe (4513/4512) — pour behavior worked but no beans were ground (hot water through an empty filter), and the only recovery was a machine power cycle.

### Root cause

A PacketLogger HCI capture of the **official iOS app** going tea→coffee (2026-05-28, `Untitled - (null).pklg`) settled it: the official app sends **no mode-exit command at all** between a tea brew and a coffee brew — just the standard `8102 → 8104 → 8001 → 8002` — and its grinder engages on the very first coffee after tea. There is no tea-mode lockout in the firmware.

The bug was **self-inflicted**: `_async_brew_coffee` had grown a QUIT prelude (`APP_RECIPE_STOP` 40519 + `APP_BREWER_QUIT` 8013 + `APP_GRINDER_QUIT` 8012 + `APP_RECIPE_START_QUIT` 8017) that the official app never sends. One of those QUIT commands suppressed the grinder. The earlier guess that a missing, undocumented "tea exit command" was needed was backwards — we were sending *too much*, not too little.

### Fix

Removed the four QUIT commands from `_async_brew_coffee`; kept only `8022 RD_BackToHome` (it independently restores pour-pattern interpretation — without it the coffee pour falls back to center instead of the recipe's spiral). Confirmed 2026-05-29: tea → coffee now grinds, with spiral pour, temperature, and vibration all correct. The power-cycle workaround is no longer needed.

> Note: this document previously credited the QUIT prelude with "restoring multi-steep separation in tea." That was a coincidental correlation — the official capture shows tea steep separation is determined purely by the tea recipe payload (pattern byte + per-steep timing), not by any coffee-side prelude. See below.

## Resolved — tea multi-steep flatten

**Status: FIXED (2026-05-29, hardware-confirmed).** A multi-steep tea recipe (e.g. 홍차: 120 ml @95 °C soak 180 s + 120 ml @95 °C soak 120 s) used to brew as a **single ~316 ml pour** instead of two separate steeps. The official-app capture pinpointed the cause via a byte diff of the 4513 payload:

```
ha-xbloom: 10 | 78 5f 03 00 | 4c 00 00 1e | 78 5f 03 00 | 88 00 00 1e | 00 60
official:  10 | 5a 63 01 00 | 00 60 00 23 | 46 63 01 00 | ce 20 00 23 | 32 00
                  +-substep-+   +-timing--+
```

`316 = 120 + 76 + 120`: with no recognised steep boundary the firmware misreads the timing block's pause byte (`0x4c = 76`) as another pour volume. `_build_tea_payload` diverges from the official encoding in three fields:

1. **Substep pattern byte: 3 vs 1.** The `_TEA_PATTERN_BYTE = 3` hack (from AML225's cloud-API JSON) is not what the official app sends — it uses pattern 1 (circular), the same enum as coffee. Steep separation does NOT come from pattern=3.
2. **Timing byte[1]: 0 vs nonzero** (0x60 / 0x20) — the suspected real steep-separation / soak marker. `_build_tea_payload` hardcodes this byte to 0.
3. **Footer: `[0, water×10]` vs `[grind, ratio]`** — `_build_tea_payload` wrongly packs `total_water*10` into the ratio slot; it should mirror `encode_recipe`'s `[grinder_size, ratio×10]`.

**Separation FIXED 2026-05-29 (hardware-confirmed).** `_build_tea_payload` now emits pattern=1, footer `[grind, ratio×10]`, and the soak in timing byte[1] with byte[0]=0. Brewing 홍차 now produces two distinct steeps — **pattern 3→1 was the fix.** Follow-up: byte[1] was first written negated, which *inverted* the steep order on hardware (steep1 shorter than steep2, opposite of the recipe); it is now the **positive** `pausing & 0xFF` (the firmware reads it positively). 

**Soak scale calibrated (approximate) 2026-05-29.** A 홍차 brew measured the firmware running the idle wait at ~**1.67×** byte[1] (byte 180 → ~300 s, 120 → ~180 s). `_build_tea_payload` now writes `byte[1] = clamp(round(pausing × 0.6), 1, 255)` so the actual wait ≈ the recipe's `pausing` seconds (kept ≥1 to preserve the nonzero steep marker). The 0.6 is from two coarse stopwatch points — re-time a brew if you want it tighter.

**Real soak / siphon FIXED 2026-05-29 (hardware-confirmed).** ha-xbloom previously poured the recipe's full volume (120 ml), which hits the ~120 ml siphon threshold and drains *instantly* — no soak. The official app instead sends a sub-threshold pour and lets the firmware auto-top-up past the threshold AFTER the soak to trigger the drain. `_build_tea_payload` now caps each wire pour at `_TEA_SIPHON_CAP = 90 ml` (the recipe keeps its authored volume — e.g. 홍차 stays 120/120). Verified brew of 홍차: steep1 = 90 ml pour → **3 min soak with water held in the brewer** → firmware auto-top-up ~38 ml → siphon drain → vibrate; steep2 = ~90 ml → 2 min soak → +38 ml → drain. Soak durations matched the recipe (180 s / 120 s); total ~255 ml ≈ authored 240. So ha-xbloom's 4513 path triggers the same firmware soak+top-up as the official app — **we don't replicate the top-up, we just stay under the threshold and let the firmware do it.** Consequence: a real multi-minute soak IS achievable (this corrects the "flash steep only" note below).

## xBloom Omni Tea Brewer — siphon mechanics

This section documents the **hardware (Pythagorean cup) behavior**, not firmware. Necessary context when designing tea recipes.

### Official spec

- **Total capacity**: 160 ml per steep
- **Volume dispensed to cup**: ~120 ml per steep
- **Auto Steep System**: valve automatically opens when water level reaches the siphon arm height inside the brewer; full volume drains

(Sources: xBloom official guide, Basic Barista product page)

### Actual behavior

- Tea leaves (3-5 g loose leaf) occupy ~30-40 ml of physical volume inside the brewer
- Effective threshold: **pouring ~120 ml of water triggers the siphon immediately**
- If you pour **≥ threshold** → instant siphon drain, no soak (this was ha-xbloom's old bug)
- If you pour **< threshold** → water is **held** in the brewer and **really soaks** for the programmed time, then the firmware auto-tops-up past the threshold to trigger the drain (verified 2026-05-29: 90 ml → 3 min soak → +38 ml → drain). This is what the official app and now ha-xbloom (via `_TEA_SIPHON_CAP`) do.

### Recipe design implications

- The YAML `pausing` field **is the real steep/soak time** (water sits in the brewer for it), as long as the per-steep pour stays under the siphon threshold — which `_build_tea_payload` enforces with `_TEA_SIPHON_CAP` (90 ml)
- A real multi-minute soak **is** achievable (earlier notes here calling this a "flash steep only" device and "long-soak structurally impossible" were wrong — disproven on hardware 2026-05-29)
- For stronger tea:
  - Increase the leaf amount (3 g → 5 g)
  - Increase `pausing` (longer real soak) and/or use multiple steeps
- Suited to oolong / black tea-style multi-infusion leaves; for matcha or fine teas note the firmware still auto-drains each steep (no indefinite submersion)

### Threshold math

`threshold_water_ml = 160 - leaf_volume`. Leaf volume depends on quantity and tea type (dryness, leaf size). 3 g green tea → ~30 ml volume → threshold ~130 ml. 5 g pu-erh → larger volume → threshold ~100-110 ml.

## 2026-05-28 session changelog

1. `_async_brew_coffee` introduced — bypasses vendored `XBloomClient.brew()`, runs inline sequence
2. Added 8022 to coffee prelude → restored pour pattern interpretation (spiral was being read as center)
3. Added RECIPE_STOP + BREWER_QUIT + GRINDER_QUIT to coffee prelude → restored multi-steep separation in tea (previously all steeps flattened into one pour)
4. Added 8017 (no observed effect on grinding restoration, but kept as no-op)
5. Tried 8006 → no effect → rolled back
6. Tried switching tea path to 8004/8002 → firmware did not enter tea mode → reverted to 4513/4512
7. `bypass_volume` / `bypass_temperature` now actually reach packet 8102 — YAML bypass fields became functional for the first time
8. Confirmed AGENTS.md's "8004 tea path" claim was inferred, not measured; recorded the invalidation in code comments

## 2026-05-29 session changelog

1. Decoded a PacketLogger HCI capture of the official iOS app (tea → coffee → coffee). All four recipe packets CRC-verified. Established framing + chunk reassembly (raw concat to the `len` field).
2. **Grinding-after-tea FIXED:** removed the QUIT prelude (RECIPE_STOP + BREWER_QUIT + GRINDER_QUIT + RECIPE_START_QUIT) from `_async_brew_coffee` — it was the cause, not the cure. Kept 8022 only. Confirmed on hardware: tea → coffee grinds with correct spiral/temp/vibration. Power-cycle workaround removed.
3. Removed the now-unused `_CMD_BREWER_QUIT` / `_CMD_GRINDER_QUIT` / `_CMD_RECIPE_START_QUIT` constants.
4. Invalidated the changelog #3 claim above (QUIT prelude "restored tea separation") — coincidence; separation is payload-driven.
5. **Tea-flatten FIXED:** root cause was pattern=3 (firmware misparses → 316 ml = 120 + 76 + 120). `_build_tea_payload` now uses pattern=1, `[grind, ratio]` footer, and soak in timing byte[1]. Hardware-confirmed two separate steeps.
6. **Tea soak FIXED:** byte[1] = `round(pausing × 0.6)` (firmware runs the wait at ~1.67× the byte; hardware soaks came out at the recipe's seconds). An earlier negated byte inverted the steep order — corrected to positive.
7. **Tea real-soak / siphon FIXED:** added `_TEA_SIPHON_CAP = 90` — caps the wire pour below the siphon threshold so the firmware soaks then auto-tops-up to drain (recipe keeps its authored volume). Hardware-confirmed: 90 ml → 3 min held soak → +38 ml → drain, per steep. Disproves the old "flash steep only / long-soak impossible" claim.
8. Confirmed the official app **auto-converts** authored tea volumes (preset 120/120 → wire 90/70 fitting the 160 ml capacity); ha-xbloom doesn't replicate the converter but the sub-threshold cap + firmware top-up achieves the same real-soak result.
9. BP temperature observation: a user-confirmed BP tea pour encoded as byte 99 (not the 98/100 the upstreams guessed) — likely a computed near-boiling value, not a fixed sentinel.
