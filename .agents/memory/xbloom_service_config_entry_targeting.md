---
name: xbloom-service-config-entry-targeting
description: "Every service's device_id field was migrated to config_entry_id (a config_entry selector, not device) after a hassfest schema conflict; a separate, more severe bug then had _coordinators_for_call iterate the resulting string character-by-character, silently breaking every targeted service call since the integration's first commit."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

**The selector migration**: a first attempt narrowed the `device_id`
field's `device` selector to the main device only via
`filter[0].entity: {domain: update}` — `hassfest` rejects `entity` as a key
inside a plain **field**-level `device` selector's `filter` (that sub-key is
only valid inside a **`target:`** block, which this integration doesn't
use). The failure cascaded into spurious `required key not provided
@ ...['target']` errors on every *other* service in the file too — a single
bad schema branch anywhere in `services.yaml` makes voluptuous retry the
whole document against an unrelated alternative schema, so a wall of
unrelated-looking errors can point at one root cause. Second attempt (kept):
a `config_entry` selector sidesteps the problem structurally — each config
entry maps 1:1 to a physical machine, so the picker only ever lists one item
per machine regardless of how many device-registry entries (main +
Grinder/Scale/Brewer, see the 4-device split) it owns. Confirmed against HA
core's actual `dev` branch source directly (this repo's installed
`homeassistant` test dependency was a full year behind the floor this
integration targets): `ConfigEntrySelector.CONFIG_SCHEMA` has **no
`multiple` key at all**, and `__call__` validates the result as a bare
string, not a list — so a `config_entry` selector can only ever pick one
machine, never several. The two services that previously accepted several
devices at once now can only target one specific machine or (blank field)
all of them — the "no selection = all machines" fallback was unchanged,
just the "several, but not all" middle case is gone.

**The string-iteration bug**: `_coordinators_for_call`'s handling did
`entry_ids = call.data.get("config_entry_id") or []` then
`for eid in entry_ids:` — since `call.data.get("config_entry_id")` is
always a bare string (never a list, per the selector fact above), iterating
a non-empty string iterates its individual *characters*. No single
character could ever match a real config entry id, so the call always fell
through to "No XBloom machine matched the service call." This silently
broke targeting a specific machine on **every** service that goes through
this helper (`execute_recipe`, `execute_tea_recipe`, `list_recipes`,
`create_recipe`, `edit_recipe`, `delete_recipe`,
`write_recipe_to_easy_slot`, `advanced_settings`, `cloud_import_recipe`,
`cloud_export_recipe`, `cloud_search_collective_recipes`) — present since
the integration's very first commit, only surfaced once a real user with a
specific `config_entry_id` in hand tried it (the "no selection" fallback
path masked it for everyone else). Fixed to a direct dict lookup instead of
a loop; `tests/test_coordinators_for_call.py` regression-tests it via
`SimpleNamespace` mocks (no full HA instance needed).

**Why**: a single-character silent-failure bug survived undetected for the
integration's entire history because the fallback behavior (targeting
nothing = targeting everything) looked correct in the overwhelmingly common
single-machine case.

**How to apply**: any future field backed by a non-`multiple` HA selector
must be treated as a scalar, never iterated as if it could be a list — this
bug class (assuming a selector value might be a list when the selector type
guarantees a scalar) is worth checking for elsewhere in this codebase if a
similarly-shaped "silently matches nothing" report ever recurs.
