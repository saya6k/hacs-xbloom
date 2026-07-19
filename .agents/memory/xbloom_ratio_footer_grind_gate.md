---
name: xbloom-ratio-footer-grind-gate
description: "The 8001 recipe footer's ratio byte gates grinding: firmware reconstructs dose × ratio_byte/10 and silently downgrades the whole brew to no-grind (water only, no error, 8001 still ACKed) whenever that undershoots the pour sum — our int() truncation caused every locally-built inexact-ratio recipe to never grind; fixed with ceil + clamp-255."
metadata: 
  node_type: memory
  type: project
  originSessionId: efb12ddd-12cd-4a2f-8d7a-a3b406787f12
  modified: 2026-07-19T06:24:01.340Z
---

Root-caused 2026-07-19 after three full water-only brews (18g/250ml grind
recipe poured 250ml with no grind stage, no error, machine ACKing
everything). The debugging path matters as much as the answer:

**Wrong hypotheses, each killed by hardware test** (a settle-floor restore, a
no-8022 run, an 8104=(110,90) run — all still water-only):

1. Dropping the fixed inter-step delays for ACK gating (restoring changed
   nothing).
2. The 8022 back-to-home prelude (the official app's own 2026-05-29
   PacketLogger capture brews with **no** prelude at all — the coffee chain
   is just 8102 → 8104 → 8001 → 8002 — and the capture-vs-ours diff is also
   what proved every other byte matched).
3. The 8104 cup floats ((90,40) vs the (110,90) other projects use — both
   grind fine once the footer is right; not the gate).

**The actual gate**: the firmware reconstructs expected total water as
`dose × ratio_byte / 10`. If that lands **below** Σ(pour volumes), the brew
is silently downgraded to no-grind — 8001 ACKs, pours run, grinder never
starts, no error event, `RD_GRINDER_BEGIN` never fires. Undershoot is fatal;
overshoot is tolerated (139→250.2ml and 140→252ml both grind an actual-250ml
recipe; 138→248.4ml never does). `brewing._build_coffee_recipe_payload` used
`int(ratio*10)` (truncate) → any dose/volume pair whose ratio isn't a clean
0.1 multiple undershot. Fixed: `min(math.ceil(ratio*10), 0xFF)` — ceil bounds
overshoot at 0.1×dose ≤ 1.8ml, and the clamp fixes a second latent bug where
`& 0xFF` **wrapped** ratios >25.5 (10g/300ml → byte 44 → 44ml). Pinned by
`tests/test_coffee_ratio_footer.py`.

**Why the app never hits it**: the app UI enforces `dose × grandWater ==
Σ(pours)` exactly (Water_Powder_Error dialog otherwise), so app-made recipes
always have an exactly-representable ratio. This is also the proof that
`grandWater` = ratio, not total (RecipeDetailActivity:545 multiplies it by
dose to compare against the pour sum) — settling the footer-semantics dispute
(Alshekhi's "total×10" comment is a mislabel; their observed byte 0x9A fits
ratio 15.4).

**The cheap bisection technique** (reusable): execute the chain, watch ~6s
for the grind stage vs `bloom`, then cancel with bare `40519` — each variant
costs ~2s of grinding or a splash of water instead of a full brew. In the
grind flow `brewing_started` still fires early; **`bloom` is the
discriminator** (no-grind flow reaches it ~1s after execute; grind flow takes
20-30s and emits `grinding_complete`). Note `grinding_started`
(RD_GRINDER_BEGIN) did NOT fire during recipe grinds on D500 — only
`grinding_complete` did — so don't gate detection on it.

**Also learned from the app's builder** (GetRecipeCodeService /
GetRecipeCodeManager.sendData2Hex — `theCode` is built **client-side in the
APK**, not on the server, despite the http-looking naming): byte layout
matches ours field-for-field (substeps [vol,temp,pattern,vib] with 127ml
chunking, meta [-pause,0,rpm-first-pour-only,flow×10], length byte, footer
[grind, ratio×10]); temp passes transformTemp/F2C (values <100 unchanged).

**Reference repos** (user-supplied 2026-07-19, cloned to scratchpad/refs):
Alshekhi/xbloom-studio (HCI-confirmed 8104 cup table: Omni=(110,90),
Other/FreeSolo=(200,80)), HomoLand/xbloom-studio-brew (D500
hardware-validation notes, same pour-segment encoding),
Janczykkkko/xbloom-ble (grind 0xFE no-grind sentinel claim; pour-count ≥2
claim — the latter now disproven for grinding: our single-pour recipes grind
fine with a correct footer).

**How to apply**: any "machine ACKs everything but silently does less than
asked" symptom — check derived/encoded payload fields the firmware
cross-validates (ratio vs pour sum here) before suspecting sequences or
timing. And never truncate a wire byte the firmware reconstructs a physical
quantity from; round in the direction the firmware tolerates.
