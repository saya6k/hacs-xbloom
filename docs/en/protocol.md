# XBloom Studio BLE protocol reference

> Source of truth — see [한국어](../ko/protocol.md) for the Korean translation
> (may lag). Written from this integration's own hardware captures and from
> statically decompiling the official Android app (`xbloom_coffee_release.apk`,
> via `androguard`/`jadx` — inspected as a zip/dex/source dump only, never
> published or redistributed). Supersedes reliance on the vendored
> `src/xbloom-ble/PROTOCOL.md` as the primary reference — see
> [ADR-001](../../adr/001-clean-room-reimplementation-of-xbloom-ble.md) for
> why. Every claim below traces to either a live capture against real
> hardware or a specific decompiled class/method; anything not independently
> confirmed is marked as such rather than presented as fact.

## Packet framing

```
header(0x58 0x02) | dev_id | type | cmd(2, LE) | len(4, LE) | const(0x01) | payload | crc(2)
```

- **`type`** is `0x01` for the vast majority of outbound commands, and
  `0x02` for a specific family: mode switch (`11511`), Easy Mode slot writes
  (`11510`/`11512`), and pour-radius/vibration-amplitude GET/SET
  (`11506`–`11509`). Sending one of these as type-1 gets no response at all
  (hardware-confirmed 2026-07-17, standalone capture bypassing HA).
- **Response marker byte**, immediately after the length field (offset+9):
  `0xC1` for a type-1 command's response, `0xC2` for a type-2 command's
  response. Empirically `0xC0 | type_code` — every command this integration
  sent before 2026-07-17 happened to be type-1, so the type-2 marker went
  unnoticed until the 115xx family above needed it. A parser that only
  checks `0xC1` silently drops every type-2 response.
- **Max realistic packet length**: bounded at 256 bytes when parsing. The
  telemetry stream (weight/water-volume) floods at multi-Hz, and a
  false-positive header-byte match inside that noise can read a garbage
  4-byte length field — bounding it turns a would-be corrupted-buffer abort
  into a simple resync-and-skip.
- **Outbound writes are chunked to ≤100 bytes** (`min(100, mtu_size - 3)`,
  floor 20), matching the official app's fastble `setSplitWriteNum(100)`.
  The firmware reassembles a command from multiple BLE writes — write
  boundaries mid-packet are fine, since framing is header+length driven, not
  write-boundary driven. This matters for long payloads (`8001`/`8004`
  recipe sends, `11510` Easy Slot writes) on low-MTU paths (e.g. ESPHome BLE
  proxies) where a single unfragmented write could be truncated.
- **The `8100` MTU handshake gates everything.** The machine silently
  ignores every other command — no display wake, no LED, no `RD_MachineInfo`
  — until `8100` (payload `[185, 1]`) has been sent and acknowledged.
  Independently confirmed by a second, unrelated reverse-engineering effort
  (`cryptofishbug/xbloom-recipe-cli`'s firmware-switcher APK, inspected
  statically) — same command id, same "session primer" role, same
  power-cycle recovery advice. A follow-on `8101` puts the machine into
  YMODEM firmware-receive mode for OTA updates — out of scope for this
  integration (it never flashes firmware), documented here only because the
  id sits right next to `8100`.
- **Back-to-back type-2 commands need spacing.** A gap under ~0.5s between
  two type-2 sends (GET-then-GET, GET-then-SET, or two Easy Slot writes)
  reliably drops the *second* command's response — the machine appears to
  still be busy replying to the first. Hardware-confirmed at 0.3s (fails)
  vs. 0.8s/1.0s/1.5s (succeeds) across repeated trials; every type-2
  call site in this integration uses an 0.8s gap for margin.

## Command table

Status legend: **Active** — this integration sends/handles it today, with a
confirmed payload shape. **Telemetry** — inbound, high-frequency, feeds a
sensor directly. **Present, unconfirmed** — a real command id (from the
vendored enum or the official app's own constant table) with no confirmed
payload semantics or call site in this integration; do not assume behavior
from the name alone.

### Outbound (`APP_*` and unprefixed setters)

| id | name | payload | status | notes |
| ---: | --- | --- | --- | --- |
| 3500 | `APP_GRINDER_START` | size, speed | Active | manual + recipe grind |
| 3502 | `CMD_CALIBRATE_GRINDER` | `[1000]` fixed | Active | fire-and-forget; machine runs ~120s sweep autonomously |
| 3505 | `APP_GRINDER_STOP` | — | Active | manual-grind stop only, not whole-recipe |
| 4506 | `APP_BREWER_START` | volume, temp, flow, pattern | Active | manual pour |
| 4507 | `APP_BREWER_STOP` | — | Active | manual-pour stop only |
| 4508 | water-source set | LE u32 (0=tank,1=direct) | Active | `WaterSourceType.ordinal()`; J20-only values (8/50) don't apply to Studio |
| 4510 | `APP_BREWER_SET_TEMPERATURE` | — | Present, unconfirmed | in vendored enum, no confirmed call site here |
| 4512 | `APP_TEA_RECIP_MAKE` | — | Active | execute queued tea recipe |
| 4513 | `APP_TEA_RECIP_CODE` | tea recipe blob | Active | queues a tea recipe; **not** 8004 — see brewing-notes.md |
| 8001 | `APP_RECIPE_SEND_AUTO` | recipe blob | Active | coffee recipe, with grinding |
| 8002 | `APP_RECIPE_EXECUTE` | — | Active | commits/starts the queued recipe |
| 8004 | `APP_RECIPE_SEND_MANUAL` | recipe blob | Active | coffee recipe, no grinding (bypass) |
| 8006 | `APP_GRINDER_IN` | — | Active | "enter grind screen"; sent internally before manual/recipe grind |
| 8007 | `APP_BREWER_IN` (enum name `RD_BREWER_IN`) | — | Active | "enter pour screen"; sent for app parity before manual pour, not required |
| 8012 | `APP_GRINDER_QUIT` | — | Present, unconfirmed | superseded by 3505/40519 in this integration's flows |
| 8013 | `APP_BREWER_QUIT` | — | Present, unconfirmed | superseded by 4507/40519 |
| 8016 | `APP_BREWER_SET_PATTERN` | — | Present, unconfirmed | in vendored enum, no confirmed call site here |
| 8017 | `APP_RECIPE_START_QUIT` | — | Active | dismiss the machine's own "insert pod" prompt |
| 8018 | `APP_GRINDER_PAUSE` | — | Active | manual-grind pause only, not whole-recipe |
| 8019 | `APP_BREWER_PAUSE` | — | Active | manual-pour pause only |
| 8020 | `APP_GRINDER_RESTART` | — | Active | manual-grind resume |
| 8021 | `APP_BREWER_RESTART` | — | Active | manual-pour resume |
| 8022 | `RD_BackToHome` (outbound despite the name) | — | Active | UI-state reset, sent at the start of every recipe |
| 8100 | MTU handshake | `[185, 1]` | Active | see Packet framing above; blocks all other commands until sent |
| 8102 | `APP_SET_BYPASS` | (max, min) cup-weight floats | Active | confirmed against the official app's `setCup`, not "preheat stage temps" as a third-party capture once claimed |
| 8103 | display brightness (`RD_LetType`) | one of `{1, 8, 15}` | Active | 3 fixed levels (L1/L2/L3); no GET counterpart |
| 8104 | `APP_SET_CUP` | (max, min) cup-weight floats | Active | same shape as 8102; used for the coffee/tea cup-bounds set |
| 11506 | pour-radius GET | — | Active | type-2; response is LE u32 at payload offset 0 |
| 11507 | pour-radius SET | LE u32 | Active | type-2; 5 discrete levels, ±80 around a per-device center from the cloud API |
| 11508 | vibration-amplitude GET | — | Active | type-2 |
| 11509 | vibration-amplitude SET | LE u32 | Active | type-2; 6 discrete levels |
| 11510 | `RD_EASYMODE_RECIPE_SEND` (outbound) | slot recipe blob | Active | type-2; all three slots (A/B/C) must be sent per batch, no single-slot write |
| 11511 | `RD_EASYMODE_TYPE` (outbound: mode switch) | mode code | Active | type-2; retries on ACK timeout while the machine reports sleeping |
| 11512 | `RD_EASYMODE_RECIPE_ORDER` (outbound) | hex-string `[3,0,1,2]` | Active | type-2; sent after an Easy Slot batch write |
| 40518 | whole-recipe pause | — | Active | `AppJ15AutoManager.pause()`; only for recipe-mode brews, not manual grind/pour |
| 40519 | `APP_RECIPE_STOP` | — | Active | whole-recipe stop |
| 40524 | whole-recipe restart/resume | — | Active | pairs with 40518 |
| 8500 | scale tare | — | Active | `CMD_TARE`, cherry-picked from `xbloom-ble` |

### Inbound (`RD_*`)

| id | name | payload | status | notes |
| ---: | --- | --- | --- | --- |
| 8009 | `RD_MachineSleeping` | — | Active | sets sleep flag; gates mode-switch retry |
| 8011 | `RD_MachineNotSleeping` | — | Active | clears sleep flag |
| 8015 | `RD_UNIT_CHANGE` | 3× LE u32 (weight/temp/water-source unit) | Active | pushed when units are changed on the machine's own touchscreen |
| 8023 | `RD_MachineActivity` | LE u32 `index` | Active | clears sleep flag unconditionally; `index` itself unused |
| 8105 | `RD_GRINDER_SIZE` | LE u32, `-30` offset | Telemetry | live grind-size knob |
| 8106 | `RD_GRINDER_SPEED` | LE u32 | Telemetry | live RPM; zeroed explicitly on grind-stop (0 is a real reading, not "unknown") |
| 8107 | `RD_BREWER_MODE` | LE u32, 0/1/2 | Telemetry | live pour-pattern knob |
| 8108 | `RD_BREWER_TEMPERATURE` | LE u32 | Telemetry | live brewer temperature |
| 8111 | `RD_EASYMODE_BEGIN` | LE u32, 0–2 | Active | Easy Mode brew started from the machine's own dial; maps to slot A/B/C |
| 8203 | `RD_AbnormalGearPosition` | — | Active | error event |
| 8204 | `RD_AbnormalDoseOrWater` | — | Active | error event |
| 9000 / 9001 / 9002 | `RD_IN_GRINDER`/`RD_IN_BREWER`/`RD_IN_SCALE` | — | Present, unconfirmed | enter-mode acks, no handler in this integration |
| 9003 | `RD_GRINDER_BEGIN` | — | Active, unreliable | can fail to fire during a real grind — see raw status-heartbeat frame below |
| 9004 / 9006 / 9008 | `RD_OUT_GRINDER`/`RD_OUT_BREWER`/`RD_OUT_SCALE` | — | Present, unconfirmed | exit-mode acks, no handler |
| 9005 | `RD_BREWER_BEGIN` | — | Active, early-firing | fires immediately after commit, well before real pour starts |
| 9009 | `RD_GRINDER_PAUSE` | — | Present, unconfirmed | no handler |
| 9010 | `RD_BREWER_PAUSE` | — | Active | mapped to `"paused"` notification |
| 9011 | `RD_TEA_RECIP_RESTART` | — | Active | steep resumed after a between-steep pause |
| 9012 | `RD_TEA_RECIP_SOAK` | — | Active | mapped to `"tea_soaking"` |
| 10507 | `RD_CURRENT_WEIGHT` | float32 | Telemetry | same layout as 20501 |
| 11512 (see outbound) | | | | |
| 11518 | `RD_EASYMODE_RECIPE_STATE` | — | Present, unconfirmed | decompile-confirmed to be a redundant mode-display echo, not slot/progress-related despite the name |
| 20501 | `RD_CURRENT_WEIGHT2` | float32 | Telemetry | scale weight, primary channel |
| 40501 | `RD_Pods` | 6 raw bytes → ASCII | Active | NFC pod detected; app hex-decodes 12 hex chars = 6 bytes, not 12 raw bytes |
| 40502 | `RD_BREWER_COFFEE_START` | — | Active | alternate "brewing started" signal |
| 40505 | `RD_GearReport` | — | Present, unconfirmed | no handler |
| 40507 | `RD_Grinder_Stop` | — | Active | grind end; zeroes live RPM; **not** a valid calibration-complete signal despite firing during calibration's homing move |
| 40510 | `RD_BLOOM` | — | Active | bloom notification |
| 40511 | `RD_Brewer_Stop` | — | Active | pour end |
| 40512 / 40513 | `RD_ENJOY` / `RD_ENJOY2` | — | Active | recipe complete |
| 40515 | `RD_TEA_RECIP_PAUSE` | — | Active | steep paused/ended between-steep |
| 40517 | `RD_ErrorIdling` | — | Active | mapped to `"no_beans"` error |
| 40520 | `RD_BYPASS` | — | Present, confirmed payload-less | decompile-confirmed a payload-less UI pulse, no state to expose |
| 40521 | `RD_MachineInfo` | fixed-offset struct | Active | connect-time snapshot: serial, firmware, mode, water-level-ok bit, grind-size/voltage; may never arrive on some firmwares — see AGENTS.md's retry/fallback notes |
| 40522 | `RD_ErrorLackOfWater` | LE u32 (0=empty, 1=refilled) | Active | bidirectional — not a one-shot error, see `water-level` handling |
| 40523 | `RD_WATER_VOLUME` | LE u32 | Telemetry | live tank volume |
| 40525 | `RD_EASYMODE_RECIPE_NUM` | — | Present, unconfirmed | no handler |
| 40526 | `RD_CurrentGrinder` | LE u32, `-30` offset | Active | parity with 8105; `raw == 85` while `is_calibrating_grinder` is the real calibration-complete signal |
| 40527 | `RD_BeforeVibration` | — | Present, confirmed payload-less | decompile-confirmed payload-less pulse |
| 50038 / 50039 | `RD_CalibrateStart` / `RD_Calibrating` | — | Active, best-effort | calibration start/progress pulses; not reliably sent on every unit — `async_calibrate_grinder()` doesn't depend on 50038 to start tracking |
| Raw status-heartbeat frame | (no cmd id — separate framing, `type` byte `0x57`) | state byte | Active | the only reliable `starting`/`brewing`/`ready` signal; the cmd-tagged path above (9003/9005/40507) is known-unreliable for that specific transition — see AGENTS.md |

Two ids appear in both directions with different meanings depending on
context and are **not** the same command: `4508` is a plain outbound
water-source setter (see table above); `8103` is used both as the outbound
brightness setter and appears in the vendored enum as `RD_LedType` — no
separate inbound handler exists for it as a response, only as the outbound
command id.

## Known transport quirks (summary — see `AGENTS.md` / project memory for the
full investigation history behind each)

- `8100` handshake must be (re-)sent before `RD_MachineInfo` or any other
  request/response command can succeed — including the pour-radius/
  vibration-amplitude GETs, which were silently dropped in an early version
  of this integration because they were fired before a *second*, retried
  handshake had completed.
- Type-2 commands (`115xx` family) need `type_code=2` on the request *and*
  accept `0xC2` (not `0xC1`) on the response, and need ≥0.8s between
  back-to-back type-2 sends.
- `MachineInfo` string fields (model, etc.) are `0xFF`-padded, not
  NUL-padded — always decode through `strict_ascii()` (printable
  0x20–0x7E only), never a naive UTF-8 decode.
- Easy Mode slot writes (`11510`) must be sent as a full A/B/C batch with no
  commit frame, from PRO mode — a single-slot write hangs the machine at a
  "saving" status.
- No-grind (bypass) coffee recipes need a real, nonzero `dose` in the `8102`
  payload — `dose=0` silently hangs the arm with no error notification.
