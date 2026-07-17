---
name: xbloom-easymode-ack-marker-and-mode-switch-retry
description: "The mode-switch ACK (cmd 11511) was silently dropped by the same type-1-only marker-byte assumption, unrelated to the type-2 GET/SET bugs; fixed generally in the shared framing pipeline. Mode-switch retry now mirrors the official app's ACK-timeout-while-sleeping spec, requiring new sleep-state tracking (cmds 8009/8011/8023)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

`_split_and_parse` originally only accepted marker `0xC1`. Cmd `11511`
(mode switch) is sent as `type_code=2`, so its response carries marker
`0xC2` like every other type-2 command — but unlike pour_radius/vibration
(which needed a separate raw pre-scan since they aren't in the vendored
enum at all, see [[xbloom-advanced-settings-transport-bugs]]), `11511`
**is** a valid `XBloomResponse` enum member and would otherwise flow
through the normal `_handle_response` path — the marker check alone
silently discarded the frame before it got there. Hardware-confirmed
2026-07-17: captured the real ACK frame
(`580207f72c10000000c2913278569080`, marker `0xc2`, payload matching the
"easy" mode code) arriving on the wire while `_mode_ack_hex` stayed `None`
the whole time. Renamed `_ADVANCED_SETTINGS_MARKER_BYTE` to the more
accurate `_TYPE2_MARKER_BYTE` and widened `_split_and_parse`'s check to
accept both `0xC1` and `0xC2` — a general fix to the shared notification
pipeline, not scoped to one command.

**Mode-switch retry spec, decompiled 2026-07-17**:
`AppBleManager.sendMessage` (the app's general command-send wrapper, used
for `setDeviceMode` same as everything else) retries the *same* command on
a 1.5s ACK timeout while `AppDeviceManager.isSleeping()` is true, up to
`retryCount < 3` (4 total sends) before surfacing "BLE ACK Timeout" — never
tears down the connection. `coordinator._async_switch_mode_with_retry()`
mirrors this (`_MODE_SWITCH_ACK_TIMEOUT_S=1.5`, `_MODE_SWITCH_MAX_
ATTEMPTS=4`), replacing a blind `sleep(0.5)` at all four mode-switch call
sites. This only works because of the marker-byte fix above — without it
every retry would exhaust for nothing, since the ACK could never be
observed.

**The `isSleeping()` gating itself needed new tracking**: cmds `8009`
(`RD_MachineSleeping`)/`8011`(`RD_MachineNotSleeping`)/`8023`
(`RD_MachineActivity`) were already valid enum members but had no handler
at all. Decompiled from `MachineSleepingModel`/`MachineNotSleepingModel`/
`MachineActivityModel.excute()` — 8009 sets sleeping, 8011 and 8023 both
clear it unconditionally (8023 also carries a payload `index` the app only
uses for a UI event, unrelated to the flag). `_client.py`'s
`_handle_response` sets `self._status.is_sleeping` on all three, exposed
via `client.is_sleeping()`; the retry loop now `break`s on the first ACK
timeout while `not client.is_sleeping()`, instead of always exhausting all
4 attempts. No raw pre-scan needed — ordinary type-1 notifications the
vendored enum already resolves.

**Live-verified**: 4/4 mode switches (easy→pro→easy→pro) confirmed on the
first attempt post-fix, no retries needed. The `isSleeping()`-gating part
of the retry logic itself is **not hardware-verified** — its effect only
shows up on a machine that's actually gone idle-to-sleep between switches.

**Why**: two unrelated bugs (a general framing bug, and a missing feature)
both had to land before mode switching became reliable.

**How to apply**: any new type-2 command that seems to never get an ACK —
check the marker-byte fix is actually in place before assuming a new
transport bug. If a mode switch fails to resume retrying after a real
sleep/wake cycle, that's the untested part to look at first.
