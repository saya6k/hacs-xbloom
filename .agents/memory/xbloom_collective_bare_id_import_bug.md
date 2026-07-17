---
name: xbloom-collective-bare-id-import-bug
description: "cloud_import_recipe silently failed for a bare community recipe id (just the digits, no collective.xbloom.com/recipe/ URL prefix) because fetch_shared_recipe only recognized the community-id shape inside the full URL, not as a standalone numeric string - fixed by treating any bare all-digit identifier as a community recipe id."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Hardware-reported 2026-07-18: `cloud_import_recipe`/`import_xbloom_cloud_recipe`
failed with the generic "Could not fetch that recipe" error when given a
bare community recipe id copied from collective.xbloom.com (just the
digits, e.g. `123456`, not the full `https://collective.xbloom.com/recipe/123456`
URL).

Root cause: `_cloud_client.fetch_shared_recipe()`'s collective-id detection
was `_COLLECTIVE_RECIPE_URL_RE.search(value)` — a regex requiring the
literal substring `collective.xbloom.com/recipe/` to be present. A bare
numeric string doesn't match, so it fell through to `_parse_share_id()`,
which for anything that isn't a `share-h5.xbloom.com` URL just returns the
input unchanged — treating the community recipe id as if it were an opaque
share-h5 share id. Per
[[xbloom-collective-hub-and-backend-api]], these are genuinely different
identifier spaces (`communityRecipeId` is plain numeric; a real share-h5
share id is base64/opaque), so `RecipeDetail.html` rejects the community id
outright with no useful error code — matching the generic failure message
reported.

Fixed: `fetch_shared_recipe` now also treats a bare all-digit string as a
community recipe id (`value.isdigit()`), routing it through
`_resolve_collective_link()` exactly like the full-URL case, before falling
through to the share-h5 path. `coordinator.recipes.RecipesMixin.
_looks_like_share_ref()` (the heuristic that decides whether `edit_recipe`/
`write_recipe_to_easy_slot` should auto-import an unresolved identifier)
was extended the same way — by the time it runs, `find_recipe` has already
tried the identifier as a local cloud table id and failed, so the only risk
of the broadened heuristic is one extra, cleanly-failing network round-trip
for the rare recipe named entirely in digits, not a wrong match.

**Why**: this is the same "identifier space confusion" class as the other
collective-vs-share-h5 findings in
[[xbloom-collective-hub-and-backend-api]] — a real share-h5 share id is
never a plain decimal integer, so `.isdigit()` is an unambiguous
disambiguator between the two spaces, not a heuristic guess.

**How to apply**: if a future report shows import failing for some other
identifier shape (e.g. a URL-encoded or truncated id), check
`fetch_shared_recipe`'s routing logic first — this is the second bug found
in that exact function's identifier-shape handling.
