---
name: xbloom-water-shortage-and-level-derivation
description: "RD_ErrorLackOfWater (40522) is bidirectional (0=empty, 1=refilled), not a one-shot error - an earlier implementation that treated every occurrence as a shortage caused a permanent post-refill deadlock; a later bug independently caused a false \"problem\" reading by trusting the unreliable MachineInfo snapshot flag once serial_number was known."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

**Bidirectional refill signal** (fixed 2026-07-17, from a real deadlock
report): `RD_ErrorLackOfWater` (40522)'s payload first 4 bytes (LE uint32)
are `0` = tank empty, `1` = water restored — found from a report where
water shortage fired, the user refilled, and every recipe execute stayed
blocked. Two compounding bugs: `coordinator._water_shortage` could only be
cleared by a successful-brew notification, which the low-water execute gate
itself made unreachable; and the firmware's own "refilled" 40522 (value=1)
was being counted as *another* shortage since `_client.py` fired
`("error", "water_shortage")` for every 40522 regardless of payload.
Decompiled ground truth: `ErrorLackOfWaterBleModel` parses
`data.substring(0,8)` → `reverseHex` → int, and `HomeActivity`'s handler
calls `dismissWaterScarcityAnimation()` on value==1 /
`showWaterScarcityAnimation()` on value==0 (skipping the warning entirely
when `device.waterFeed != 0`, matching this integration's existing
`water_source == WATER_SOURCE_TANK` gate). Fixed: 40522 is special-cased
(removed from the generic error map), fires `("notification",
"water_refilled")` on value=1 vs `("error", "water_shortage")` on value=0,
and mirrors the value onto `status.water_level_ok` — which the vendored
client otherwise only ever sets once from the connect-time `RD_MachineInfo`
snapshot. `coordinator._dispatch_event` clears `_water_shortage` on
`water_refilled`. The value=1-on-refill semantics are inferred from the
app's dismiss logic, not captured live — if a refill ever fails to clear
state on real hardware, capture the actual 40522 traffic before assuming
the semantics are wrong.

**The false "problem" bug** (separate, fixed same day): even after the
above, `binary_sensor.problem`'s water derivation did
`water_ok = bool(s.water_level_ok) if s.serial_number else not
self._water_shortage` — i.e. once MachineInfo had been observed even once,
it trusted the raw flag unconditionally. This directly contradicted
[[xbloom-machineinfo-reliability-and-padding]]'s own documented
unreliability of that flag. On a unit whose connect-time snapshot happens
to read False with a full tank, and that never fires a follow-up 40522 to
self-correct (the common case — most sessions have no water error), the
"problem" reading was permanent for the whole connection. Predates every
session in this file's history — only surfaced from a real "물 수위가
문제있음" (water level shows a problem) report after a normal reconnect.
Fixed: `water_ok` is now derived purely from the event-driven
`_water_shortage` flag unconditionally, dropping the `serial_number`-gated
branch entirely.

**Why**: two independent bugs in the same feature, six months apart,
both traced back to trusting a connect-time snapshot flag that this
integration's own documentation already flagged as unreliable — the fix
each time was to lean more on the event stream and less on the snapshot.

**How to apply**: never reintroduce a code path that trusts
`s.water_level_ok` directly — water state must always derive from the
event-driven `_water_shortage` flag. If water state ever looks wrong again,
check for a similar "trust the raw snapshot once we've seen it" pattern
before assuming a new protocol bug.
