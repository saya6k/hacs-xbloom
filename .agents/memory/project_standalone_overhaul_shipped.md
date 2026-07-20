---
name: xbloom-standalone-overhaul-shipped
description: Standalone-mode overhaul (SPEC.md T1-T17) fully implemented on main 2026-07-20; breaking state/button/slider/LLM changes listed; rc publish + 4 soak-verification items pending.
metadata: 
  node_type: memory
  type: project
  originSessionId: 9518af78-3112-4f15-b9d7-be223b4d0d1d
  modified: 2026-07-20T02:14:47.961Z
---

The standalone-mode overhaul (root `SPEC.md`, plan in `tasks/plan.md`, both
gitignored/local) shipped completely on `main` on 2026-07-20 — evidence tasks
(jadx + live capture), telemetry-driven states, transitions, live sync,
entity rework, LLM two-phase, alarm channel, maintenance states, docs.
Commits `dab95de` → `b4ac999`+; 449 tests passing. T3–T7 and the fixes were
hardware-verified live the same day ([[xbloom-checkpoint2-hardware-findings]]).

**Breaking changes shipped together** (release-note draft sits in
`tasks/todo.md`): `armed_grind`/`armed_pour` → `standalone_*` (+
`standalone_scale`, `descaling`, `calibrating_scale`; `calibrating` →
`calibrating_grinder`); enter/exit scale buttons → one `button.scale_mode`
toggle; `number.temperature` 40–100 → 39–96 with RT/BP endpoint wire mapping
(20/98); LLM `grind_xbloom`/`pour_xbloom` two-phase + new `cancel_xbloom`.

**Pending before stable promotion** (Checkpoint 4, needs the rc soak /
hardware): (1) armed-recipe machine-confirm transition never hardware-run;
(2) the 0xFFFE/0xCD alarm parser is decompile-derived, no real alarm frame
observed yet — verify offsets when one fires; (3) codes emitted DURING an
actual descale / scale-calibration run are uncaptured (confirm screens 0x2F/
0x32, 0x39/0x3A are mapped; a run may emit different codes that would fall
back to idle); (4) LLM two-phase flow not yet exercised in a live Assist
session.

**Why:** the next session will otherwise re-derive what shipped vs. what the
rc soak still owes.

**How to apply:** when publishing the rc, paste the draft from
`tasks/todo.md`; when any soak item is verified, update this entry. Related
memory: [[xbloom-machine-alarm-channel-and-rtbp]],
[[xbloom-t2-screen-code-capture]], [[xbloom-checkpoint2-hardware-findings]].
