---
name: xbloom-two-stage-arm-confirm-buttons
description: "The grind/pour/execute-recipe HA button entities are two-stage (2026-07-18): a first press queues the operation on the machine (enter mode / queue recipe) without starting it, a second press on the SAME button sends the actual go command — gives the user time to place a cup etc. HA-button-only; the execute_recipe/execute_tea_recipe services, async_grind()/async_pour(), and every LLM tool still act in one call, unchanged."
metadata:
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

User-requested feature (2026-07-18), not a bug fix. The protocol already
splits "queue" from "go" at the command level for all three operations,
which is what made this a natural fit rather than an artificial addition:

- **Grind**: `GRINDER_IN` (size/speed, burr adjust) = arm; bare
  `GRINDER_START` = go. `GrinderController.enter_mode()`/`.confirm_start()`
  (`ble/components.py`) — `confirm_start()` is new, `.start()` (the
  single-shot form `async_grind()` still uses) already called
  `enter_mode()` internally.
- **Pour**: `RD_BREWER_IN` (8007, "enter pour page") = arm; `BREWER_START`
  (4506, full payload) = go. `BrewerController.enter_mode()` is new — this
  is the exact 8007 send [[xbloom-manual-operation-command-targeting]]
  removed from `async_pour()` for racing 4506 with no delay. Reintroducing
  it here is safe: the real gap until the user's second press replaces the
  missing delay that caused that regression.
- **Recipe execution**: `8022→8102→8104→8001/8004` (coffee) or
  `8022→8102→8104→4513` (tea) = arm; bare `8002` (coffee) or a **re-send of
  the identical 4513 payload as 4512** (tea — the firmware's own expected
  sequence, not a bare command) = go. `brewing.py`'s `_async_brew_coffee`/
  `_async_brew_tea` were split into `_async_arm_coffee`/`_async_arm_tea`
  (return the tea payload) plus the existing/new confirm step;
  `async_arm_recipe()`/`async_confirm_recipe()` are the new public
  entry points, `async_execute_recipe()` (unchanged single-shot behavior)
  now composes `_async_arm_*` + confirm internally.

**Coordinator state** (`__init__.py`): `_armed_operation` (`None` /
`"grind"` / `"pour"` / `"recipe"`), plus `_armed_recipe_is_tea` /
`_armed_recipe_tea_payload` (only meaningful for `"recipe"` — the tea
payload has to be stashed since 4512 needs the exact same bytes as 4513,
not a bare command). **No timeout** (user's explicit choice) — stays
armed until confirmed or `async_cancel()`, which now branches on
`_armed_operation` first (before the heavier stop sequence) and just
sends `8022` (Back to Home) to back out, since nothing has actually
started yet. `async_pause_resume()` is a no-op while armed for the same
reason.

**New coordinator methods** (`coordinator/operations.py`,
`coordinator/recipes.py`): `async_arm_grind`/`async_confirm_grind`,
`async_arm_pour`/`async_confirm_pour`, `async_arm_recipe`/
`async_confirm_recipe`. `async_grind()`/`async_pour()`/
`async_execute_recipe()` themselves are untouched — button.py's
`async_press()` now checks `coordinator._armed_operation` and calls arm
vs. confirm; every other caller (services, LLM tools) still calls the
original single-shot methods directly.

`async_arm_recipe()`'s pre-brew logic (water check, firmware gate, recipe
build with overrides, bypass resolution) is shared with
`async_execute_recipe()` via a new private `_prepare_recipe_execution()` —
a pure refactor, not a behavior change for the single-shot callers.
`_async_retry_while_sleeping()` (`connection.py`) was widened to return
its wrapped action's result (backward compatible — every pre-existing
caller ignored the return value) so `async_arm_recipe()` can get the tea
payload back through the sleep-retry wrapper.

**`sensor.state` gained three new values**: `armed_grind`/`armed_pour`/
`armed_recipe`, highest priority in the state-derivation chain (above
even `calibrating` — pure HA-side bookkeeping, not inferred from
telemetry at all). Added to `sensor.py`'s `_attr_options` **and** all
three translation files together, per the established
"forgetting one crashes `async_write_ha_state()`" lesson
[[xbloom-grinder-calibration-completion-signal-saga]] —
`tests/test_sensor_state_enum_registration.py` already pins this
invariant generically, no new test needed for that part specifically.

**Untested edge case**: pressing a *different* button while one operation
is already armed (e.g. `button.pour` while grind is armed) just arms the
new operation without first backing out of the old one — not specially
handled, no hardware available to confirm what the firmware actually does
in that case.

**Why**: the two-stage split maps directly onto commands the protocol
already treats as separate steps — worth checking for this same "queue
vs. go" shape before assuming a new manual action needs an artificial
confirmation step bolted on.

**How to apply**: any new manual single-shot action should keep its
existing single-call method untouched for services/LLM tools, and add
sibling arm/confirm methods only if the underlying protocol has a real
queue/go split to exploit — don't invent an artificial one.
