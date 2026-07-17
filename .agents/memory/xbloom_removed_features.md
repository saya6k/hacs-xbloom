---
name: xbloom-removed-features
description: "button.vibrate_scale (SG_* scale-gesture commands), sensor.last_error, and the cloud Product/Shared recipe tabs were all implemented then reverted after turning out to be non-real, duplicate, or lacking a concrete use case - a reminder to verify a feature is real and needed before shipping it."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

**`button.vibrate_scale` removed (2026-07-17)** — the `SG_*` scale-gesture
commands (2500-2505, incl. `SG_VIBRATE` 2502) are not a real Studio feature.
Hardware-reported as a no-op, and the evidence agrees: the official app
never sends any `SG_*` command anywhere (they exist only in its
`CommandParams` constant table), and `src/xbloom-ble`'s capture-based
`PROTOCOL.md` has no trace of them — the vendored PyBloom `scale.vibrate()`/
`move_left()`/`move_right()` methods were written from the app's constant
*names* alone, with no capture behind them.

**`sensor.last_error` removed** (`XBloomErrorSensor`) — a byte-for-byte
duplicate of `binary_sensor.problem`'s own `last_error` extra-state-
attribute (both just read `coordinator.data["error"]`). `event.error_event`
is not a duplicate of either — it's a momentary occurrence log (fires once
per error with an `event_type` attribute), not an ongoing-state surface, so
it stays.

**The official app's Product/Shared account recipe tabs** (`MyRecipeType.
PRODUCT`/`SHARED` — the app's `tuMyRecipeProduct.tuhtml`/
`tuMyRecipeShared.tuhtml`) were implemented (`cloud_search_my_recipes`/
`cloud_import_my_recipe` services + LLM tools, 2026-07-17) and **reverted
the same day**. Decompile-driven completeness ("the app has it, we don't")
wasn't backed by an actual use case: Product recipes (bundled with a
purchased pod) are a narrow audience for a BLE-first integration, Shared
recipes (account-to-account push via the app's own Share button) are a
rare path next to the public `share_url` links `cloud_import_recipe`
already covers, the feature required a cloud login for what's designed to
work fully over Bluetooth without one, and none of it was ever verified
against a live account. If this gap resurfaces from a future decompile
diff, that's not new information — don't re-implement without a concrete
use case first.

**Why**: three separate removals, same underlying lesson each time — a
vendored library method existing, or the official app having a feature,
doesn't by itself justify shipping the equivalent here. Check for a real
capture/call-site (not just a constant-table name) and a concrete use case
before adding a new entity/service, not after.

**How to apply**: don't re-expose any `SG_*`-based entity without first
capturing the official app actually using it. Before adding a new sensor
that reads `coordinator.data[...]`, check whether an existing entity's
extra-state-attributes already expose the same data. Before reimplementing
Product/Shared cloud recipe tabs, get a concrete use case first, not just
decompile-completeness pressure.
