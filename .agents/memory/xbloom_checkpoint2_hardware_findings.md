---
name: xbloom-checkpoint2-hardware-findings
description: "Checkpoint 1+2 live smoke 2026-07-20: T3-T7 all verified on hardware; 4 bugs found+fixed same-session (reconcile race, 4510/8016 back-to-back drop, start-transition stop drop, 40511 never after 4507); 9003/9005 fire on knob starts with snapshot payloads."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9518af78-3112-4f15-b9d7-be223b4d0d1d
  modified: 2026-07-20T01:48:18.450Z
---

Live Checkpoint 1+2 session (2026-07-20, harness = real StateMixin/
OperationsMixin + real XBloomClient over bare BleakClient, HA glue stubbed —
scratchpad `hw_verify_t3t7.py`, logs `hw_verify_run*.log`). **T3–T7 all
verified end-to-end**: knob/button state parity (standalone_grind/pour/scale
both directions), knob→entity mirrors (grind size/RPM/temp/pattern/volume
seed), entry push visible on the machine display (60 °C + circular adopted
and echoed back in the knob-started pour's own 9005 snapshot), armed→active
transitions with correct cancel targeting (3505 grind / 4507 pour), literal-°C
8108 fix confirmed (knob 95 read as 95, not 9.5).

**Four bugs found and fixed in-session** (commits c90a7a3, b410044):

1. **Stale-arm reconcile raced every arm** — the machine keeps reporting home
   for ~1s after 8006/8007 until the page code lands; the level-triggered
   "home clears grind/pour arms" rule cleared a fresh arm deterministically
   on a fast poll tick. Fix: edge-triggered — the armed page must have been
   observed before a home report clears it.
2. **Back-to-back sends drop the second command**: 4510 then 8016 1ms apart →
   4510 ACKed, 8016 never (machine kept its remembered pattern; user saw
   "center" instead of circular). The app's sendMessage queue is ACK-gated
   (~370-380ms); fix = 0.5s gap (`_POUR_ARM_PUSH_GAP_S`). General rule for
   any multi-send flow.
3. **Start-transition stop drop**: a 3505 sent ~1.9s after 9003 (before
   40506) was silently ignored — grinder ran through the cancel (user had to
   stop it manually). Same send after 40506 stops in <150ms. NOT
   deterministic (a 0.2s-after-9003 send worked). Fix: outcome-based retry —
   `_async_verify_component_stop` watches is_running 2.5s, re-sends once;
   re-send verified harmless when the first landed.
4. **40511 never comes after a 4507 stop** (completion-only signal) →
   brewer.is_running latched True, derived state stuck at "brewing". Fix:
   page/home screen reports clear both run flags (machine showing a page =
   nothing running).

**Protocol refinements**: 9003 `RD_GRINDER_BEGIN` DOES fire for knob-started
grinds (2× LE u32 size/rpm snapshot, ~1s before 40506) — the old "never seen
firing" holds only for app/recipe grinds. 9005 `RD_BREWER_BEGIN` on knob
starts carries the 4× LE u32 (volume, temp, pattern, temp) snapshot.
Wire pattern encoding confirmed = our enum (app maps UI 1/2/3 →
`Device.getPatternMachine` → 0=center/1=circular/2=spiral before sending).

**Still pending**: recipe-family machine-confirm transition (armed recipe →
knob confirm) not hardware-run — unit-tested only, deferred to the rc soak.

**Why:** these transport quirks (drop window, back-to-back drop) will bite
any future multi-send or cancel flow; the session pattern (mixin harness over
bare bleak) is the fastest full-behavior test rig short of real HA.

**How to apply:** never send two commands back-to-back without a gap or ACK
gate; never trust a stop until the run flag clears; reuse
`hw_verify_t3t7.py`'s harness shape for future coordinator-level hardware
tests. See [[xbloom-t2-screen-code-capture]] and
[[xbloom-machine-alarm-channel-and-rtbp]] for the same day's earlier halves.
