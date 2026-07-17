---
name: xbloom-manual-operation-command-targeting
description: "The pause/cancel buttons sent whole-recipe commands (40518/40524/40519) regardless of what was actually running; fixed by tracking _active_operation (recipe/manual_grind/manual_pour) so manual grind/pour pause/resume/cancel target the grinder/brewer-specific command family (8018-8021, 3505, 4507) instead."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

The recipe pause/resume button sent the wrong command family entirely for
a manual grind/pour — `APP_GRINDER_PAUSE`/`APP_BREWER_PAUSE` (8018/8019)
were what the vendored PyBloom naming suggested (`grinder.pause()`/
`brewer.pause()`), which made this look correct for years, but tracing
every real call site of those commands showed they're only used from
`GrinderActivity`/`BrewerActivity` — **standalone manual single-motor
screens**, reached only from the home screen's own "Grind"/"Brew"
quick-action icons, which first send a distinct "enter mode" handshake
(`APP_GRINDER_IN`/`RD_BREWER_IN`, 8006/8007) before the pause-capable
screen even opens. This is a different machine mode from the onboard
Auto-recipe state this integration's own `8001`/`8004`+`8002`-driven brews
put the machine into — which is exactly what `AppJ15AutoManager.pause()`/
`restart()` (40518/40524, "full-flow brew pause") target, and the *only*
pause mechanism the app's own in-recipe pause button ever calls. Fixed:
`coordinator.async_pause_resume()` sends 40518/40524 for recipe brews,
matching the app's own `CodeModule` calls exactly.

**Manual grind/pour pause/resume/cancel** (8018/8019/8020/8021 pause/
restart, 3505/4507 stop) were wired up the same session by adding
`coordinator._active_operation` (`"recipe"`/`"manual_grind"`/
`"manual_pour"`/`None`, set in `async_grind()`/`async_pour()`/
`async_execute_recipe()`, cleared in `_dispatch_event()` on the matching
completion event — `grinding_complete` only clears it for
`"manual_grind"`, since a coffee recipe's own grind phase fires the same
event mid-recipe). `async_pause_resume()`/`async_cancel()` branch on it to
target the right command family instead of always assuming a recipe.
`button.grind`/`button.pour` already worked correctly before this — the
vendored `GrinderController.start()` already sends `APP_GRINDER_IN` (8006)
internally. `coordinator.async_pour()` now also sends `8007`
(`RD_BREWER_IN`) before `client.brewer.start(...)`, for app parity — not
functionally required, 4506 alone was already hardware-confirmed
sufficient. Deliberately **not** new entities — extends the existing single
pause/cancel buttons (user's explicit choice), same pattern
[[xbloom-dismiss-pod-prompt-8017]] established the same day for
`_pod_prompt_active`.

**Not hardware-verified** — needs a real manual grind/pour, pause mid-
operation (expect 8018/8019, not 40518), resume (8020/8021), and cancel
(3505/4507, not the recipe stop sequence).

**Why**: two structurally different machine modes (standalone manual
screens vs. onboard Auto-recipe flow) share overlapping vendored method
names, which is what made the wrong-family bug easy to introduce and hard
to notice without decompiling actual call sites.

**How to apply**: any new pause/cancel-shaped action must branch on
`_active_operation` rather than assuming one command family — see
`coordinator.py`'s `async_pause_resume`/`async_cancel` for the pattern.
