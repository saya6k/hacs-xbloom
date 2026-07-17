---
name: xbloom-full-command-table-androguard-sweep
description: "A full sweep of every known command id against the official app's decompiled bytecode (androguard) confirmed nearly the entire table and settled the pattern/vibration cloud-mapping dispute; established the methodology of checking androguard for IDs and jadx for payload semantics."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

2026-07-16: downloaded `xbloom_coffee_release.apk` (multidex, 5
`classes*.dex`) and parsed it with `androguard` (proper DEX bytecode
access — field/enum values and method-body constants, not just
string-grepping the way an earlier switcher-app analysis had to). A
scripted sweep for every known command id as a `const`/`const-16` literal,
across all 5 dex files, hit almost every one of them in a class/method
whose name matches its documented purpose:
`com/xbloom/util/BleCodeFactory$Companion` (`backToHome`→8022,
`setCup`→8104, `teaRecipeCode`→4513, `makeTea`→4512, `quitRecipeStart`→8017,
`easyModeRecipe`→11510, `easyModeSwitch`→11511,
`easyModeRecipesOrder`→11512), `com/chisalsoft/andite/manager/
AppJ15AutoManager` (`pause`→40518, `restart`→40524, `stop`→40519),
`AppBleManager.mtuSuccess`→8100, `FwUpgradeActivity`→8101,
`RecipeDetailActivity`/`PodsDetailActivity` (`sendBypassJ15`→8102,
`sendCodeJ15`→8001/8004, `sendCupJ15`→8104, `startJ15`→8002), and
`com/chisalsoft/andite/model/ble/BaseBleModel$Companion.create` — a single
dispatcher containing essentially the entire inbound `RD_*` table in one
place.

**Also resolved**: the cloud pattern-mapping question. `j15code.
S_PourPattern`'s `<clinit>` assigns `center=1, spiral=2, circular=3` —
matching this integration's own live-account-verified
`_LOCAL_PATTERN_TO_CLOUD` exactly and **refuting**
`cryptofishbug/xbloom-recipe-cli`'s README table (which had spiral/circular
swapped). `j15code.S_CupType` confirms `XPod=1, XDripper=2, Other=3`.

**The one real, actionable gap found**: `easyModeRecipesOrder` (cmd 11512)
turned out to be genuine official-app behavior, not a third-party
embellishment — see [[xbloom-easy-mode-slot-batch-write]] for the fix that
followed.

**Why**: this sweep is the reason most of the command table in
`docs/en/protocol.md` can be marked "Active" with confidence rather than
"present, unconfirmed" — it's the closest thing this integration has to a
full protocol audit.

**How to apply**: `androguard`'s bytecode access finds command-*id* literals
reliably but not payload *encoding* — for that, decompile with `jadx`
instead (near-source Kotlin/Java) — see
[[xbloom-advanced-features-jadx-pour-vibration-brightness-calibration]] for
where this distinction mattered. Use this sweep's class names as starting
points for any future protocol question rather than re-deriving from
scratch.
