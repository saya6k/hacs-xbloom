---
name: xbloom-app-parity-controls-jadx-round2
description: "2026-07-19 jadx round 2 + same-day hardware pass: 8023 = RD_MachineActivity (identity solved), 8003/8014 scale page enter/exit live-verified, 4510/8016/8006 live-adjust confirmed on hardware, 8001/8004 chosen by isSetGrinderSize, Easy Mode brews recipes fine — _ensure_pro_mode rationale REFUTED (removal pending go-ahead); new screen codes 0x41/0x02/0x04/0x05/0x1D."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9df22f00-e12a-4774-8845-697ce76887a4
  modified: 2026-07-19T12:09:29.595Z
---

Second jadx sweep of `xbloom_coffee_release.apk` (2026-07-19), answering the
open questions from the stall probe. Docs: PR #126 (protocol.md en/ko).
Implementation: PR #127 (armed live-adjust, scale buttons,
water_shortage_cleared event) — **hardware-verified same day** (native
macOS bleak probes, session-9df22f00 scratchpad `verify_pr127_controls.py`
/ `probe_easy_recipe.py` / `probe_easy_manual_page.py`): 8003/8014 ACK +
screen transitions (scale = status `0x04`→`0x05`, home `0x01` on exit);
4510 ACK echoes the parsed value as float32 (880 → `00005c44` = 880.0);
8016 and the 8006 live-adjust re-send ACK cleanly. New unmapped screen
codes: `0x01` pro home, `0x41` easy home, `0x02` grind screen,
`0x04`/`0x05` scale, `0x1D` connect-time transient. Still unwitnessed:
whether the machine display visibly updates on the live-adjust sets (no
8105-8108 echo follows them — those pushes are knob-driven), and whether
8007 visibly opens the pour screen (no status/8023 change followed it).

**8023 identity solved — `RD_MachineActivity`** (`CommandParams.java`,
handled by `MachineActivityModel`): payload first 4 bytes LE = `index`,
which is the raw heartbeat state code (we already knew the mirroring).
App semantics: *any* 8023 clears the sleeping flag; only `index == 1`
(home) is re-posted on the bus, where `AppJ15AutoManager` treats it as
end-of-session for auto-brew tracking; `TeaAutoFragment` refreshes its
pour list on `index == 35` (0x23). So "index unused" was wrong in both
directions — the app keys real behavior off specific values.

**Scale page has real enter/exit commands**: `8003` (raw literal, no enum
name — "电子秤功能进入指令") sent ACK-gated by `HomeActivity.onClickOperator3`
before opening the app's scale page; `8014` ("退出称重页面") from
`ScaleActivity.onBackPressed`. Tare (8500) and weight-unit (8005) are the
only other scale-page sends; entering via machine knob is reported by
9002/9008 (IN_SCALE/OUT_SCALE).

**Live adjustment = re-send/setter, page-scoped**: the app adjusts an
armed (page-open, not running) machine by (a) re-sending `GRINDER_IN`
8006 with new (size, RPM) — `GrinderActivity.adjustGrinder`, best-effort
`sendMessageNoShowFail`; (b) `4510` with `roundToInt(temp × 10)` as a
plain LE u32 (NOT the float32-bits encoding 4506 uses) —
`checkAndSetTemperature`; (c) `8016` with the pattern code —
`checkAndSetSpiral`. All three UI controls are disabled while the
operation actually runs. PR #127 mirrors this gated on
`_armed_operation`.

**8001 vs 8004**: `RecipeDetailActivity.sendCodeJ15` picks 8001 when
`recipe.isSetGrinderSize == 1`, else 8004 — confirming our
AUTO(grind)/MANUAL(no-grind) naming.

**The app has NO mode gate on recipe execution, and hardware confirms
none is needed** (live 2026-07-19, `probe_easy_recipe.py`): machine
switched to Easy (11511 ACK, home code `0x41`), full chain
`8102`→`8104`→`8001`→`8002` ACKed, then `0x1F recipe_loaded` → `0x1E
awaiting_confirm` (~2.7s transient again) → `0x22 starting` + the grind
stage began; bare 40519 cancelled cleanly back to easy home. The manual
grind page also opens in Easy Mode (8006 → 8023 `index=0x02` — notably
with NO raw heartbeat frame, so 8023 is the more complete page-change
channel). `connection._ensure_pro_mode`'s rationale ("Easy Mode silently
ignores the Pro brew commands — hot water only") is therefore **refuted**:
the original symptom was the ratio-footer grind-gate bug
([[xbloom-ratio-footer-grind-gate]]). A follow-up with-beans probe
(`probe_beans_confirm.py`) also ran a **manual grind in Easy Mode**
(8006 → 3500 → `0x22` + 40506 fired, grinder ran → 3505 → 40507), closing
the last gap, and the user approved removal — **`_ensure_pro_mode`,
`_restore_persisted_mode`, and `_auto_switched_to_pro` are deleted**
(PR #127). Only 4506 manual pour in Easy Mode remains formally untested.
The Easy-slot batch write keeps its own Pro switch
(`recipes.async_write_easy_slots`, separate hardware-established
requirement). Bonus from that probe: the vendored `grinder.is_running`
stayed False through a real grind — yet another cmd-tagged-path
unreliability datapoint; trust the heartbeat/40506, not it.

**Error resolution signals** (basis for PR #127's cleared event):
only 40522 is bidirectional (value 1 = refilled). 8203/8204
(AbnormalGearPosition/AbnormalDoseOrWater) and 40517 (ErrorIdling =
no-beans, "空磨提醒") are payload-less one-shot toasts in the app with no
wire-level clear. **User decision 2026-07-19: ship only
`water_shortage_cleared`** — derived cleared events for the other three
were implemented then removed same-session as guesswork; don't re-add
them without a real resolution signal (a test pins the sole-type rule).

**Why:** these are decompile-established facts that future protocol work
will re-ask; the _ensure_pro_mode doubt in particular must not be lost or
someone will re-justify the switch from the stale docstring.

**How to apply:** before touching mode-switching, scale-page, or
live-adjust code, re-read this. jadx tree lives in the 04d79599 scratchpad
(re-decompile from `xbloom_coffee_release.apk` in repo root if gone).
