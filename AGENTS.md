# Repository agent instructions

> `CLAUDE.md` and `GEMINI.md` are local symlinks to this file (gitignored) — edit `AGENTS.md`.

Agent assets live under `.agents/` (the source of truth): `skills/`, `workflows/` (commands), `agents/`, and `memory/` (Claude's per-project memory). `.claude/` is a real directory: its `settings.json` is Claude-specific and tracked; its per-item symlinks into `.agents/` (`skills`, `commands` → `workflows`, `agents`) and `settings.local.json` are local-only, as are the `CLAUDE.md`/`GEMINI.md` → `AGENTS.md` symlinks and `.gemini` → `.agents`.

This file briefs Claude / GPT / other coding agents on the conventions and load-bearing facts of `ha_xbloom`. Read this before making changes.

## Repository layout

```
ha_xbloom/
├── custom_components/xbloom/      ← the HA integration (edit this)
│   ├── src/xbloom/                ← VENDORED upstream #1 (fhenwood/PyBloom) — DO NOT MODIFY
│   ├── src/xbloom-ble/            ← VENDORED upstream #2 (brAzzi64/xbloom-ble) — DO NOT MODIFY
│   ├── llm_tools/                 ← tools exposed via the HA LLM API
│   ├── translations/              ← per-locale entity/config UI strings
│   ├── strings.json               ← English source-of-truth for translations
│   ├── icons.json                 ← entity icons keyed by translation_key
│   ├── coordinator.py             ← BLE lifecycle + state aggregation
│   ├── _client.py                 ← HA-side wrapper around vendored XBloomClient
│   ├── brewing.py                 ← HA-side brew flow; cherry-picks tea protocol from src/xbloom-ble
│   └── ... (sensor / binary_sensor / button / number / select / switch / event / config_flow / __init__ / manifest / const)
├── .devcontainer/
├── scripts/
│   ├── setup                      ← installs HA + dev deps in the container
│   └── develop                    ← runs HA from this checkout for live testing
├── hacs.json
└── README.md
```

## Hard rules

1. **Do not modify either vendored upstream.** `custom_components/xbloom/src/xbloom/` mirrors fhenwood/PyBloom; `custom_components/xbloom/src/xbloom-ble/` mirrors brAzzi64/xbloom-ble. Both are reference copies. If a protocol change is needed, wrap or override in `_client.py` / `coordinator.py` / `brewing.py` instead. `src/xbloom-ble/` is intentionally not a Python package (no `__init__.py`, hyphen in path) — treat it as documentation + sample code, not a runtime import target. Cherry-pick by re-implementing the relevant snippet in HA-side code with a comment pointing at the upstream file.
2. **Never set `_attr_name` on an entity that has `_attr_translation_key`.** HA's `Entity._name_internal` returns `_attr_name` first and never consults the translation map afterwards — this silently breaks every non-English UI. Pick one or the other.
3. **Translations live in two places.** `strings.json` is the English source of truth; `translations/<lang>.json` files are the localized copies. They must share the same key tree. Add a Korean entry to `translations/ko.json` whenever you add an English entry to `strings.json`.
4. **Icons live in `icons.json`, not in entity classes.** Don't set `_attr_icon` unless the icon is dynamic (e.g. `XBloomErrorSensor` flips based on string content). Static icons go in `icons.json` keyed by `entity.<platform>.<translation_key>.default` (with optional `.state` map).
5. **Coordinator is the single source of truth for state.** Entities read `self.coordinator.data[...]`; they do not call BLE methods directly. Side-effects (start brew, stop, etc.) go through `XBloomCoordinator.async_*` methods.
6. **XBloom Original (Wi-Fi) is out of scope.** This integration only supports XBloom Studio, connected over Bluetooth LE — see `manifest.json`'s `bluetooth` matcher. Original uses an entirely different Wi-Fi-based protocol this codebase doesn't implement, and the maintainer has no Original hardware to test against. Don't add Original-specific BLE/protocol code on spec; if a change would only make sense for Original, flag it instead.

## XBloom firmware quirks

- **The machine ignores every command until it receives the `8100` MTU handshake.** Per `src/xbloom-ble/PROTOCOL.md`, writes succeed at the BLE level but produce no display wake, no LED indicator, and no `RD_MachineInfo` (40521) until the handshake — `build_packet_type1(8100, [185, 1])` — has been sent. The vendored `XBloomClient.connect` / `_reset_state` send `APP_RECIPE_STOP`/`BREWER_QUIT`/`GRINDER_QUIT` but **never** the handshake, so on strict firmwares MachineInfo never fires and the cleanup commands are silently dropped. `_client.XBloomClientWithEvents._reset_state` overrides the upstream to send `8100` first, and `coordinator._machine_info_retry_loop` re-sends the handshake (not `APP_RECIPE_STOP`) when MachineInfo hasn't arrived. Use `client.async_send_handshake()` if you need to retrigger it from elsewhere.
- **`RD_MachineInfo` (cmd 40521) may still arrive late or not at all on some firmwares.** The retry loop in `coordinator.py:_machine_info_retry_loop` and the manual-signature scanner in `_client.py:_scan_for_machine_info` handle the common cases, plus a GATT 180A read fallback. If all three fail, the Model / Serial / Firmware sensors will stay `unknown`. `_status.water_level_ok` (set only inside the `RD_MachineInfo` handler at `src/xbloom/core/client.py:272`) likewise stays `False` — `coordinator._async_update_data` therefore *cannot* trust the raw flag at idle. It uses `serial_number` non-empty as a proxy for "MachineInfo has been seen"; otherwise it derives water-shortage state from the `water_shortage` error event stream.
- **Tea recipes use the dedicated `4513`/`4512` path — NOT `8004`.** A PacketLogger HCI capture of the official iOS app (2026-05-28, all packets CRC-verified) shows tea brews go `8104` (set_cup, `(200, 80)`) → `4513` (`APP_TEA_RECIP_CODE`) → `4512` (`APP_TEA_RECIP_MAKE`). The earlier claim here that the app used the no-grind `8004` path was inferred from upstreams, never measured, and is **wrong** — `8004` with tea cup bounds was tested locally and the firmware did NOT enter tea mode (no tea UI, no siphon). `4513`/`4512` is the only known tea-mode trigger. The tea sequence lives in `brewing.py` (`_async_brew_tea`); do not patch the vendored library. Caveat: ha-xbloom's `4513` payload still differs from the official one (pattern/timing/footer bytes), so multi-steep recipes currently flatten into one pour — see `docs/en/brewing-notes.md`.
- **MachineInfo string fields are 0xFF-padded, not NUL-padded.** The `theModel` slice of the `RD_MachineInfo` (40521) payload is filled with `0xFF` on machines that don't populate it. A naive `decode('utf-8', errors='ignore')` lets some `0xFF` runs through whenever they form valid UTF-8 sequences with neighboring bytes — produces garbage in the Model sensor. Always run MachineInfo / GATT 180A bytes through `_client.strict_ascii()` (printable 0x20–0x7E only), cherry-picked from `src/xbloom-ble/python/xbloom.py:_handshake_notify._hex_ascii`.
- **Easy Mode slot writes (cmd 11510) are type-2 packets** — the type byte at packet offset 2 is `0x02`, not the usual `0x01`. Use `client._send_command_raw(11510, payload, type_code=2)`. Payload prefix is `[slot_index][flags]` followed by the same recipe blob `build_recipe_payload` produces for 8001/8004 brews.
- **Tea steeps end on `RD_TEA_RECIP_PAUSE` (40515) → "paused"** or `RD_ENJOY` (40512) → "recipe_complete". The firmware fires these between steeps inside one `8004` recipe — entities can listen via the event bus rather than orchestrating per-steep.

## BLE protocol primer

Packet layout: `header(0x58 0x02) | dev_id | type | cmd(2 LE) | len(4 LE) | const(0x01) | payload | crc(2)`.

Helpful constants live in `src/xbloom/protocol/constants.py`; the most thoroughly-decoded protocol reference is `src/xbloom-ble/PROTOCOL.md` (HCI snoop captures from the official iOS app). Notable inbound responses: `RD_MachineInfo` (40521), `RD_WATER_VOLUME` (40523), `RD_BREWER_PAUSE` (9010), `RD_TEA_RECIP_PAUSE` (40515), `RD_ENJOY` (40512), `RD_BLOOM`, `RD_BREWER_BEGIN`, `RD_Brewer_Stop`, `RD_GRINDER_BEGIN`, `RD_Grinder_Stop`. Notable outbound commands: `APP_BREWER_START`, `APP_RECIPE_SEND_AUTO` (8001, with grinding), `APP_RECIPE_SEND_MANUAL` (8004, no grinding), `APP_TEA_RECIP_CODE` (4513) / `APP_TEA_RECIP_MAKE` (4512, the live tea path), `APP_RECIPE_EXECUTE` (8002), `APP_RECIPE_STOP` (40519), `8022` (Back to Home, sent at the start of every recipe).

## XBloom cloud API

`_cloud_client.py` (HA-side, no vendored library — this API has no upstream) talks to
`https://client-api.xbloom.com` for optional cloud-account recipe management
(`cloud_search_recipes` / `cloud_create_recipe` / `cloud_edit_recipe` /
`cloud_delete_recipe` / `cloud_import_recipe` services, wired through
`coordinator.async_*_cloud_recipe` / `async_import_cloud_recipe`). Entirely separate
from the BLE protocol above — this is plain HTTPS, reverse-engineered from
[`denull0/xbloom-agent`](https://github.com/denull0/xbloom-agent)'s `index.ts` and
live-verified against a real account (2026-07-03). Login is optional; without
`CONF_EMAIL`/`CONF_PASSWORD` (set via the config-flow account step) the integration
behaves exactly as it does BLE-only.

**Endpoints** (form/JSON POST): `tMemberLogin.thtml` (login, plaintext), `RecipeDetail.html`
(fetch a public share link, plaintext, no auth), `tuMyTeaRecipeCreated.tuhtml` (list —
yes, this literal tea-sounding name lists *every* recipe type), `tuRecipeAdd.tuhtml`
(create), `tuRecipeUpdate.tuhtml` (edit, full-replace not merge-patch — fetch current
recipe first and overlay), `tuRecipeDelete.tuhtml` (delete). Every authenticated call
after login is whole-payload RSA-encrypted (`_rsa_encrypt`/`_post_encrypted`); only
login and the public share fetch are plaintext.

**`adaptedModel: 1` (Studio) is hardcoded** in both `list_recipes()`'s
`tuMyTeaRecipeCreated.tuhtml` payload and `create_recipe()`'s
`_CREATE_STATIC_FIELDS` — copied from the reference implementation, never
parameterized. This integration only supports XBloom Studio at all (BLE-only;
see the top-level "XBloom Original is not supported" limitation), so this
hasn't been an issue in practice, but it means the private-account cloud
sync/create path is unverified for whatever `adaptedModel` value Original
uses — nobody with an Original + cloud account has tested it.

**Four wire-API requirements that aren't obvious from the reference source and were
only found by live-testing against a real account** — get any of these wrong and the
API returns a generic non-actionable "abnormal pour data" (or similar) error with no
error code:

1. **Every pour object needs a `theName` field.** `"Bloom"` for the first pour,
   `"Pour {n+1}"` for the rest (`_local_pour_to_cloud`). Omitting it is silently
   rejected.
2. **`sum(pours[].volume_ml) + bypass_volume` must equal `dose_g * ratio`** for
   dosed (coffee-style, bypass-off) recipes — `validate_pour_volume_consistency()`
   checks this client-side before any network call. **Bypass-ON payload
   requirements are still unconfirmed live** — no currently-live example recipe has
   bypass enabled, so flag this before recommending `cloud_create_recipe`/
   `cloud_edit_recipe` (via `recipe_name`) for a local recipe with nonzero
   `bypass_volume`.
3. **`share_url` is server-assigned, not derivable client-side.** The reference
   implementation's own `btoa(String(tableId))` guess is wrong — decoding a real
   `shareRecipeLink` shows 16 bytes of opaque binary, not the table id's ASCII
   digits. `create_recipe()` does a follow-up `get_recipe(table_id)` call and reads
   the real `shareRecipeLink` back; never guess it.
4. **`delete_recipe` is idempotent for a previously-valid id, not for a
   never-existed one.** Deleting an id that *was* a real recipe returns success
   again on a second call; an id that never existed returns failure. The two
   aren't the same "already gone" case.

**Pattern/vibration mapping** (local schema, `schema.py`, was deliberately *not*
renumbered to match cloud — see `tasks/todo.md` Phase 1 deviation note): local
`pattern` ints `0/1/2` = `center/circular/spiral`; cloud ints `1/2/3` =
`centered/spiral/circular` — note both names and numbers differ, mapped through
`_LOCAL_PATTERN_TO_CLOUD`/`_CLOUD_PATTERN_TO_LOCAL` in `_cloud_client.py`, never
copied directly. Local `vibration` (single enum `none/before/after/both`) maps to
cloud's two independent booleans `isEnableVibrationBefore`/`After` via
`_local_vibration_to_cloud`/`_cloud_vibration_to_local`.

**A second, unrelated public frontend/API exists: `collective.xbloom.com` /
`collective-api.xbloom.com`** (a "Coffee Recipe Hub" community site, discovered
2026-07-03 by reading its React bundle — not documented anywhere, no relation to
`denull0/xbloom-agent`). A `collective.xbloom.com/recipe/{id}` link is a *different*
identifier space than the `share-h5.xbloom.com` share id (`<id>` here is the plain
numeric `communityRecipeId`, not the opaque base64 share id — `client-api.xbloom.com`'s
`RecipeDetail.html` rejects it directly). Live-verified: `POST
https://collective-api.xbloom.com/communityRecipe/recipe/detail {"id": <int>, "type":
1}` (no auth) returns `{"code": 200, "data": {..., "shareRecipeLink":
"https://share-h5.xbloom.com/?id=..."}}` — same recipe, cross-confirmed by fetching
both URLs for community recipe 317445 and diffing the translated result (identical).
`_cloud_client.fetch_shared_recipe()` detects a `collective.xbloom.com/recipe/{id}`
URL, resolves it to its `shareRecipeLink` via this second API, then hands off to the
normal `RecipeDetail.html` path rather than writing a second translation function —
the collective-api response shape differs subtly (`cupType` comes back as a string
there, e.g. `"Omni"`, plus a separate `cupTypeInt`, instead of the int
`RecipeDetail.html`/`cloud_recipe_to_local` expect).

**The same collective-api.xbloom.com backend also powers the hub's search
(`cloud_search_collective_recipes` service / `search_xbloom_collective_recipes`
LLM tool)** — live-verified 2026-07-03, wired through
`XBloomCloudClient.search_collective_recipes()`. `POST
communityRecipe/index/page` takes `pageIndex`/`pageSize`/`keyword`/`recipeType`
(1=coffee,2=tea)/`recipeUserType` (1=official,2=user)/`sort`
(1=date,2=likes,3=downloads)/`sortType` (1=asc,2=desc)/`originIds`/`varietalIds`/
`processIds`/`roastList`/`flavorIds`/`machineList`/`cupTypeList` — the last seven
are lists of numeric-or-string **ids**, not names. Those ids come from `POST
communityRecipe/recipe/criteria` (no auth, cached per `XBloomCloudClient`
instance in `_collective_criteria`), which returns `{originList, varietalList,
processingList (not "processList"), roastList, flavorList, machineList,
cupTypeList}`, each a `[{"name": ..., "value": ...}]` list. Rather than
hardcoding ~28 origins / ~49 varietals / ~93 flavors as static enums,
`search_collective_recipes()` resolves caller-supplied free-text names against
this live table case-insensitively (`_resolve_criteria_values`) and reports any
that don't match back in an `unmatched` dict instead of silently dropping them.
Each result row's `roast` field comes back as a numeric id (unlike
origin/varietal/process/flavor, which are already human-readable strings) —
`_collective_result_to_summary()` reverse-maps it through the same
`roastList` fetched for the request.

## Recipe sync architecture

`default_recipes.py`'s bundled `DEFAULT_RECIPES` is **not** an always-active
recipe layer anymore — it's now only a network-failure fallback. The lowest
recipe-precedence layer is `coordinator.cloud_synced_recipes`, populated by
`coordinator.async_sync_cloud_recipes()`: the account's own private cloud
recipes (`cloud_client.list_recipes()`, already includes full `pourList`) if
a cloud account is configured and login succeeds, otherwise XBloom's official
public recipes from the collective hub (`cloud_client.fetch_official_recipes()`
— capped at `_OFFICIAL_RECIPE_SYNC_LIMIT` since each one needs its own
`fetch_shared_recipe()` round-trip, unlike the account list). Only if *both*
of those fail (e.g. no network at all) does it fall back to the bundled
`default_recipes.py` list.

`__init__.py`'s `async_setup_entry` seeds `cloud_synced_recipes` synchronously
with the bundled list (no network call) so `coordinator.recipes` is never
empty, then kicks off the real sync via `hass.async_create_task(...)` —
**not** awaited inline — so a slow/unreachable cloud API can't stall
integration setup (fetching `_OFFICIAL_RECIPE_SYNC_LIMIT` official recipes is
one detail-fetch per recipe; awaiting that inline could push entry setup past
HA's own timeout). It also registers `async_track_time_interval(...,
CLOUD_RECIPE_SYNC_INTERVAL)` (hourly) so recipes added to the account (or new
official recipes) eventually show up without a manual reload.
`coordinator._rebuild_recipes()` recomputes `self.recipes` from
`cloud_synced_recipes` < YAML < `entry.options[CONF_RECIPES]` (unchanged
tombstone-by-`None` override semantics) and is called both at setup and at
the end of every sync; `async_sync_cloud_recipes()` also calls
`self.async_update_listeners()` so the recipe select entity and any other
`CoordinatorEntity` pick up the change immediately.

**`config_flow.py`'s `_all_visible_recipes()` duplicates this merge** (needed
because the OptionsFlow doesn't have direct access to `coordinator.recipes`
at the time it needs to know what's "visible" for Add/Edit/Delete) — it reads
`coordinator.cloud_synced_recipes` via `_synced_recipes()`, not the static
`hass.data[DOMAIN]["default_recipes"]` directly. If the merge logic changes
in one place, check the other.

## Entity translation flow

`_attr_has_entity_name = True` + `_attr_translation_key = "<key>"` →
HA looks up `entity.<platform>.<key>.name` from `translations/<ha_ui_lang>.json` (falls back to `strings.json`).

For state-enum sensors, also populate `entity.<platform>.<key>.state.<value>`.
For event entities with attribute enums, populate `entity.<platform>.<key>.state_attributes.event_type.state.<value>`.

## Testing

Use the devcontainer:

```bash
scripts/develop          # boots HA on :8123 with this integration mounted
```

There is no automated test suite yet. The integration is validated by:

1. Starting the devcontainer.
2. Adding the integration via Settings → Devices & Services with a real BLE MAC.
3. Driving each entity (pour / grind / recipe / cancel) and watching `home-assistant.log` for the `SEND CMD` / `RECV CMD` lines emitted by the vendored client.

## Release workflow

This repo (and other `ha-*` HACS components, excluding `ha-app*`) ships on a
two-track rolling draft release, maintained by release-drafter since
`e3bf99b` (#28): a `rc` (prerelease) draft and a `stable` draft, both updated
continuously as PRs merge to `main`.

1. Verify locally with the devcontainer (`scripts/develop`) before merging —
   see Testing above.
2. Once merged and the `rc` draft looks right, publish it as a prerelease
   from the GitHub Releases UI.
3. After the prerelease has been exercised with no issues, promote/publish
   the corresponding `stable` draft.

## When in doubt

- Localization broken? Check (2) above before anything else.
- Sensor stuck `unknown`? Check the firmware-quirks section.
- Tea recipe doing nothing? It must go through `brewing.async_execute_recipe` (8022 → 8102 → 8104 → 8004 → 8002), not the firmware's `4512`/`4513` constants — see the firmware-quirks entry.
- Adding a new entity? Update `strings.json` AND every file under `translations/`. Add an `icons.json` entry. Don't set `_attr_name` or `_attr_icon` on the class.
