---
name: xbloom-collective-hub-and-backend-api
description: "Two additional undocumented XBloom cloud backends exist beyond client-api.xbloom.com - collective.xbloom.com (public recipe hub, different id space, found by reading its React bundle) and backend-api.xbloom.com (signed Retrofit API, found by decompiling the app, used to fetch the real per-device pour-radius center value, live-verified against a real account)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

**`collective.xbloom.com`/`collective-api.xbloom.com`** — a "Coffee Recipe
Hub" community site, found 2026-07-03 by reading its React bundle (not
documented anywhere, unrelated to `denull0/xbloom-agent`). Its
`collective.xbloom.com/recipe/{id}` uses a *different* identifier space
than `share-h5.xbloom.com` — `<id>` is the plain numeric
`communityRecipeId`, not the opaque share id; `RecipeDetail.html` rejects
it directly. `POST collective-api.xbloom.com/communityRecipe/recipe/detail
{"id", "type": 1}` (no auth) returns the same recipe's `shareRecipeLink`,
cross-confirmed against `RecipeDetail.html`. `_cloud_client.
fetch_shared_recipe()` resolves a collective link to its `shareRecipeLink`
via this API, then hands off to the normal path — the collective response
shape differs subtly (`cupType` is a string there, plus a separate
`cupTypeInt`), so it isn't reused directly. The same backend powers hub
search (`cloud_search_collective_recipes`): `POST
communityRecipe/index/page` takes id-list filters (origin/varietal/
process/roast/flavor/machine/cupType) whose values come from `POST
communityRecipe/recipe/criteria` (no auth, cached per client) — matched
first by raw code, then case-insensitive name, with unmatched entries
reported back rather than dropped, since the live criteria table is always
the source of truth, not a hardcoded snapshot.

**`backend-api.xbloom.com`** — a third, separate signed Retrofit/JSON API,
unrelated to both `client-api.xbloom.com` and `collective-api.xbloom.com`.
Found 2026-07-16 chasing where the official app gets pour-radius's
per-device factory-default center (`Device.pouringRadiusInit` — needed for
[[xbloom-advanced-features-jadx-findings]]'s pour-radius level math, since
it's account/serial-keyed and otherwise unreachable). Reverse-engineered
via `jadx`: `GET /app/device/getInitPouringRadius?serialNumber=...&
pouringRadius=...` returns `{code, message, request_id, data:
{initPouringRadius, pouringRadius}}` (`code == 0` = success — the one call
site that matters, `DevicePourRep.kt`, only accepts `0`, not the `200` some
other response-checking code in the same class also accepts). Every request
needs a signed header set, **no separate login** —
`LoginActivity.loginSuccess()` calls `ServiceConfig.saveToken
(response.getProjectToken())`, a *second* token field (`projectToken`) in
the exact same `tMemberLogin.thtml` response this integration's own
`login()` already parses, previously discarded. Signature:
`sign = uppercase(MD5("{appId},{appSecret},{nonce},{ts}"))`, `nonce` = a
random UUID (hyphens stripped, lowercased), `ts` = unix seconds, plus
`Authorization: token {projectToken}` and static headers. `appId`/
`appSecret` are baked into every build variant identically — they
authenticate "this is the app," not the user; `projectToken` is what scopes
access to the caller's own devices.

**`pour_radius_level` now requires a logged-in cloud account outright**
(rejected with `cloud_login_required` otherwise) — the current-value-as-
center approximation this originally shipped with was dropped once the real
cloud value was confirmed reachable, since that approximation is only valid
on a machine nobody has ever nudged the level on before, which can't be
verified either way.

**Live-verified 2026-07-16**: a standalone script
(`verify_pour_radius_center.py`, needs `XBLOOM_EMAIL`/`XBLOOM_PASSWORD`/
`XBLOOM_SERIAL` env vars, never committed) was handed to the user to run
against their own real account rather than sharing credentials — returned
`initPouringRadius: 750` for member_id 23237 / serial `J15A01B4CV030`,
confirming the request shape, `projectToken` reuse, and signing scheme all
correct on the first live attempt. Two unrelated local-environment issues
surfaced (both fixed in the verification script only, not an API/code
issue): an `aiodns`/`pycares` mismatch breaking aiohttp's default resolver
(worked around with `ThreadedResolver()`), and a local SSL CA trust-store
gap (fixed by pointing the connector at `certifi.where()`).

**Why**: XBloom's cloud surface turned out to be three separate,
independently-discovered backends, not one — worth checking which backend
a new cloud feature actually needs before assuming `client-api.xbloom.com`
covers everything.

**How to apply**: any future account-scoped device data (not just recipes)
should be suspected to live on `backend-api.xbloom.com`, not
`client-api.xbloom.com` — check there first.
