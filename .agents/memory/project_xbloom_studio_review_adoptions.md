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
- **cmd 8104 and cmd 40518, real-brew round (2026-07-15, round 3, water only —
  no beans loaded, user supervised at the machine)**: `xbloom_probe10.py` ran
  two FULL real brews (opcode 8004 no-grind, dose=15/bean_weight=15 purely for
  ratio math — no physical beans involved, 60 ml water each) through to
  natural completion (armed → commit(8002) → brewing(sub) 0x23 → **ready**
  0x24, ~33 s each), varying only the 8104 payload: `(95.0, 85.0)`
  (temp-plausible) vs `(3.0, 0.0)` (weight-plausible/temp-absurd, while still
  pouring 60 ml ≫ any 3-unit bound).
  - **Result: no observable difference whatsoever** — identical timing,
    identical status transitions, no refusals, and **zero
    `RD_BREWER_TEMPERATURE`(8108) notifications in either run** despite a
    complete brew cycle. For this specific recipe shape (no-grind,
    bypass-off), 8104's value isn't load-bearing in any way visible over
    BLE — doesn't resolve the abstract "weight vs temp" question, but does
    mean our shipped `_COFFEE_CUP_BOUNDS_NO_GRIND` values are practically
    safe regardless of which interpretation is correct, at least for this
    recipe type. Grind-path / bypass-enabled recipes (which would need real
    beans) remain untested.
  - **cmd 40518 ("start" per Janczykkkko vs `CMD_BREW_PAUSE` per brAzzi64)
    still unresolved** — on this firmware, commit (8002) alone made the
    machine proceed straight to brewing both times; it never stalled at
    `awaiting_confirm` (0x1e), so per Janczykkkko's own safety rule (never
    send 40518 into an already-acting brew) the probe correctly never sent
    it. Confirms 40518 isn't *required* for normal brews on this unit;
    what it actually does remains untested — deliberately, since forcing an
    artificial stall just to test it would defeat the safety rule that
    makes the test meaningful.
  - **ROOT-CAUSED, 2026-07-15 round 4 (`xbloom_probe11.py`/`xbloom_probe12.py`,
    load-only, fresh-connect isolated single-variable tests)**: cmd
    `8102`'s **dose byte being `0` is independently sufficient to block the
    no-grind (8004) recipe from ever arming — silently, no refusal
    notification at all** — regardless of the 8004 footer's ratio byte.
    Three clean fresh-connection tests, `total_water=150`/`rpm=100`/
    `cup=(80.0,0.0)` held fixed throughout:
    - `dose=15, bean_weight=15` (footer ratio naturally `0x64`) → **armed
      OK**. (Sanity re-check of probe10's baseline — still holds.)
    - `dose=0, bean_weight=0` (footer ratio naturally `0x00`) → **no arm
      status, ever** (10s timeout, clean connection, reproducible).
    - `dose=0, bean_weight=15` (footer ratio forced/naturally `0x64`,
      i.e. **the real shape `brewing.py` sends today for any no-grind
      coffee recipe that has a real weighed dose**) → **also no arm
      status.** This isolates the cause to the 8102 dose byte alone, not
      the footer.
    - **This is a live production bug**, not a hypothetical: `brewing.py`
      line ~269 is `dose = int(recipe.bean_weight) if grinding else 0` —
      `grinding` is `False` whenever `grind_size == 0` (the intentional
      "pre-ground coffee, don't run the grinder" feature, distinct from
      the opcode 8001-vs-8004 selection which is correct and unrelated).
      So **every no-grind coffee recipe currently zeroes its own dose
      before sending it to 8102**, which (per this test) means the
      machine never arms it — `execute_recipe` for any no-grind recipe
      would hang waiting for a status that never comes. The vendored
      upstream's own `brew_without_grinding` (`src/xbloom/core/client.py:496`)
      has the identical `dose=0` pattern, so this is likely also latent
      there, not something `brewing.py` introduced.
    - **Fixed and hardware-verified, same session**: `brewing.py`'s `dose`
      now follows `recipe.bean_weight > 0` unconditionally (`grinding`
      still gates opcode 8001-vs-8004 and the cup-bounds table, just no
      longer the dose value). Re-ran the exact previously-broken shape
      (`grind_size=0, bean_weight=15`) through the **real**
      `brewing._async_brew_coffee()` (not a reimplementation — only
      `execute_coffee_recipe` was intercepted to keep it load-only) —
      **armed OK**. `pytest tests/` still 66 passed/3 skipped.
      `dose` should follow `recipe.bean_weight` whenever it's `>0`,
      independent of `grinding` — `grinding` should only gate opcode
      selection (8001 vs 8004) and the cup-bounds table, not the 8102
      dose value. A true water-only recipe (`bean_weight == 0` for a
      *coffee*-path recipe, not tea) is a separate, narrower open
      question: this test also showed `dose=0/bean_weight=0` fails to
      arm, and there's no real dose to substitute in that case — but
      `schema.py`'s `dose_g` defaults to `15.0` for coffee recipes (only
      reachable at `0` via explicit user override, and tea already uses a
      wholly separate 4513/4512 path that never touches 8102/8004), so
      this edge case may not be practically reachable today.
- **No-grind footer byte (0xFE vs 0x00), resolved 2026-07-15 (round 2)**: cross-
  referenced `Janczykkkko/xbloom-ble`'s `NO_GRIND_WIRE=0xFE` sentinel (their
  claim: sending literal `0` "grinds at the finest setting") against our
  shipped `_build_coffee_recipe_payload`, which always writes
  `grind_size & 0xFF` (`0x00` when `grind_size=0`) and never emits `0xFE`.
  Direct load-only hardware test (`xbloom_probe7.py`): armed the identical
  no-grind (opcode 8004) recipe once with footer byte `0xFE`, once with
  `0x00` — **byte-for-byte identical notification streams both times**
  (same arm sequence, same `RD_MachineInfo` grind field, no errors). At the
  arm stage the footer grind byte has no observable effect once opcode 8004
  already tells the firmware "no grinding" — **our shipped `0x00` behavior is
  safe as-is; no code change needed.** (What happens if the brew is actually
  *committed*, i.e. whether footer `0x00` would grind on execute the way
  Janczykkkko warns, is still untested — would need a real brew, out of
  scope for a load-only check.)
- Still needs devcontainer/UI-level check (not done via raw BLE): (a) the
  Bluetooth discovery card actually renders in Settings → Devices & Services,
  (b) the 4-device split renders as expected there, (c) `execute_tea_recipe`
  brews tea end-to-end.

**Round 5, same session (2026-07-15): adopted the two informational items
from the `Janczykkkko/xbloom-ble` cross-reference** (richer status-byte
table, `0xc1` notification marker) — committed as `203f973` (0xc1 marker)
and `170abf7` (no_beans/water_shortage/ready states):
- `0xc1` marker byte: `_client.py`'s `_split_and_parse` now also requires
  the constant marker byte at offset+9 (confirmed `0xc1` on every captured
  `RD_MachineInfo` frame this session) alongside the existing
  `_MAX_PACKET_LEN` bound, as a second independent false-positive-header
  filter. Verified live — `RD_MachineInfo`/grinder/voltage telemetry still
  decode correctly with the check in place.
- `no_beans`/`water_shortage`/`ready` added to `sensor.state`'s
  `_attr_options`: the first two reuse `RD_ErrorIdling`/
  `RD_ErrorLackOfWater`, which already fired as events but never reached
  `sensor.state` — same tracking pattern as the pre-existing
  `_water_shortage` flag. `ready` (brew done/beeped, cup still on the
  scale) needed new raw-frame parsing since nothing in the existing
  cmd-tagged notifications distinguishes it from `RD_Brewer_Stop`'s
  immediate `IDLE` (which fires the instant pouring physically stops, not
  when the cup is lifted) — `_client.py._scan_for_status_frame` reads the
  raw status-heartbeat frame directly (same frame family Janczykkkko
  documents; never reaches `_handle_response`, no `XBloomResponse` enum
  entry) for the ready/idle codes, with a safety-net clear if a new brew
  starts before a true-idle frame ever arrives.
- Deliberately did NOT add a distinct "starting" state (0x22, the ~20s
  silent-grinding window), reasoning that `RD_GRINDER_BEGIN` already sets
  `grinding` promptly via the existing cmd-tagged path — **this was an
  untested assumption, corrected below (round 6)**: no grind-path brew had
  actually been run this session (no beans loaded) when that claim was
  written, so whether `RD_GRINDER_BEGIN`'s timing actually covers the same
  window was never verified. Still not resolved either way — round 6 below
  didn't reach real grinding (aborted at the "starting" transition), so
  `RD_GRINDER_BEGIN` vs raw-status timing remains genuinely open.

**Round 6, same session (2026-07-15): end-to-end verification of the two
new states, real `brewing._async_brew_coffee()` (`xbloom_probe15.py`).**
- **`ready`: confirmed working end-to-end.** A real no-grind 50 ml water
  brew completed naturally (`brewing_started` → `bloom` → `pour_complete`
  → `recipe_complete` → raw status `0x24`), and
  `client.status._brew_ready` flipped `True` within the same second raw
  status showed `0x24`, then stayed `True` through an extra 10 s wait (no
  physical cup was ever removed, consistent with "stays ready until the
  cup is lifted"). The `coordinator.py` derivation itself
  (`elif getattr(s, "_brew_ready", False): state_str = "ready"`) is
  simple enough that this confirms the sensor value end-to-end without
  needing a full HA runtime.
- **`no_beans`: did NOT trigger as documented — a real behavior gap from
  what Janczykkkko/AGENTS.md's state table claims.** Armed a real
  grind-path recipe (`grind_size=50, bean_weight=15`, opcode 8001) with
  no beans physically loaded, expecting the machine to refuse/wait at
  status `0x0F` ("machine WAITS here" per the documented state table).
  Instead it proceeded `armed → awaiting_confirm → starting (0x22)` —
  the probe's safety check caught this (any of 0x22/0x10/0x23/0x3B is
  treated as "unexpectedly grinding/brewing, abort") and immediately sent
  `stop_recipe()`; the machine responded with a `grinding_complete` event
  and returned cleanly to `0x41 (complete)`. **Neither the `0x0F` status
  nor a `no_beans` event ever fired** before the abort.
  - **Side effect**: the post-test health check showed
    `RD_MachineInfo`'s live grind-size telemetry changed from the
    session's consistent baseline (`grind_raw=87`, UI 57) to `grind_raw=80`
    (UI 50) — exactly matching the aborted test recipe's `grind_size=50`.
    Most likely explanation: "starting" briefly engaged a motorized
    grind-*size* adjustment (repositioning the burr gap to match the
    recipe) before any actual bean-grinding attempt, and the probe's
    abort caught it before it got further — but this is inference, not
    confirmed. Net effect either way: **the machine's stored/live grind
    setting was changed by this test** (user was told to check/reset the
    physical dial if they care about the prior 57 setting).
  - Implication: the `no_beans` sensor.state value (added round 5) is
    real, correctly wired to `RD_ErrorIdling`, but **this specific test
    couldn't confirm it actually fires on this firmware/condition** — the
    machine may check for beans later (mid-grind, not pre-arm) or via a
    different signal than assumed. Further grind-path-without-beans
    testing was deliberately not repeated given this result — the
    "no_beans = safe wait" assumption that justified trying it turned out
    to not hold.
