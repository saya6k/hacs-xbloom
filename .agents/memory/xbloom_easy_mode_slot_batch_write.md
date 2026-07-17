---
name: xbloom-easy-mode-slot-batch-write
description: "Easy Mode slot writes (cmd 11510) are type-2 packets that must be sent as a full A/B/C batch with no commit frame, from PRO mode; a bookkeeping bug once mirrored the BLE-level batch requirement into HA's own record of which slots the user actually assigned."
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
