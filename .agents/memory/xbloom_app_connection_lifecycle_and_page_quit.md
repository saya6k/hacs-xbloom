---
name: xbloom-app-connection-lifecycle-and-page-quit
description: "Decompile (2026-07-19) of the official app's AppDeviceManager/AppBleManager: the heart check DISCONNECTS after 2s of notification silence (it is not a reconnect watchdog), the whole supervise+reconnect loop is skipped while the app is backgrounded, and grinder/brewer pages are exited with 8012/8013 (not 8022) with finish() called regardless of BLE success."
metadata: 
  node_type: memory
  type: project
  originSessionId: efb12ddd-12cd-4a2f-8d7a-a3b406787f12
---

APK moved to the repo root (`xbloom_coffee_release.apk`, ignored by the
top-level default-deny `.gitignore`) and decompiled with `jadx` on
2026-07-19 to settle two live bugs: a machine that locked up hard after
being left connected overnight (needed a power-cycle), and cancel not
working from the two-stage arm state.

**1. The app's "heart check" is a disconnector, not a reconnect
watchdog.** `AppDeviceManager.initHeartCheck()` schedules
`AppBleManager.get().disconnect(true)` 2 seconds later;
`blueNotifyMessage`'s `onCharacteristicChanged` calls `removeHeartCheck()`
to cancel it on every notification. `initTimer()`'s 5s
`Observable.interval` re-arms it while connected, and separately calls
`connect()` when *not* connected — but only if `device.isAutoConnect()`.
So the official answer to "the link went quiet" is **drop it**, and
reconnect at most once per 5s tick. This integration instead does
`_async_force_reconnect()` (disconnect + immediate reconnect) — strictly
more aggressive than the app.

**2. The app never supervises or reconnects while backgrounded.**
`initTimer`'s callback returns early when
`App.get().getResumeTime() < App.get().getPauseTime()` (backgrounded) or
when the current activity is a scan activity. `toForeground()` reconnects
only if the last heartbeat is older than ~ExoPlayer's
DEFAULT_DETACH_SURFACE_TIMEOUT_MS. Net effect: the official client's BLE
link is a **foreground-only, actively-supervised** session. A permanently
held idle GATT link with a 24/7 reconnect supervisor (what HA does) is
outside the envelope the firmware is ever exercised in by the vendor's own
client — the most plausible explanation for the overnight hard lockup.

Corollary: because the app tolerates only 2s of silence, the machine must
stream notifications faster than 0.5 Hz whenever connected and awake, so
`_BLE_SILENCE_TIMEOUT_S = 15.0` is not mistuned as a staleness threshold.
The divergence is the *response* (reconnect vs. disconnect-and-stay-down),
and that `is_sleeping()` is not consulted. See
[[xbloom-connection-race-and-supervisor]].

**3. Leaving the grind/pour page is 8012/8013, not 8022.**
`GrinderActivity.onBackPressed()` sends `APP_GRINDER_QUIT` (8012),
`BrewerActivity.onBackPressed()` sends `APP_BREWER_QUIT` (8013) — both
previously "Present, unconfirmed" in `docs/en/protocol.md`, now confirmed.
`RD_BackToHome` (8022) is only sent by `MachineJ15Fragment`
(`backToHomeForMachine()`) from the machine-settings screen, never on page
exit. This integration's `async_cancel()` sends 8022 for the armed case
(see [[xbloom-two-stage-arm-confirm-buttons]]) — the arm state *is* the
"user is on the grind/pour page" state, so 8012/8013 is the matching
command.

**4. The app's UI teardown never depends on the BLE command landing.**
Both `onBackPressed()` implementations call `finish()` unconditionally,
immediately after `sendMessage(...)`, with empty success/fail callbacks.
`async_cancel()`'s early `return` on `_check_connected()` failure (which
skips clearing `_armed_operation`) contradicts this — and is worse than a
no-op, since a stuck armed flag makes the *next* button press confirm
(start a real grind/pour) instead of arm.

**5. Hardware-verified 2026-07-19** (natively on the Mac — see
[[xbloom-macos-native-ble-testing]] for why this is possible at all):

- 8012, 8013 and 8017 are all **accepted, each with a proper `0xC1` ACK**
  (`5802074c1f0c000000c1e444` / `...4d1f...c131db` / `...511f...c162df`),
  as are the 8006/8007 enters. The command-table status change from
  "Present, unconfirmed" to Active is now backed by direct evidence, not
  just the decompile.
- Idle telemetry is a **~10 Hz flood** (`CURRENT_WEIGHT2` and
  `WATER_VOLUME` at ~5 Hz each), **max gap 1.23s over 5 continuous
  minutes**. So `_BLE_SILENCE_TIMEOUT_S = 15.0` is comfortably
  conservative and a 15s gap really does mean a wedged link — the
  placeholder value turned out fine.
- **The machine did NOT sleep during 5+ minutes of connected idle**, and
  the stream never paused. The mechanism originally proposed for the
  overnight lockup — machine sleeps, telemetry stops, the old
  reconnect-inline watchdog storms — is therefore **still unproven**. The
  `is_sleeping()` gate on the watchdog is defensive, not demonstrated
  load-bearing. Don't cite it as the established root cause.
- What the measurement *does* establish independently: holding the link
  means absorbing ~10 notifications/second forever (~864k packets/day),
  which is its own argument for idle standby regardless of the sleep
  question.

**Why**: both live bugs traced back to the same wrong assumption — that
the integration should hold and defend a BLE link the vendor's own client
only ever holds while a user is looking at it.

**How to apply**: when connection-lifecycle behavior is in question, check
`AppDeviceManager`/`AppBleManager` before theorizing; the app's supervisor
is small and answers most of it. Re-decompile with
`jadx -d <out> --no-res --no-imports -j 8 xbloom_coffee_release.apk` (note
`-j`, not `--threads`).
