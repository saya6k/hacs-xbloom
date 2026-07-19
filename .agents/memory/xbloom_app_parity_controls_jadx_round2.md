---
name: xbloom-app-parity-controls-jadx-round2
description: "2026-07-19 jadx round 2: 8023 = RD_MachineActivity (identity solved), 8003/8014 scale page enter/exit, 4510/8016 live-adjust call sites confirmed, 8006 doubles as grind-page adjuster, 8001/8004 chosen by isSetGrinderSize, and the app has NO Easy/Pro gate on recipe execution — casting doubt on our _ensure_pro_mode rationale."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9df22f00-e12a-4774-8845-697ce76887a4
  modified: 2026-07-19T11:31:40.038Z
---

Second jadx sweep of `xbloom_coffee_release.apk` (2026-07-19), answering the
open questions from the stall probe. Docs: PR #126 (protocol.md en/ko).
Implementation: PR #127 (armed live-adjust, scale buttons, error-cleared
events) — **not yet hardware-verified**.

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

**The app has NO mode gate on recipe execution**: the full chain is
`8102` (bypass) → `8104` (cup) → `8001`/`8004` → \[user taps confirm\] →
`8002`, sent identically whether the machine is in Easy or PRO mode.
**This casts doubt on `connection._ensure_pro_mode`'s rationale** ("Easy
Mode silently ignores the Pro brew commands — hot water only"): that
symptom is byte-identical to the ratio-footer grind-gate bug
([[xbloom-ratio-footer-grind-gate]]) found later, so the original
observation may have been a misattribution. Hardware test to settle it:
machine in Easy mode, send a recipe with a correct ratio footer, watch
whether it grinds. If it does, the auto Pro-switch (and the post-brew
Easy restore) can go. Don't remove it before that test.

**Error resolution signals** (basis for PR #127's `*_cleared` events):
only 40522 is bidirectional (value 1 = refilled). 8203/8204
(AbnormalGearPosition/AbnormalDoseOrWater) and 40517 (ErrorIdling =
no-beans, "空磨提醒") are payload-less one-shot toasts in the app with no
wire-level clear — so recovery is only honestly detectable via
demonstrated success (brewing_started / pour_complete / recipe_complete).

**Why:** these are decompile-established facts that future protocol work
will re-ask; the _ensure_pro_mode doubt in particular must not be lost or
someone will re-justify the switch from the stale docstring.

**How to apply:** before touching mode-switching, scale-page, or
live-adjust code, re-read this; treat PR #127's sends as unverified until
a real-hardware pass. jadx tree lives in the 04d79599 scratchpad
(re-decompile from `xbloom_coffee_release.apk` in repo root if gone).
