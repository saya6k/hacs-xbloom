---
name: xbloom-brew-start-verification
description: "Phase 3 (2026-07-19): 8002's echo ACK ≠ brew started — verify from the raw state heartbeat (new mapped codes 0x1E awaiting_confirm / 0x1F recipe_loaded, both live-confirmed); 40518-as-start refuted a second time on this machine (bounced awaiting_confirm back to recipe_loaded); recipe cancel slimmed to bare 40519; error events now tear run flags down; pause fallback state-gated."
metadata: 
  node_type: memory
  type: project
  originSessionId: efb12ddd-12cd-4a2f-8d7a-a3b406787f12
  modified: 2026-07-19T07:30:18.942Z
---

Implemented 2026-07-19 (app-parity Phase 3), building on
[[xbloom-ratio-footer-grind-gate]]'s bisection session.

**Brew-start verification** (`brewing._async_verify_brew_started`, runs
after 8002 in both the single-shot and confirm paths): watches
`client.status.raw_state_label` up to 8s — `starting`/`brewing` → started;
`water_shortage`/`no_beans` → machine refused (raise with reason);
timeout → raise `BrewStartUnconfirmed`. **Sends nothing while watching.**
This replaced "assume started", and the very first hardware probe
validated the design in the best possible way: the machine genuinely
stalled (below) and the verifier correctly refused to claim success.

**New raw-state codes, live-confirmed on this machine** (adopted from
HomoLand/xbloom-studio-brew's D500 notes, then observed directly):
`0x1F recipe_loaded` (after the arm chain lands) and `0x1E
awaiting_confirm` (after 8002 when the machine wants its own screen
confirmed). Also mapped on their word but NOT yet seen here: `0x0C` →
water_shortage, `0x0F` → no_beans. All four are in `_RAW_STATE_LABEL_MAP`,
the state sensor's ENUM options, and all 3 translation files.

**40518-as-start: refuted AGAIN, live.** HomoLand/Janczykkkko both claim
40518 starts a brew from awaiting-confirm (their hardware). Tried here
2026-07-19: the machine bounced from `awaiting_confirm` back to
`recipe_loaded` — no start. Consistent with this project's original
refutation ([[xbloom-40518-and-8104-third-party-claims-refuted]]). Their
other 40518 warning ("into a running brew it aborts back to armed") stays
unverified here but motivated the pause-gate below; don't fire 40518 on
any guess.

**What awaiting_confirm actually is** (settled by the 2026-07-19 stall
probe + the user reading the machine screen): the machine's own pre-start
screen, showing values straight from our payload — "35 13 →" = grind 35,
ratio 13 (the footer's 13.9 truncated), with an arrow to tap. In the
normal flow it is a **~2.7s transient**: 8002 → 0x1E → auto-proceed to
0x22 starting (well inside the verifier's 8s window). The earlier stall
was the machine sitting on that screen waiting for the arrow tap; a human
tapping it starts the brew, which is exactly what the verifier's error
message tells them. WHY it sometimes waits instead of auto-proceeding is
still not established.

**Two protocol discoveries from the same probe** (recorded in
docs/*/protocol.md): cmd 8023's `index` payload mirrors the raw
status-heartbeat state code byte-for-byte (0x01 home / 0x1F / 0x1E / 0x22
arrived in lock-step on both channels — they are one state stream, and
0x01 = home/idle is unmapped but real); and **cmd 40506** (absent from the
APK's own constant table) fired exactly at the 0x22 grind-begin moment —
candidate real grind-start notification, which would explain why 9003
RD_GRINDER_BEGIN never fires during recipe grinds. Single observation.

**Bean supply matters for probes**: the user observed the grinder running
empty (공회전) on a later probe — repeated probe grinds drain the hopper,
so refill before physical grind verification, and don't read an empty-spin
grind as a protocol failure.

**The machine's screen sequence during a recipe** (user-reported
2026-07-19, matching the stall screens): recipe/confirm screen shows
`<grind size> <ratio int> →` (35 13 — both straight out of our 8001
payload, ratio being the footer byte's integer part), then grinding shows
`<size> <RPM> →` (35 60), then brewer shows `<pattern icon> <temp> →`
(spiral 93). The `→` glyph and `X` are different affordances on the same
screen — turning the knob on `→` flips it to `X` (cancel), so a stalled
awaiting_confirm screen may show either depending on whether the knob was
touched.

**cmd 40506 disambiguation still open**: confirmed absent from the APK's
CommandParams (40505 GearReport → 40507 Grinder_Stop gap). Two candidate
readings of the single observation (fired exactly at grind-stage begin,
with an EMPTY hopper): grind-begin counterpart of 40507, or a
no-beans-adjacent signal (the user leans no-beans; note the app's actual
no-beans alarm is 40517 RD_ErrorIdling "空磨提醒"). Discriminator: watch
the next live grind WITH beans loaded — 40506 firing again means
grind-begin; only-when-empty means no-beans-ish.

**Cancel slimmed** (`operations.async_cancel` recipe branch): bare 40519
only, matching `AppJ15AutoManager.stop()`. The old chasers (3505, 4507,
8022 + sleeps) are gone — the app never sends them when stopping a brew.
Bare 40519 was hardware-proven by the bisection probes (cleanly stopped
grind-stage and pour-stage runs repeatedly).

**Error teardown** (`state._finish_run`): `no_beans` /
`abnormal_dose_or_water` / `abnormal_gear_position` error events now clear
`_executing_recipe`/`_active_recipe_pours`/`current_pour_index`/
`_active_operation` (the app posts BleEnjoyEvent on ErrorBle1/ErrorIdling).
`water_shortage` is deliberately excluded — hardware-observed firing
mid-brew while the brew ran to completion, and the app likewise excludes
ErrorLackOfWater. Stale flags misroute cancel, pause, and idle standby.

**Pause fallback state-gated** (`operations.async_pause_resume`): with no
`_active_operation`, 40518/40524 only fire from
`starting`/`brewing`/`grinding`/`paused`; anything else is a logged no-op.

**Tea 4512 is ACK-gated** (`send_and_wait`, 3.0s) — the one place the
third-party repos' echo-gating matched our primitive directly.

**How to apply**: brew-start problems → read the label sequence first
(`recipe_loaded` → `awaiting_confirm` → stuck means the machine wants a
human); never "fix" a stall by firing state-sensitive commands blind.
