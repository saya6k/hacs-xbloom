---
name: xbloom-machine-alarm-channel-and-rtbp
description: "T1 jadx sweep 2026-07-20: machine alarms = cmd 0xFFFE marker 0xCD with LE u32 code lists per category (power/brewer/dock/grinder/scale/upgrade-fail); RT/BP slider 39-96°C sends 20.0/98.0; descale & scale-cal have NO BLE commands; 50038/50039 = gear-zeroing notifications."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9518af78-3112-4f15-b9d7-be223b4d0d1d
  modified: 2026-07-19T16:31:35.576Z
---

jadx 1.5.6 sweep of `xbloom_coffee_release.apk` (2026-07-20, standalone-mode
overhaul T1 — full detail in the session scratchpad `t1-jadx-findings.md` and
the drafted `docs/*/protocol.md` rows; SPEC.md / tasks/plan.md are the work
context).

**Machine alarm channel**: `VerifyCodeUtils.getData()` routes cmd `0xFFFE`
(65534) + marker byte `0xCD` → `ErrorBle1Model`; payload first 4 bytes LE =
alarm code. Same-id `0xC1` frames (ErrorBle2) and all of `0xFFFD` (ErrorBle3)
have EMPTY `excute()` — the app deliberately ignores them; don't map them.
Code lists → app dialog category: power 8449/8450/4355–4362 ("Mismatched
power"); brewer 513/4610/5633/5637/6148/6401–6405/9730/9732/10241–10243/10245/
13827/14342/14598–14603 ("Brewing error"); dock 8961–8963/4868/4869/4871/
4873–4875/13062/13064; grinder 1025/5123/5124/5379/9218/9473/9474/9477/9478/
13317/13572; scale 1793/1795/1796/5890 ("Scale overload"); upgrade-fail
7169/7170 (→ `FwUpgradeFailEvent`; AppBleManager special-cases "011C"/"021C"
frames during OTA). Silent lists: 2562/2563/2820/2821/6657/6913–6915; 9479 is
silent AND skipped from the app's cloud error log. The umeng `q.a.n..q`
constants in the power list = 4355–4358. "Grinder Overload" / "Water Intake
Alert" / "Overflow Trigger" from the troubleshooting tables have **no distinct
wire id** — machine-display-only distinctions inside those categories.
Offset caveat: the app parses cmd at hex chars 6–10 (bytes 3–4) and marker at
byte 9 — one byte off from our outbound layout doc; verify against a captured
alarm frame before writing the parser.

**RT/BP manual-pour slider** (`CoffeeConstantUtil.getTemperatureJ15RTBP` +
`BrewerActivity`): range 39–96 °C step 1 (°F 103–204), default 85; min shows
"RT", max shows "BP". BOTH 4510 (`checkAndSetTemperature`) and 4506
(`startWater`) send `TemperatureConstant.RT` = 20.0 at ≤min and `BP` = 98.0 at
≥max, literal between — so [[xbloom-temperature-name-constants]]' RT=20/BP=98
DO apply to the manual path. 4506 truncates: float32 bits of `((int) f) * 10`.
App volume slider on the same page: 30–500 step 1, default 150.

**Descale & scale calibration have NO BLE commands**: `DescaleActivity` and
`CalibrateScaleJ15Activity` are static instruction slideshows; both procedures
run on the machine. HA-side visibility for `descaling`/`calibrating_scale`
states can only come from passive telemetry (T2 hardware capture).

**50038/50039** (`RD_CalibrateStart`/`RD_Calibrating`): both toast "The
machine gear is being reset to zero, please try again later"
(`Device_GrindSize_Reset_Zero`) and flush the app's command queue
(`clearAllCode()`) — grinder gear-zeroing notifications, candidate signals for
machine-entered grinder calibration; exact firing timing needs hardware.

**Why:** these settle SPEC.md open questions 2 and 5 and gate tasks T11
(slider), T14 (error events), T16 (maintenance states); re-deriving them means
another full decompile.

**How to apply:** T14 should ship one event type per app category with the raw
code as an attribute, mirroring the app's silent lists; T11 implements the
39–96 → 20/98 endpoint mapping; T16 must not expect any descale/scale-cal
wire signal beyond whatever T2 captures. See also
[[xbloom-app-parity-controls-jadx-round2]] and [[xbloom-full-command-table-androguard-sweep]].
