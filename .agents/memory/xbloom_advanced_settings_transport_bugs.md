---
name: xbloom-advanced-settings-transport-bugs
description: "Five-layer debugging saga for pour_radius/vibration_amplitude sensors staying unknown - offset-0 scan bug, missing type_code=2, wrong marker byte, GET fired before machine awake, and a too-short gap between back-to-back type-2 sends. Also generalizes to SET and to Easy Slot writes."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Getting `pour_radius`/`vibration_amplitude` (see
[[xbloom-advanced-features-jadx-findings]]) working on real hardware took
five separate hardware-reported rounds, each fixing a real but different
bug — a case study in not declaring victory after one plausible-looking fix.

**Layer 1 (2026-07-17)**: `_scan_for_advanced_settings` only checked byte
offset 0 of the notification buffer, unlike this file's other raw pre-scans
(`_scan_for_machine_info` does `raw.find(...)` anywhere in the buffer).
Silently missed the target frame whenever a BLE notification carried a
leading unrelated/partial frame first — routine, given the weight/water
telemetry stream floods concurrently. Fixed to walk the whole buffer like
`_split_and_parse` does.

**Layer 2**: that fix alone didn't work — the machine wasn't responding to
the GET at all. Root-caused by connecting directly to the real machine from
a plain Python script (bypassing HA — no HA instance reachable in this dev
environment, see Testing below): sending `11506`/`11508` with the default
`type_code=1` gets zero response ever; resending with `type_code=2` (the
same type the `11510` Easy Slot family needs) got an immediate reply. The
response's marker byte is also type-dependent: type-2 responses carry
`0xC2` at offset+9, not `0xC1` — apparently the marker is `0xC0 |
type_code`, never surfaced before since every other command this
integration sends is type-1. Both bugs (type_code and marker check) had to
be fixed together. Live values cross-confirmed against independent
sources: `pour_radius: 750` matched the cloud API's `initPouringRadius` for
that serial; `vibration_amplitude: 1000` matched level-0's raw value.

**Layer 3**: still `unknown` after a real HA restart. The GET was fired
unconditionally right after `client.connect()` returns, but on this
machine/session MachineInfo didn't arrive from the first `8100` handshake —
the retry loop needed a second handshake ~5s later. The GET, sent during
that dead window, was silently dropped exactly like
[[xbloom-8100-handshake-and-firmware-history]] predicts — it's a
request/response command just as vulnerable to that window as MachineInfo
itself, but wasn't gated on the same signal. Fixed: the GET only fires if
`client.status.serial_number` is already populated right after connect;
the retry loop fires it instead when MachineInfo arrives late.

**Layer 4 (a red herring)**: while debugging layer 3, a log dump showed
zero `SEND CMD`/`RECV CMD` lines anywhere despite this integration's own
loggers clearly firing — a per-logger level override in that install was
suppressing the vendored `xbloom.core.client` namespace specifically. This
made log-grepping a dead end in that environment even though nothing was
wrong at the protocol level at that point. Fixed by also logging on this
integration's own loggers (confirmed visible in the same dump), so this
class of command doesn't depend on a third-party logger namespace nobody
expects to re-enable.

**Layer 5**: pour_radius worked, vibration_amplitude still didn't — a
0.3s gap between the two GET calls made the second's `SEND CMD 11508` go
out but get zero response, consistently (4 trials); 0.6s/1.0s/1.5s all
succeeded. The machine appears to still be busy replying to the first
type-2 request when the second arrives. Widened the gap to 0.8s.

**Generalizes beyond GET**: directly reproduced the same 0.3s-drops-2nd-
type-2-command signature on `async_set_advanced_settings`'s SET pair
(2/2 trials failed at 0.3s, 2/2 succeeded at 0.8s) — both gaps widened.
`brewing.py`'s Easy Slot writes (`11510` ×3 + `11512` order frame, the same
115xx type-2 family) use the identical pattern and were widened to 0.8s too
on the reasoning that the drop is a transport-layer property of back-to-back
type-2 commands, not specific to which command — **not independently
hardware-verified for 11510 itself**, since that would mean risking
overwriting a user's real Easy Mode slots to test.

**Why**: each layer looked like "the" fix at the time; only sustained
hardware feedback across multiple rounds surfaced the full picture.

**How to apply**: if any type-2 command (115xx family) misbehaves on real
hardware, check in this order: type_code=2 set? marker check accepts 0xC2?
GET/SET gated on MachineInfo-confirmed rather than fired blind post-connect?
≥0.8s since the last type-2 send? Don't assume a single fix is sufficient
without a full hardware round-trip confirming it.
