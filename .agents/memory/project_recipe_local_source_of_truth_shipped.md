---
name: project-recipe-local-source-of-truth-shipped
description: The recipe local-source-of-truth rework is complete and verified against real XBloom hardware (2026-07-04); planning docs archived.
metadata: 
  node_type: memory
  type: project
  originSessionId: a3ebf6da-07d3-47a6-8749-c89384cf7ac6
---

The "레시피 로컬 Source of Truth 개편" project (recipes: local store instead of always-on cloud sync) is **done and verified on real hardware**, not just code-complete. All checkpoints A–D from the todo were either verified live or explicitly deferred by the user as unnecessary:

- Checkpoint A (fresh-install seed / v2→v3 migration / restart stability) — deferred; the user's install has been running migrated for weeks, which stands in for it.
- Checkpoint B (all 9 recipe services) — verified live: list/create/edit/delete_recipe, cloud_export_recipe (including a bypass-enabled recipe), cloud_search_collective_recipes, write_recipe_to_easy_slot, execute_recipe with dose override. cloud_import_recipe and the export-without-login branch were skipped as optional.
- Checkpoint C (Easy Slot) — verified live via both the physical-button path and the `write_recipe_to_easy_slot` service; confirmed `SEND CMD 11510` and restart persistence.
- Checkpoint D (Assist/LLM round trip) — verified live; this also surfaced and fixed a real safety-confirmation bypass in `execute_xbloom_recipe` (see below).

**Old planning docs are archived, not deleted**, following this repo's own convention: `tasks/archive/2026-07-recipe-local-source-of-truth-{spec,plan,todo,release-notes}.md`. `SPEC.md`, `tasks/plan.md`, `tasks/todo.md`, `tasks/release-notes.md` at their live paths are gone — they're reset for whatever the next project is. `AGENTS.md` was updated to point at the archived paths instead of the now-gone live ones.

**Why this matters for future work:** if asked "what's the current project" or "what's in SPEC.md", the live files are empty/gone by design — check `tasks/archive/2026-07-recipe-local-source-of-truth-*.md` for this project's history instead, or ask the user what the next project is.

Bugs found and fixed *during* this real-hardware verification pass (all shipped, not still-open):
1. BLE connection layer bypassed HA's Bluetooth integration entirely (bare `BleakClient`, no `bleak-retry-connector`) — replaced with `_client.HABleakConnection`.
2. No auto-reconnect existed after an unexpected BLE drop — added via `disconnected_callback` → `coordinator._handle_unexpected_disconnect`.
3. A false-positive header byte in the vendored notification-framing loop could produce garbage packet lengths ("Partial packet received: ...3254779905 bytes") and silently drop real packets — fixed with a bounded-length check in `_client.py`.
4. **The real root cause of "mode switch drops the connection"**: `async_set_mode()` persisting the mode via `entry.options` triggered a full config-entry reload (`CONF_MODE` wasn't in the reload-exemption set), and nothing ever reconnected after that reload. Fixed by adding `CONF_MODE` to the reload-exemption set alongside the recipe-store keys.
5. `cloud_export_recipe` hard-rejected any bypass-enabled recipe because the pour-volume-consistency formula (`pours + bypass == dose*ratio`) was only ever confirmed for bypass-off recipes; live data showed bypass sitting on top of the budget, not inside it. Fixed by skipping the hard check when `bypass_volume > 0` (the existing `warning` field already covered that case).
6. `execute_xbloom_recipe`'s beans/filter confirmation gate could be bypassed by calling `pour_xbloom` directly for water-only recipes, since pour_xbloom has no such gate — an Assist test literally triggered an unintended real pour this way. Fixed at the tool-logic level: added `dripper_confirmed`, and recipes with no dose/grind (e.g. water-only) skip the whole beans/dripper/filter confirmation since there's nothing to confirm.

See [[feedback_release_cycle]] for how these were shipped (branch → PR → merge → rc prerelease, tested live each time).
