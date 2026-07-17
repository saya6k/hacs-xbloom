---
name: xbloom-temperature-name-constants
description: "temperature_c accepts \"RT\"/\"BP\" name strings alongside a plain int (RT=20, BP=98 on J15/Studio) - decompiled from TemperatureConstant.java, resolving a prior open question about whether BP was a fixed sentinel or a computed near-boiling value."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

`schema.py`'s `_coerce_temperature_c` (added 2026-07-17) accepts `"RT"`
(Room Temperature) and `"BP"` (Boiling Point) as recipe pour temperature
names alongside a plain positive int, decompiled from
`TemperatureConstant.java`/`RecipePourViewHolder`: the official app's own
pour-temperature slider snaps to fixed literal values at its min/max —
**not** protocol-level sentinels. RT = `20`, BP = `98` (on J15/Studio). A
recipe already using `temperature_c: 98` behaves identically; this only
adds the app's own names as a convenience, matching the existing
`_coerce_pour_pattern` string-or-int pattern.

This resolves an old open question in `docs/en/brewing-notes.md` — a prior
observation of a captured byte value of `99` for a "BP" pour looked like it
might be a computed near-boiling value rather than a fixed sentinel. It's a
fixed constant after all; the `99` vs. `98` discrepancy is a ~1° rounding/
encoding artifact, not evidence of dynamic computation.

**Why**: this closes a specific documented uncertainty rather than
introducing a new one — worth remembering the byte-level discrepancy is
expected, not a bug, if it ever resurfaces in a capture.

**How to apply**: if a future capture shows a pour temperature byte that's
off by ~1° from an expected round value, check whether it's an RT/BP-style
fixed constant with known rounding before assuming a new encoding bug.
