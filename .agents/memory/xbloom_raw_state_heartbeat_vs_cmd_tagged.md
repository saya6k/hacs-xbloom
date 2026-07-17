---
name: xbloom-raw-state-heartbeat-vs-cmd-tagged
description: "The cmd-tagged RD_GRINDER_BEGIN/RD_BREWER_BEGIN/etc. are unreliable for starting/brewing/ready transitions; a separate raw status-heartbeat frame is the only trustworthy signal; connected-but-never-brewed machines used to report state \"unknown\" forever instead of \"idle\"."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Hardware-confirmed 2026-07-16 during a real ~11s grind: `RD_GRINDER_BEGIN`
never fired at all, `RD_BREWER_BEGIN` fired immediately after commit (long
before pouring actually starts), and `RD_Grinder_Stop` flips the vendored
`DeviceState` to `IDLE` the instant grinding *ends* — moments before real
pouring begins. Net effect without a fix: "brewing" shown too early, a false
"idle" blip right before the pour, and nothing distinguishing "done, cup
still on scale" from true idle.

The fix uses a **separate raw frame**, distinct from the cmd-tagged `RD_*`
notifications and never reaching `XBloomResponse` at all: header(0x58|0x02)
| dev_id | `0x57` | ... | `0xc1` marker | state_byte | .... `_client.py`'s
`_scan_for_status_frame`/`_RAW_STATE_LABEL_MAP` reads this directly for
`0x22`(starting)/`0x10`,`0x23`,`0x3B`(brewing)/`0x24`(ready), overriding the
vendored value only for those codes.
`coordinator._async_update_data`'s state priority is `no_beans →
water_shortage → raw_label → vendored s.state.value`.

**Separately**, `sensor.state` could get permanently stuck at `unknown` on a
connected machine that simply hadn't brewed yet this session (fixed
2026-07-17). Root cause: the vendored `DeviceState` enum defaults to
`UNKNOWN` and is only ever transitioned to `IDLE` by a
`RD_Grinder_Stop`/`RD_Brewer_Stop` event — i.e. only *after* at least one
grind/brew cycle. The raw-label map above has no idle code either. Fixed:
`coordinator._async_update_data` now maps `s.state.value == "unknown"` to
`"idle"` when connected with no error/no_beans/water_shortage/raw_label
match — connected + no activity ever observed is, definitionally, idle.

**Why**: this is the single biggest gap between "what the firmware's
cmd-tagged events say" and "what's actually happening" in the whole
protocol — critical for any UI/automation that reacts to brew state.

**How to apply**: if `sensor.state` looks wrong specifically during/right
after a real grind (stuck on a stale value, or briefly flips to `idle`
mid-brew), check `_RAW_STATE_LABEL_MAP` before assuming a new bug. If it's
stuck `unknown` on an otherwise-healthy connection, check whether the
machine has ever completed a grind/brew this session.
