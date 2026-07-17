---
name: xbloom-cloud-wire-api-quirks
description: "Four non-obvious XBloom cloud API (client-api.xbloom.com) wire requirements found only by live-testing against a real account - a missing theName field, a pour-volume-sum constraint that doesn't hold for bypass-on recipes, a server-assigned (not derivable) share_url, and asymmetric delete idempotency."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

`_cloud_client.py` talks to `client-api.xbloom.com`, reverse-engineered from
`denull0/xbloom-agent`'s `index.ts` and live-verified against a real
account (2026-07-03). Four requirements aren't obvious from the reference
source and were only found by live-testing — getting any wrong returns a
generic non-actionable error with no error code:

1. **Every pour object needs a `theName` field** — `"Bloom"` for the first
   pour, `"Pour {n+1}"` for the rest. Omitting it is silently rejected.
2. **`sum(pours[].volume_ml) + bypass_volume` must equal `dose_g * ratio`**
   for dosed (bypass-off) recipes — `validate_pour_volume_consistency()`
   checks this client-side, but only when `bypass_volume == 0`. **Bypass-ON
   recipes don't follow this formula**: live account data (2026-07-04)
   showed `pours` alone already summing to `dose_g * ratio`, with
   `bypass_volume` sitting on top as extra water — the opposite of what the
   bypass-off formula would require. The exact bypass-ON wire constraint
   (if any) is unconfirmed; `cloud_export_recipe` skips the hard check for
   nonzero `bypass_volume` and just attaches a warning.
3. **`share_url` is server-assigned, not derivable client-side** — the
   reference implementation's `btoa(String(tableId))` guess is wrong;
   decoding a real `shareRecipeLink` shows 16 bytes of opaque binary, not
   the table id's ASCII digits. `create_recipe()` does a follow-up
   `get_recipe(table_id)` call and reads the real value back.
4. **`delete_recipe` is idempotent only for a previously-valid id** —
   deleting an id that *was* a real recipe returns success again on a
   second call; an id that never existed returns failure. The two aren't
   the same "already gone" case.

**Pattern/vibration mapping** (`schema.py`) was deliberately not renumbered
to match cloud: local `pattern` ints `0/1/2` = `center/circular/spiral`;
cloud ints `1/2/3` = `centered/spiral/circular` — names *and* numbers
differ, mapped through `_LOCAL_PATTERN_TO_CLOUD`/`_CLOUD_PATTERN_TO_LOCAL`,
confirmed correct against
[[xbloom-full-command-table-androguard-sweep]]'s `S_PourPattern` finding.
Local `vibration` (single enum) maps to cloud's two independent booleans via
`_local_vibration_to_cloud`/`_cloud_vibration_to_local`.

**`adaptedModel: 1` (Studio) is hardcoded** in `list_recipes()` and
`create_recipe()` — copied from the reference implementation, never
parameterized, since this integration only supports Studio anyway. Account
recipe seed and `cloud_export_recipe` are unverified for whatever
`adaptedModel` value Original uses.

**Why**: this API returns no actionable error codes, so every one of these
four requirements was found the hard way (silent generic failure → bisect
the payload) — worth checking this list before assuming a new cloud-API
bug is something else.

**How to apply**: any new cloud-recipe field added to the wire payload must
be checked against all four requirements above before assuming "it should
just work" — the API will not tell you which one you got wrong.
