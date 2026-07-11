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
│   ├── llm/                       ← LLM tools platform (entry point + catalog + tools)
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
- **Tea recipes use the dedicated `4513`/`4512` path — NOT `8004`.** A PacketLogger HCI capture of the official iOS app (2026-05-28, CRC-verified) confirmed `8104` (set_cup) → `4513` (`APP_TEA_RECIP_CODE`) → `4512` (`APP_TEA_RECIP_MAKE`); `8004` with tea cup bounds was tested locally and the firmware did NOT enter tea mode (no tea UI, no siphon). Lives in `brewing.py` (`_async_brew_tea`/`_build_tea_payload`); do not patch the vendored library. Multi-steep separation, real soak, and tea→coffee grinding were all fixed 2026-05-29 (pattern=1 substep byte + siphon-cap top-up trick + dropping a QUIT prelude that was killing the grinder) — see `docs/en/brewing-notes.md` for the byte-level history.
- **MachineInfo string fields are 0xFF-padded, not NUL-padded.** The `theModel` slice of the `RD_MachineInfo` (40521) payload is filled with `0xFF` on machines that don't populate it. A naive `decode('utf-8', errors='ignore')` lets some `0xFF` runs through whenever they form valid UTF-8 sequences with neighboring bytes — produces garbage in the Model sensor. Always run MachineInfo / GATT 180A bytes through `_client.strict_ascii()` (printable 0x20–0x7E only), cherry-picked from `src/xbloom-ble/python/xbloom.py:_handshake_notify._hex_ascii`.
- **Easy Mode slot writes (cmd 11510) are type-2 packets** — the type byte at packet offset 2 is `0x02`, not the usual `0x01`. Use `client._send_command_raw(11510, payload, type_code=2)`. Payload prefix is `[slot_index][flags]` followed by the same recipe blob `build_recipe_payload` produces for 8001/8004 brews.
- **Tea steeps end on `RD_TEA_RECIP_PAUSE` (40515) → "paused"** or `RD_ENJOY` (40512) → "recipe_complete". The firmware fires these between steeps inside one `8004` recipe — entities can listen via the event bus rather than orchestrating per-steep.

## BLE protocol primer

Packet layout: `header(0x58 0x02) | dev_id | type | cmd(2 LE) | len(4 LE) | const(0x01) | payload | crc(2)`.

Helpful constants live in `src/xbloom/protocol/constants.py`; the most thoroughly-decoded protocol reference is `src/xbloom-ble/PROTOCOL.md` (HCI snoop captures from the official iOS app). Notable inbound responses: `RD_MachineInfo` (40521), `RD_WATER_VOLUME` (40523), `RD_BREWER_PAUSE` (9010), `RD_TEA_RECIP_PAUSE` (40515), `RD_ENJOY` (40512), `RD_BLOOM`, `RD_BREWER_BEGIN`, `RD_Brewer_Stop`, `RD_GRINDER_BEGIN`, `RD_Grinder_Stop`. Notable outbound commands: `APP_BREWER_START`, `APP_RECIPE_SEND_AUTO` (8001, with grinding), `APP_RECIPE_SEND_MANUAL` (8004, no grinding), `APP_TEA_RECIP_CODE` (4513) / `APP_TEA_RECIP_MAKE` (4512, the live tea path), `APP_RECIPE_EXECUTE` (8002), `APP_RECIPE_STOP` (40519), `8022` (Back to Home, sent at the start of every recipe).

## BLE connection management

- **Connects through HA's Bluetooth integration, not a bare `BleakClient`.** The vendored `src/xbloom/connection/bleak_impl.py` opens `BleakClient(mac_address)` directly — no HA proxy routing, no `bleak-retry-connector` retry/cache-clear handling. `_client.HABleakConnection` (injected via the vendored `XBloomClient(connection=...)` constructor param, never by editing the vendored file) resolves the address through `bluetooth.async_ble_device_from_address` and connects via `bleak_retry_connector.establish_connection` instead. `manifest.json` depends on the `bluetooth` integration and requires `bleak-retry-connector` for this.
- **Auto-reconnects on an unexpected BLE drop.** Before 2026-07-04 nothing ever called `coordinator.async_connect()` again after an unrequested disconnect — only the connection switch's `async_turn_on` did — so any drop left the switch stuck "off" until manually flipped. `HABleakConnection`'s `disconnected_callback` now calls `coordinator._handle_unexpected_disconnect()`, which reconnects unless the drop was caused by `async_disconnect()` itself (tracked via `_manual_disconnect`, so turning the switch off on purpose doesn't immediately reconnect).
- **A stray header byte inside telemetry can produce a garbage frame length.** The vendored framing loop (`src/xbloom/core/client.py:_on_notification`) scans raw notification bytes for a header byte (`0x58`/`0x02`) and reads the next 4 bytes as the packet length with no bounds check — a false match inside the weight/water-volume telemetry stream (which floods at multi-Hz) can read garbage (e.g. `0xc2000001` = 3254779905) and, in the vendored code, discards the rest of the buffer with a misleading "Partial packet received" warning. `_client.py`'s `_on_notification` override replaces the framing loop (`_split_and_parse`) with the same logic plus a `_MAX_PACKET_LEN` (256) sanity bound: anything larger is a false-positive header byte, skipped instead of aborting the buffer.
- **Changing the mode-select entity must not reload the config entry.** `coordinator.async_set_mode()` persists the preference via `hass.config_entries.async_update_entry()`, which fires `__init__.py`'s `_async_update_listener`. `CONF_MODE` is in `_NO_RELOAD_OPTION_KEYS` (alongside the recipe-store keys) specifically so this doesn't trigger `hass.config_entries.async_reload()` — a reload's `async_unload_entry` calls `coordinator.async_disconnect()`, and nothing in `async_setup_entry` reconnects automatically, so every mode switch used to drop the connection and leave it dropped (confirmed live 2026-07-04, and easy to mistake for a firmware quirk — it wasn't).

## XBloom cloud API

`_cloud_client.py` (HA-side, no vendored library — this API has no upstream) talks to
`https://client-api.xbloom.com` for optional cloud-account recipe management —
`cloud_import_recipe` / `cloud_export_recipe` services, wired through
`coordinator.async_import_cloud_recipe` / `async_export_recipe` (plus the one-time
account seed, `async_seed_recipes`; see the Recipe store architecture section
below). Entirely separate from the BLE protocol above — this is plain HTTPS,
reverse-engineered from
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

**`adaptedModel: 1` (Studio) is hardcoded** in `list_recipes()`'s
`tuMyTeaRecipeCreated.tuhtml` payload and `create_recipe()`'s
`_CREATE_STATIC_FIELDS` — copied from the reference implementation, never
parameterized. Since this integration only supports Studio (see the
Original limitation above), this hasn't mattered in practice, but the
account recipe seed and `cloud_export_recipe` are both unverified for
whatever `adaptedModel` value Original uses.

**Four wire-API requirements that aren't obvious from the reference source and were
only found by live-testing against a real account** — get any of these wrong and the
API returns a generic non-actionable "abnormal pour data" (or similar) error with no
error code:

1. **Every pour object needs a `theName` field.** `"Bloom"` for the first pour,
   `"Pour {n+1}"` for the rest (`_local_pour_to_cloud`). Omitting it is silently
   rejected.
2. **`sum(pours[].volume_ml) + bypass_volume` must equal `dose_g * ratio`** for
   dosed (coffee-style, bypass-off) recipes — `validate_pour_volume_consistency()`
   checks this client-side before any network call, but `async_export_recipe`
   only runs that check when `bypass_volume == 0`. **Bypass-ON recipes don't
   follow this formula**: live account data confirmed 2026-07-04 shows
   `pours` alone already summing to `dose_g * ratio`, with `bypass_volume`
   sitting on top as extra water rather than counting toward that budget —
   the opposite of what the bypass-off formula would require. The exact
   bypass-ON wire constraint (if any) is still unconfirmed, so
   `cloud_export_recipe` skips the hard check and just attaches a `warning`
   for any recipe with nonzero `bypass_volume`.
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
renumbered to match cloud — see `tasks/archive/2026-07-recipe-local-source-of-truth-todo.md`
Phase 1 deviation note): local
`pattern` ints `0/1/2` = `center/circular/spiral`; cloud ints `1/2/3` =
`centered/spiral/circular` — note both names and numbers differ, mapped through
`_LOCAL_PATTERN_TO_CLOUD`/`_CLOUD_PATTERN_TO_LOCAL` in `_cloud_client.py`, never
copied directly. Local `vibration` (single enum `none/before/after/both`) maps to
cloud's two independent booleans `isEnableVibrationBefore`/`After` via
`_local_vibration_to_cloud`/`_cloud_vibration_to_local`.

**A second, unrelated public API exists: `collective.xbloom.com` /
`collective-api.xbloom.com`** (a "Coffee Recipe Hub" community site, found
2026-07-03 by reading its React bundle — undocumented, unrelated to
`denull0/xbloom-agent`). Its `collective.xbloom.com/recipe/{id}` uses a
*different* identifier space than `share-h5.xbloom.com` — `<id>` is the
plain numeric `communityRecipeId`, not the opaque share id, and
`RecipeDetail.html` rejects it directly. `POST
collective-api.xbloom.com/communityRecipe/recipe/detail {"id", "type": 1}`
(no auth) returns the same recipe's `shareRecipeLink`, cross-confirmed
against `RecipeDetail.html`. `_cloud_client.fetch_shared_recipe()` resolves
a collective link to its `shareRecipeLink` via this API, then hands off to
the normal `RecipeDetail.html` path — the collective response shape
differs subtly (`cupType` is a string there, e.g. `"Omni"`, plus a
separate `cupTypeInt`), so it isn't reused directly.

**The same backend powers the hub's search**
(`cloud_search_collective_recipes` service /
`search_xbloom_collective_recipes` LLM tool, `XBloomCloudClient.search_collective_recipes()`).
`POST communityRecipe/index/page` takes `pageIndex`/`pageSize`/`keyword`/
`recipeType` (1=coffee,2=tea)/`recipeUserType` (1=official,2=user)/`sort`/
`sortType`/`originIds`/`varietalIds`/`processIds`/`roastList`/`flavorIds`/
`machineList`/`cupTypeList` — the last seven are id lists, not names. The
ids come from `POST communityRecipe/recipe/criteria` (no auth, cached per
client in `_collective_criteria`): `{originList, varietalList,
processingList, roastList, flavorList, machineList, cupTypeList}`, each
`[{"name", "value"}]`. `_resolve_criteria_values` matches a raw **code**
first (exact `value` — what the services.yaml multi-select submits, and
the escape hatch for categories our snapshot doesn't know yet), then a
case-insensitive **name**; unmatched entries are reported back in an
`unmatched` dict rather than dropped. Values aren't hardcoded as static
enums — the live criteria table is always the source of truth, and
services.yaml/strings.json only hold a UI-convenience snapshot. Each
result row's `roast` comes back as a numeric id (unlike
origin/varietal/process/flavor) — `_collective_result_to_summary()`
reverse-maps it through the same `roastList`.

## Recipe store architecture (local source of truth)

> Replaces an earlier always-on cloud sync layer (`cloud_synced_recipes` /
> hourly interval); see `tasks/archive/2026-07-recipe-local-source-of-truth-{spec,plan,todo}.md`
> for the rework (verified against real hardware 2026-07-04), and
> `tasks/archive/2026-06-cloud-recipes-{plan,todo}.md` for what preceded it.

**`entry.options[CONF_RECIPES]`, keyed by name, is the single source of
truth.** Each recipe dict carries optional metadata (`RECIPE_SCHEMA`):
`uid` (`uuid4().hex[:12]`, assigned on create/import/seed; YAML recipes get
a deterministic `"yaml-" + sha1(name)[:8]`), `cloud_table_id` + `share_url`
(set on export/import), and `source` (`manual`/`import`/`seed_*`/`yaml`).
Brewing ignores these fields. `schema.find_recipe(recipes, identifier)`
resolves the cross-identifier every service/LLM tool takes — uid → cloud
table id (int) → share URL/id → exact name, returning `(name, recipe)` —
and `coordinator._looks_like_share_ref()` decides whether an unresolved
identifier triggers auto-import (edit/write-slot do; execute doesn't).

**Seeding is one-time, not a sync.** `async_setup_entry` writes the
bundled `default_recipes.py` set synchronously (only when the store is
empty and `CONF_RECIPES_SEEDED` is unset, so the dropdown is never empty),
then backgrounds `coordinator.async_seed_recipes()` via
`hass.async_create_task(...)` so a slow cloud API can't stall setup. That
task fetches the account's own recipes if a login is configured (flag
`CONF_ACCOUNT_RECIPES_SEEDED` — linking an account later seeds once more)
or XBloom's official public recipes otherwise (flag `CONF_RECIPES_SEEDED`,
capped at `_OFFICIAL_RECIPE_SYNC_LIMIT`); names already present locally —
tombstones and YAML names included — are skipped, and a failed fetch
leaves its flag unset for the next HA start to retry.

`coordinator._rebuild_recipes()` merges two layers only: YAML
(`hass.data[DOMAIN]["yaml_recipes"]`) < the local store, where a `None`
store value tombstones a YAML name. All CRUD (`create_local_recipe` /
`async_edit_local_recipe` / `delete_local_recipe`, plus import/export)
funnels through `_write_options_recipes()`, which persists, rebuilds, and
calls `async_update_listeners()`. Name collisions get a ` (2)` suffix
(`dedupe_name`), never an overwrite. Config entry **v3**
(`async_migrate_entry`) injects `uid`/`source` into pre-existing recipes,
preserving tombstones.

`config_flow.py`'s `_all_visible_recipes()` duplicates this two-layer
merge (the OptionsFlow needs it without going through the coordinator) —
change both together.

## LLM tools platform (`llm/`)

> Introduced 2026-07 for HA ≥ 2026.8 (core's new `llm` integration platform —
> the reason for the `2026.8.0.dev*` floor in `hacs.json`); see
> `tasks/2026-07-llm-platform-migration-spec.md` for the full design.

The 13 Assist tools live in the **`llm/` platform package** — `catalog.py`
(`build_tools()`, the single tool list; `tests/test_llm_prompt.py` checks
`XBLOOM_LLM_PROMPT` against it) plus one module per tool group. The entry
point `llm/__init__.py` implements core's `async_get_tools(hass, llm_context,
api_id)` hook and answers **only** our per-entry api_ids
(`xbloom_coffee_<entry_id>`); Assist and every other API get `None`, so the
tools surface exclusively through the user-selected custom API registered by
`llm_api.py` (a thin shell — the opt-in UX predates the platform and must
stay). MCP exposure is automatic: every registered API is served at
`/api/mcp/<api_id>` (admin token required for non-Assist).

**Lazy-loading invariants — AST-pinned by `tests/test_llm_platform.py`; do
not break them when refactoring:**

1. `llm/__init__.py` stays import-light: no tool/catalog/
   `homeassistant.components.llm` imports at module level. Core imports every
   integration's `llm` platform on the first tool collection of *any* API —
   a heavy entry module would load our tools for users who never enabled the
   XBloom API (and break the pre-2026.8 test host).
2. The setup path (`__init__.py`, `llm_api.py`) never imports `.llm` **or any
   `.llm.*` submodule** (a submodule import executes the package `__init__`
   first). `llm_api.py` references the platform by string module path only.
3. `XBloomCoffeeAPI.async_get_api_instance` pre-imports `llm.catalog` via
   `helpers.importlib.async_import_module` (executor) before calling **our
   own** `async_get_tools` — not core's collector, which isn't a documented
   surface for custom APIs. The callback's function-level imports are then
   cache hits; HA's `block_async_io` flags a module's first import inside the
   event loop.

API id/name strings (`xbloom_coffee_<entry_id>`, `"XBloom Coffee Machine
(<MAC>)"`) are pinned by test — changing them breaks existing agent configs.
Unregistration rides `entry.async_on_unload` (official docs pattern); there
is no manual unregister path.

## Entity translation flow

`_attr_has_entity_name = True` + `_attr_translation_key = "<key>"` →
HA looks up `entity.<platform>.<key>.name` from `translations/<ha_ui_lang>.json` (falls back to `strings.json`).

For state-enum sensors, also populate `entity.<platform>.<key>.state.<value>`.
For event entities with attribute enums, populate `entity.<platform>.<key>.state_attributes.event_type.state.<value>`.

## Testing

Use the devcontainer — its base image is the **official HA dev nightly**
(`homeassistant/home-assistant:2026.8.0.dev202607110310`), which bundles HA
core and every default_config runtime dep, so `scripts/setup` only pip-installs
dev tools. The image tag, `hacs.json`'s `homeassistant` floor, and
`requirements_test.txt`'s pin must stay the **same version string** (move all
three to `>=2026.8.0b0` together once the 2026.8 beta ships):

```bash
scripts/develop          # boots HA on :8123 with this integration mounted
```

`pytest tests/` covers the pure-logic pieces (uid metadata, `find_recipe`
resolution, pour scaling, v2→v3 migration, name dedupe, criteria matching,
LLM-prompt/tool-name consistency, llm platform gating/catalog/lazy-loading
invariants) and runs without an HA instance — on a pre-2026.8 host the
success-path tests skip; inside the devcontainer everything runs. Everything
BLE-facing is still validated manually:

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
- Tea recipe doing nothing, or steeps flattening into one pour? Tea must go through `brewing._async_brew_tea` (8022 → 8102 → 8104 → 4513 → 4512) — `8004` does not trigger tea mode at all. See the firmware-quirks entry.
- Adding a new entity? Update `strings.json` AND every file under `translations/`. Add an `icons.json` entry. Don't set `_attr_name` or `_attr_icon` on the class.
