---
name: xbloom-dismiss-pod-prompt-8017
description: "cmd 8017 (quitRecipeStart) dismisses the machine's own local \"insert pod\" prompt shown on NFC pod detection, independent of whether HA has armed a brew; folded into the existing cancel button rather than shipped as a separate one."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

`8017` (`APP_RECIPE_START_QUIT`/`quitRecipeStart`) was initially dismissed
during a completeness sweep as having "no applicable scenario" because this
integration's own brew flow sends `8001/8004 → 8002` back-to-back with no
confirmation gap. That reasoning didn't apply: `jadx` call-site tracing
showed `quitRecipeStart()` is sent from `PodsDetailActivity`/
`RecipeDetailActivity`'s `showStartDialog()` dismiss handler, **before any
BLE brew command is sent** — the machine shows its own local "ready to brew
this pod" prompt the instant it reads an NFC tag (the same `RD_Pods`/40501
event exposed as `pod_detected`), independent of whether the
app/HA has armed anything.

Implemented 2026-07-17 as its own `button.dismiss_pod` first, then removed
the same day in favor of folding the same call directly into
`coordinator.async_cancel()` — logically the same "cancel" action from the
user's perspective, just targeting a different machine state.
`_dispatch_event` tracks `self._pod_prompt_active` (set on `pod_detected`,
cleared once a real brew actually starts — `grinding_started`/
`brewing_started`, since the app's own arm+execute flow never sends 8017
either); `async_cancel()` sends bare 8017 when that flag is set, the
original stop/quit/back-to-home sequence otherwise.

**Why**: this is the precedent for "extend an existing button with a new
state branch" over "add a new button for a related-but-distinct action" —
reused directly for the manual-grind/pour targeting decision, see
[[xbloom-manual-operation-command-targeting]].

**How to apply**: if a future pod-detection-adjacent feature comes up,
check `_pod_prompt_active`'s existing clear conditions before adding new
ones — it's meant to track exactly the window between NFC detection and
either a dismiss or a real brew start.
