---
name: xbloom-easy-mode-slot-batch-write
description: "Easy Mode slot writes (cmd 11510) are type-2 packets that must be sent as a full A/B/C batch with no commit frame, from PRO mode; a bookkeeping bug once mirrored the BLE-level batch requirement into HA's own record of which slots the user actually assigned. (2026-07-18) Easy Mode slots have no dedicated tea payload format at all — writing a tea recipe to a slot is now refused outright."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Easy Mode slot writes (cmd `11510`) are type-2 packets — packet offset 2 is
`0x02`, not the usual `0x01`. Payload prefix is `[slot_index][flags]`
followed by the same recipe blob `build_recipe_payload` produces for
8001/8004 brews.

**Hardware-confirmed 2026-07-15**: writing a single slot hangs the machine
at status `0x43` ("saving", RETRY) — completing all three back-to-back
unsticks it (`0x43`→`0xf8`→`0x25`→idle). Writing from Easy/Auto mode is also
refused (stays at `0x41`/RETRY) — the machine must be switched to PRO
first. `coordinator.async_write_easy_slot()` handles both: resolves the
other two slots' current contents before writing, force-switches to PRO if
needed (restoring the prior mode after), and `brewing.async_write_easy_slots
()` always sends all three frames in one call — there is no single-slot
write path.

**The BLE-level "write all three" requirement must not leak into HA's own
bookkeeping.** Hardware-confirmed 2026-07-17: writing only slot A while B/C
had never been configured made the `easy_slot_a`/`b`/`c` sensors *all* show
as registered — `async_write_easy_slot()` mirrors the target recipe into the
BLE payload for any never-written slot (unavoidable, no readback exists to
preserve instead), but was also persisting that synthetic mirror into
`entry.options["easy_slots"]` for all three letters. Fixed to persist only
the target letter; the fallback recipe still goes out over BLE for the
other two, it just isn't reported back to the user as a real assignment.

**`RD_EASYMODE_RECIPE_ORDER` (cmd 11512)** is a real official-app behavior,
not a third-party embellishment — confirmed via decompile of
`com/xbloom/util/BleCodeFactory$Companion.easyModeRecipesOrder(String)`,
called after writing all three slots. `brewing.async_write_easy_slots()`
sends it too (payload `[3, 0, 1, 2]`, matching an independent third-party
capture's observed default) — untested on real hardware.

**Why**: the batch/PRO-mode/order-frame requirements are all non-obvious
from the protocol alone and easy to regress if someone "simplifies" to a
single-slot write path.

**How to apply**: never add a single-slot Easy Mode write path. Any change
to slot persistence must keep the BLE-payload-vs-HA-bookkeeping distinction
this fix established — what goes out over BLE for unwritten slots is not
necessarily what gets reported to the user.

**2026-07-18: Easy Mode slots have no dedicated tea format — writing a tea
recipe to a slot is now refused, hardware-reported as "saved a chamomile
recipe to a slot, pressing the physical slot button ground beans."**
`brewing.async_write_easy_slots()` always builds the slot payload with
`_build_coffee_recipe_payload` — the exact same coffee-shaped recipe blob
`build_recipe_payload` produces for 8001/8004 — and its `grinder_on` flag
comes straight from `recipe.grind_size`/`recipe.bean_weight`, with zero
`cup_type` awareness (AGENTS.md's tea firmware-quirks entry already
established 8004 itself never enters tea mode — 11510 has no evidence of
being any different). Compounding this: `RECIPE_SCHEMA` defaults `grind_size` to 50
and `dose_g` to 15.0 (coffee-oriented) — nothing enforces the documented
convention that a `cup_type: tea` recipe should zero them out, so a
casually-authored tea recipe that only set `name`/`cup_type: tea`/`pours`
keeps those coffee defaults, and the slot write faithfully encodes them as
a real grind. `coordinator.async_write_easy_slot()` now checks
`raw.get("cup_type")` and refuses with `error: tea_not_supported_in_easy_slot`
before any BLE traffic (mode switch included) whenever it's `"tea"` —
regardless of grind_size/dose_g, since even a correctly-zeroed tea recipe
still can't brew as real tea from a slot (no siphon/soak, only 4513/4512
does that) — this isn't a payload-sanitization fix, slots categorically
can't do tea. Surfaces through both the `write_recipe_to_easy_slot`
service (raises `HomeAssistantError` with the message) and the
`write_xbloom_easy_slot` LLM tool (message flows through automatically via
its existing generic failure path) — **not** through the HA
`button.write_slot_a/b/c` entities, which discard `async_write_easy_slot`'s
return value entirely and always fail silently (log-only), a pre-existing
gap for every error this method can return, not something this fix
introduced or addressed. Tests: `tests/test_easy_slot_tea_rejected.py`.

**Why**: 11510's payload format was reverse-engineered entirely from
coffee-recipe captures — there was never any positive evidence it supports
tea, only an absence of anyone checking cup_type before this report.

**How to apply**: if a genuine tea-capable Easy Mode payload format is ever
found (a real HCI capture of the official app writing a tea recipe to a
slot, not just an absence-of-evidence assumption), this refusal should be
replaced with the real tea-aware payload — not simply removed.
