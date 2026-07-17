---
name: xbloom-connection-race-and-supervisor
description: "A connection supervisor + silence watchdog mirrors the official app's poll loop for backstop reconnects and stale-link detection; outbound writes are chunked to <=100 bytes matching the app's fastble config; a NoneType crash race between disconnect callback and an in-flight connect was fixed by holding a local client reference throughout async_connect."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

**Auto-reconnect** (since 2026-07-04): `HABleakConnection`'s
`disconnected_callback` calls `coordinator._handle_unexpected_disconnect()`,
which reconnects unless the drop was caused by `async_disconnect()` itself
(tracked via `_manual_disconnect`).

**Connection supervisor + silence watchdog** (2026-07-17), deliberately
mirroring the official app's `AppDeviceManager` poll loop (`jadx`/
`androguard` from `xbloom_coffee_release.apk` — `initTimer()`'s
`Observable.interval(0, 5, SECONDS)`, `initHeartCheck()`/
`removeHeartCheck()`, `blueNotifyMessage`'s `onCharacteristicChanged`
resetting the watchdog on every notification). Two gaps this closed:

1. **No backstop retry** — `_handle_unexpected_disconnect()` fires once per
   BLE-level drop and gives up silently if that one attempt fails.
   `coordinator._async_update_data()` now also drives
   `_maybe_schedule_reconnect()` on every poll tick (5s default): if not
   connected, not mid-connect, and not user-disconnected this session, it
   schedules another `async_connect()`. This also means the integration now
   auto-connects at HA startup for free.
2. **A GATT link can go silent without ever firing a disconnect event** —
   `is_connected` only reflects GATT state, not whether the firmware is
   still talking. `_on_notification()` stamps
   `_last_notification_monotonic` on every raw notification (the telemetry
   stream floods at multi-Hz normally, so a large gap is a reliable stale-
   link signal); the coordinator forces a reconnect if that gap exceeds
   `_BLE_SILENCE_TIMEOUT_S` (15s — a deliberately conservative placeholder,
   **not hardware-verified**; the app's own threshold is 2s but this
   dev environment has no real Bluetooth to cross-check the actual
   telemetry cadence against).

Deliberately session-only, not persisted to `entry.options` — unlike the
app, which stores its disconnect preference in the device DB. An HA restart
always auto-connects again regardless of the last session's switch state.

**Outbound writes chunked to ≤100 bytes** (2026-07-17), matching the
official app's fastble `setSplitWriteNum(100)` — see
`docs/en/protocol.md`'s framing section for the wire-level detail. Not
hardware-verified over a real low-MTU proxy path; on a normal adapter,
packets under 100 bytes behave exactly as before.

**The NoneType connect race** (fixed same session as the manual-operation
targeting work, 2026-07-17): `_handle_unexpected_disconnect()` is bleak's
`disconnected_callback` — it can fire at any time, including while a
*different*, already-running `async_connect()` call is past its own
`connect()` and using `self.client` for follow-up steps
(`_apply_unit_preferences`, the final `serial_number` check). Since the
callback sets `self.client = None` directly without acquiring
`_connect_lock`, a disconnect landing in that window crashed the in-flight
call with `'NoneType' object has no attribute '_send_command_raw'`/
`'...has no attribute 'status'` — hardware-confirmed: both errors logged 4
seconds after the same reconnect's own "dropped unexpectedly" warning, from
a single HA restart. Fixed: `async_connect()` now holds its own client in a
local variable throughout its body (a concurrent `self.client = None` can't
be raced out from under a local reference); `_apply_unit_preferences()`
gained an optional `client` parameter for the same reason. **Not
hardware-verified** — the race is real and the fix is straightforward, but
reproducing the exact timing on demand isn't practical in this dev
environment.

**Why**: BLE connection management on this device is genuinely fragile —
three distinct, independently-discovered robustness gaps (no backstop
retry, silent stale links, a real asyncio race) all needed fixing over
time, none obvious from a single bug report alone.

**How to apply**: if `_BLE_SILENCE_TIMEOUT_S` ever needs retuning (fires
spuriously, or too late), that's a signal to adjust the constant, not
evidence the watchdog mechanism itself is wrong. Any future code touching
`self.client` inside `async_connect()` should keep using the local-variable
pattern, not read `self.client` directly mid-method.
