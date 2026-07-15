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
the same session. **Committed to `main` as 5 separate commits** (not pushed —
confirm with the user before pushing): `c56e886` (slot batch-write fix),
`8cc072b` (Bluetooth discovery), `78a894f` (execute_tea_recipe),
`e0ac87e` (telemetry/device-split/flow-rate), `2b714d0` (memory). The
same session also cloned and cross-referenced `Janczykkkko/xbloom-ble`
(a second independent reverse-engineering effort) and live-tested several
of its claims directly against real hardware over BLE from this machine
(see the hardware-verification note below) — that's what surfaced and
confirmed the Easy Mode slot-batching bug now fixed in `c56e886`.

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

**Hardware verification (2026-07-15, direct BLE from this Mac via bleak, machine
"XBLOOM 4CV030" / firmware V12.0D.500 — the exact firmware Janczykkkko tested
against):**
- MachineInfo byte 37/39 parsing: confirmed live (grind byte 87→UI 57 plausible;
  voltage byte 220 matches Korean 220V mains — strong signal it's really volts).
- Recipe LOAD-only tests (never sent commit/start — physically safe): dose_g=20
  armed fine, **refuting** Janczykkkko's claimed "18g firm cap" at the protocol
  level. Our own `ratio×10` footer fix (independently found via decompiling the
  app) was hardware-confirmed correct. no-grind sentinel (0x00 vs 0xFE) was
  **inconclusive** — both arm identically; distinguishing them needs a completed
  brew or a slot-write comparison, neither done.
- Easy Mode slot test: **confirmed and fixed**. Single-slot write hangs the real
  machine at status 0x43 (RETRY) exactly as Janczykkkko documented; completing
  the A/B/C batch immediately unsticks it (0x43→0x25→idle, with an 0xf8
  notification in between). PRO mode is required first. Both now handled in
  `coordinator.async_write_easy_slot` (see `c56e886`).
- Still untested/unverified: cmd 8104 semantics (cup-weight-bounds vs
  preheat-stage-temps — genuine unresolved conflict, not tested since it needs a
  live brew to observe), cmd 40518 (pause vs start — **never tested, physically
  risky**, would need explicit fresh confirmation), no-grind 0xFE's actual effect
  on stored slot memory.
- Still needs devcontainer/UI-level check (not done via raw BLE): (a) the
  Bluetooth discovery card actually renders in Settings → Devices & Services,
  (b) the 4-device split renders as expected there, (c) `execute_tea_recipe`
  brews tea end-to-end.
