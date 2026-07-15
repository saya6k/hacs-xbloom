---
name: xbloom-studio-review-adoptions
description: "In-flight, uncommitted work adopting ideas from reviewing Alshekhi/xbloom-studio — what changed, why, and what still needs real-hardware verification"
metadata: 
  node_type: memory
  type: project
  originSessionId: aac0a1e2-1283-41d2-a622-2cf11d40dc2d
---

Reviewed the newly-published `Alshekhi/xbloom-studio` HA integration (2026-07-15) as
a feature comparison against this repo, then implemented several of the ideas over
the same session — all currently **uncommitted** on `main` (15 files touched, no
commit made yet; confirm with the user before committing/pushing).

**What was adopted, in order:**

1. **Bluetooth auto-discovery** (`config_flow.py`) — added `async_step_bluetooth` +
   `async_step_bluetooth_confirm` so HA shows a one-click "discovered" card instead
   of requiring manual MAC entry. Reuses the existing connect-test/account-step flow.
2. **MachineInfo unused fields + live knob telemetry** (`_client.py`,
   `coordinator.py`) — parses previously-ignored `RD_MachineInfo` bytes (37=grind
   size, 39=voltage) and three notify codes that were already in our own vendored
   `XBloomResponse` enum but had no handler: `RD_GRINDER_SIZE`(8105),
   `RD_GRINDER_SPEED`(8106), `RD_BREWER_MODE`(8107/pattern). These mirror onto the
   *existing* `number.temperature` / `select.*_pour_pattern` setpoints in real time
   (turn the knob, the HA entity follows) — **gated to only apply while
   `state == "idle"`**, because `RD_BREWER_TEMPERATURE`(8108) is ambiguous between
   "knob turned" and "brewer heating toward a recipe target mid-brew"; syncing
   during an active brew/grind/pause would corrupt the setpoint with transient
   noise. Provenance: cross-referenced against xbloom-studio's own capture
   (firmware V12.0D.500), corroborated by matching numeric conventions already in
   this repo (RPM bounds, pattern int mapping) — not yet verified on our own
   hardware.
3. **Entity reorg into child devices** — device registry now has 4 devices per
   config entry: main + Grinder + Scale + Brewer, linked via `via_device`
   (see `coordinator.grinder_device_info` / `scale_device_info` /
   `brewer_device_info`). Deliberately **not** HA's "config subentries" feature —
   that's for dynamically add/removable child items, wrong fit for fixed
   sub-components of one physical machine. `unique_id`s untouched, so no
   entity_id/automation breakage, only device-page regrouping.
4. **`number.flow_rate` removed, replaced by a read-only `sensor.xbloom_flow_rate`**
   (Brewer device) — no physical knob exists for flow rate (confirmed absent from
   both our vendored enum and xbloom-studio's capture), so a manual setpoint made
   no sense. New: `_client.py` now decodes `RD_BLOOM`(40510)'s pour_index payload;
   `coordinator.async_execute_recipe()` snapshots the final post-override pour list
   and updates `self.flow_rate` live to the active pour's value as "bloom" events
   arrive, reverting to the manual-pour value once idle.
5. **New `execute_tea_recipe` service** — leaner sibling of `execute_recipe`
   (device_id + recipe only, no dose/ratio/grind/bypass) since tea takes a wholly
   different BLE sequence and none of those fields apply. `execute_recipe` /
   `create_recipe` / `edit_recipe` are untouched (full backward compat); shares the
   `recipe` field name for consistency. See [[feedback_additive_variant_split]].

**Explicitly NOT adopted** from xbloom-studio: cloud API, LLM tools platform (we're
far ahead there already), tea-recipe handling (their tea path reuses the generic
`8004` sequence, which this repo's own HCI capture already proved does **not**
enter real tea mode — see the tea firmware-quirk entry in `AGENTS.md`).

**Follow-up still needed:** none of this has been exercised on real hardware yet.
Before considering it done: verify in the devcontainer that (a) Bluetooth discovery
actually surfaces the "discovered" card, (b) turning the physical knobs updates the
mirrored Number/Select entities and reverts correctly after a brew, (c) the 4-device
split renders as expected in Settings → Devices, (d) `flow_rate` sensor tracks
per-pour values during a real coffee recipe brew, (e) `execute_tea_recipe` actually
brews tea end-to-end.
