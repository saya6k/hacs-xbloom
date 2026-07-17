---
name: xbloom-40518-and-8104-third-party-claims-refuted
description: "cmd 40518 is BREW_PAUSE (not a \"start\" command a third-party capture claimed) and cmd 8104 is genuinely cup-weight bounds (not \"preheat stage temps\" another third-party capture claimed) - both settled by decompiling the official app's own bytecode."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Two protocol ambiguities where a third-party reverse-engineering repo made
a claim that conflicted with this integration's own interpretation — both
settled definitively by decompiling the **official Android app's own
compiled bytecode** (`xbloom_coffee_release.apk`, via `androguard`), which
outranks any third-party capture as evidence.

**cmd 40518**: hardware behavior alone (sending it mid-brew resets to
`armed`) was ambiguous — a third-party repo (Janczykkkko/xbloom-ble) claimed
it was the post-commit "go" command. Settled 2026-07-16: a class
`com/chisalsoft/andite/manager/AppJ15AutoManager` has a method literally
named `pause()` that sends `const/16 v3, 40518`; sibling `restart()`/
`stop()` send `40524`/`40519`. This confirms brAzzi64/xbloom-ble's
`CMD_BREW_PAUSE` naming and directly refutes the "start" claim.

**cmd 8104**: this integration's own code sends two floats as `(max, min)`
cup-weight bounds; a different third-party capture (Janczykkkko/xbloom-ble)
had claimed the identical payload shape was actually two preheat "stage
temps." On-device telemetry couldn't settle it either way. Settled
2026-07-16: `com/xbloom/util/BleCodeFactory$Companion.setCup()` and three
call sites all send `const/16 v_, 8104` from a method literally named
"setCup", and the app's own `theMax`/`theMin` field names (matching
`denull0/xbloom-agent`'s cloud-API `create_recipe()` naming) confirm the
cup-weight-bounds interpretation.

**Why**: both cases show the same lesson — a third-party capture repo is a
useful lead but not authoritative when it conflicts with the official app's
own bytecode; the app's source always wins.

**How to apply**: if a third-party reverse-engineering source disagrees
with this integration's protocol interpretation, decompile
`xbloom_coffee_release.apk` directly rather than trusting either capture on
priors — see [[xbloom-full-command-table-androguard-sweep]] for the broader
methodology this established.
