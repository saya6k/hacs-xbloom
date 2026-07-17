---
name: xbloom-wake-retry-universal-pattern
description: "The official app's 1.5s-ACK-timeout/retry-while-asleep pattern (previously implemented only for mode-switch) is actually universal across every command AppBleManager.sendMessage sends (DefaultTimeOut=1500L) - generalized to grind/pour/tare/calibrate/execute-recipe/easy-slot-write via coordinator._async_retry_while_sleeping after a hardware report that commands silently did nothing while the machine was asleep."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Hardware-reported 2026-07-17/18: operating the machine (grind/pour/tare/
calibrate/execute recipe/easy-slot write) while it was asleep silently did
nothing — no error, just no effect. This integration had only implemented
the official app's ACK-timeout retry pattern for the mode-switch command
(`_async_switch_mode_with_retry`, see
[[xbloom-easymode-ack-marker-and-mode-switch-retry]]).

Re-decompiling `AppBleManager.java` (`xbloom_coffee_release.apk`) to check
"how does the app's wake logic work" found: `DefaultTimeOut = 1500L` is a
**field-level constant**, the default timeout for `sendMessage()` — the
app's single, universal command-send wrapper every one of its commands
goes through, not something specific to mode-switch. `createDisposable`'s
ACK-timeout handler is identical everywhere: if `AppDeviceManager.
isSleeping()` is true at timeout, resend the identical command (up to 3
retries, 4 total sends); the instant it's not sleeping, stop — a non-sleep
failure won't be fixed by resending. There is no dedicated "wake" command;
the retry itself (re-sending the same write) is the only wake mechanism the
app has.

**Generalized** via a new `coordinator.connection.ConnectionMixin.
_async_retry_while_sleeping(action)` helper: calls `action()`, waits
`_WAKE_RETRY_DELAY_S` (1.5s, same value as `_MODE_SWITCH_ACK_TIMEOUT_S`),
checks `client.is_sleeping()`, and resends (up to `_WAKE_RETRY_MAX_ATTEMPTS`
= 4 total) while it's still true. Unlike the mode-switch retry, this has no
per-command ACK to verify against (most commands here have no dedicated
confirmation notification the way mode-switch has `mode_ack_hex`), so
`is_sleeping()` after the wait is used directly as the retry condition —
the same signal the app itself gates on. Blind retry on that condition is
judged safe: while confirmed still asleep, the machine's application layer
isn't processing incoming commands at all (the same "ignores everything
until awake" behavior the 8100 handshake gate exhibits at connect — see
[[xbloom-8100-handshake-and-firmware-history]]), so a still-sleeping resend
is very unlikely to double-fire whatever the first send was.

Wired into: `async_pour`, `async_grind`, `async_tare_scale` (operations.py),
`async_calibrate_grinder` (advanced_settings.py — only the raw send is
retried, not the follow-on bookkeeping, or a retry would fire a duplicate
`grinder_calibration_started` event and schedule a second 180s timeout
task), `async_execute_recipe` and `async_write_easy_slot` (recipes.py — the
whole multi-command sequence is retried from the top, since if asleep none
of it landed the first time). `async_pause_resume`/`async_cancel` were
deliberately left unwrapped — those are typically issued while something is
already happening, so the machine is very likely already awake at that
point.

**Why**: a single field-name grep (`isSleeping()`) missed this the first
time — the real call sites use `AppDeviceManager.INSTANCE.isSleeping()`,
not a bare method call, so the pattern looked mode-switch-specific until a
fuller re-read of `AppBleManager.java` around `createDisposable` surfaced
`DefaultTimeOut`'s universal use.

**How to apply**: any new user-triggered action that sends a BLE command
and doesn't already have its own ACK-based retry should be wrapped in
`_async_retry_while_sleeping` too, following the same pattern. Not
hardware-verified beyond the original mode-switch case this generalizes
from — if a wrapped action still silently no-ops while the machine is
asleep, capture real `is_sleeping()`/notification traffic before assuming
the retry logic itself is wrong.
