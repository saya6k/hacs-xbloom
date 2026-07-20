---
name: xbloom-t2-screen-code-capture
description: "T2 hardware capture 2026-07-20: full standalone screen-code map (adjust subscreens 0x06-0x09, descale 0x2F/0x32, scale-cal 0x39/0x3A, grinder-cal 0x25/0x26/0x27), 9000/9001 entry snapshots (9001 volume default 250!), 8500 tares from any screen but flips display to scale page, 0x03 now consistent, 40505 = gear stream."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9518af78-3112-4f15-b9d7-be223b4d0d1d
  modified: 2026-07-19T16:54:04.900Z
---

Live passive capture with the maintainer at the machine (2026-07-20, listener =
bare-BleakClient transport driving the integration's own `ble/` package;
session scratchpad `t2_listener.py` / `t2_capture.log`; results drafted into
`docs/*/protocol.md`'s command table). Firmware V12.0D.500, `XBLOOM 4CV030`.

**Screen-code map (heartbeat/8023 — same frames: `0x57` type byte is the low
byte of cmd 8023 = `0x1F57`):**

- Grind page `0x02` (knob entry fires 9000 `IN_GRINDER` with 2× LE u32
  `(grind_size, rpm)` — size in user units, matching 8105's raw−30); adjust
  subscreens: `0x06` while turning grind size (8105 push follows), `0x07`
  while turning RPM (8106 follows); exit fires 9004 + home `0x01`.
- Pour page `0x03` (9001 `IN_BREWER` with 4× LE u32 `(volume, temp_c,
  pattern, temp_c again)` — **machine default volume is 250 ml**, matching the
  chosen number-entity default); subscreens `0x08` pattern (8107 follows),
  `0x09` temperature (8108 follows); exit fires 9006 — but one exit of three
  had NO 9006 while `0x01` fired every time → 8023/heartbeat is primary,
  9xxx auxiliary. `0x03` fired on ALL four knob entries this session — the
  2026-07-19 "inconsistent emission" did not recur.
- Scale page `0x04` → `0x05`, 9002/9008 both confirmed firing on knob
  entry/exit.
- **Descale confirm screen `0x2F`** (pour-page knob-triple-press); moving the
  selection to "cancel" changes it to `0x32`; pressing cancel → home.
- **Scale-calibration confirm screen `0x39`**; cancel-selected `0x3A`.
- **Grinder calibration** (grind-page triple-press): NO separate confirm
  screen observed — it started immediately: `0x22` + 40506 spin-up, `0x26`
  then `0x27` during the sweep, 40505 `RD_GearReport` streaming gear position
  (~5 Hz, 0x40 → 0x02 → back up), completion = 40526 raw 85 (consistent with
  [[xbloom-grinder-calibration-completion-signal-saga]]), then `0x25`
  complete screen. (The triple-press also produced 9004/9000 in/out flapping
  right before start — the presses register as page enter/exit first.)
- `0x0A`: observed once at home with ~100 g on the scale; deliberate re-test
  (home → place weight → wait 15 s) did NOT reproduce it. Unexplained.
- `0x41` Easy home confirmed again (accidental dial flip; 11518 echo).

**Tare (8500) verdict for D1**: works from ANY screen — sent from home with
~100 g loaded: ACK + weight snapped to 0.0 instantly. Side effect: the machine
switches its own display to the scale page (`0x04` → `0x05`). So the tare
button needs no enter/exit wrapping, but users will see the machine land on
the scale screen.

**Why:** these codes are the entire foundation of the standalone-mode overhaul
(SPEC.md T3/T4/T16); re-deriving them needs another maintainer-at-machine
session.

**How to apply:** T3 maps 0x02/0x03/0x04/0x05 (+ subscreens as the same page)
to `screen_code`; T16 maps 0x2F/0x32 → descaling-wait, 0x39/0x3A →
calibrating_scale, and 0x25/0x26/0x27 (+ existing is_calibrating tracking) →
calibrating_grinder; machine-entered grinder cal is detectable from 0x26/0x27
(+40505/40506 burst) even though it starts without a confirm screen. Treat
9000/9001 snapshots as a knob-sync source (C1: seed grind_size/rpm on page
entry). See [[xbloom-machine-alarm-channel-and-rtbp]] for the same sweep's
jadx half.
