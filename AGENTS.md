# Repository agent instructions

> `CLAUDE.md` and `GEMINI.md` are local symlinks to this file (gitignored) — edit `AGENTS.md`.

Agent assets live under `.agents/` (the source of truth): `skills/`, `workflows/` (commands), `agents/`, and `memory/` (Claude's per-project memory). `.claude/` is a real directory: its `settings.json` is Claude-specific and tracked; its per-item symlinks into `.agents/` (`skills`, `commands` → `workflows`, `agents`) and `settings.local.json` are local-only, as are the `CLAUDE.md`/`GEMINI.md` → `AGENTS.md` symlinks and `.gemini` → `.agents`.

This file briefs Claude / GPT / other coding agents on the conventions and load-bearing facts of `ha_xbloom`. Read this before making changes. It's deliberately a *current-state* reference, not a lab notebook — the forensic history behind non-obvious facts here (hardware reports, decompile trails, wrong turns and their corrections) lives in Claude's project memory (`.agents/memory/` / the auto-memory system), cross-referenced below by topic. Read a linked memory entry when you need the "why," not just the "what."

## Repository layout

```
ha_xbloom/
├── custom_components/xbloom/      ← the HA integration (edit this)
│   ├── src/xbloom/                ← REFERENCE COPY of upstream #1 (fhenwood/PyBloom) — DO NOT MODIFY, not imported at runtime
│   ├── src/xbloom-ble/            ← REFERENCE COPY of upstream #2 (brAzzi64/xbloom-ble) — DO NOT MODIFY, not imported at runtime
│   ├── llm/                       ← LLM tools platform (entry point + catalog + tools)
│   ├── translations/              ← per-locale entity/config UI strings
│   ├── strings.json               ← English source-of-truth for translations
│   ├── icons.json                 ← entity icons keyed by translation_key
│   ├── coordinator.py             ← BLE lifecycle + state aggregation (single source of truth for entities)
│   ├── _client.py                 ← BLE client: connection, framing, notification dispatch, event bus
│   ├── _cloud_client.py           ← XBloom cloud API (client-api.xbloom.com + collective/backend APIs)
│   ├── brewing.py                 ← HA-side brew flow (coffee + tea)
│   └── ... (sensor / binary_sensor / button / number / select / switch / event / config_flow / __init__ / manifest / const / schema)
├── adr/                           ← Architecture Decision Records
├── docs/en/, docs/ko/             ← user-facing docs (index, brewing-notes, protocol)
├── .devcontainer/
├── scripts/
│   ├── setup                      ← installs HA + dev deps in the container
│   └── develop                    ← runs HA from this checkout for live testing
├── hacs.json
└── README.md
```

## Hard rules

1. **`src/xbloom` and `src/xbloom-ble` are reference/attribution copies, not runtime dependencies.** Both mirror their upstreams (`fhenwood/PyBloom`, `brAzzi64/xbloom-ble`) byte-for-byte and must never be modified. Per [ADR-001](adr/001-clean-room-reimplementation-of-xbloom-ble.md), this integration's BLE client, framing, and command table are a clean-room native implementation in `custom_components/xbloom/` (currently `_client.py` + `coordinator.py` + `brewing.py`; a dedicated `ble/` package is planned, see the ADR) — built from this integration's own hardware findings and protocol documentation, not by importing or patching the vendored source. If you're unsure whether something is still imported from `src/xbloom` at runtime, check the actual `import` statements — don't assume from history.
2. **Never set `_attr_name` on an entity that has `_attr_translation_key`.** HA's `Entity._name_internal` returns `_attr_name` first and never consults the translation map afterwards — this silently breaks every non-English UI. Pick one or the other.
3. **Translations live in two places.** `strings.json` is the English source of truth; `translations/<lang>.json` files are the localized copies. They must share the same key tree. Add a Korean entry to `translations/ko.json` whenever you add an English entry to `strings.json`.
4. **Icons live in `icons.json`, not in entity classes.** Don't set `_attr_icon` unless the icon is dynamic (e.g. `XBloomErrorSensor` flips based on string content). Static icons go in `icons.json` keyed by `entity.<platform>.<translation_key>.default` (with optional `.state` map).
5. **Coordinator is the single source of truth for state.** Entities read `self.coordinator.data[...]`; they do not call BLE methods directly. Side-effects (start brew, stop, etc.) go through `XBloomCoordinator.async_*` methods.
6. **XBloom Original (Wi-Fi) is out of scope.** This integration only supports XBloom Studio, connected over Bluetooth LE — see `manifest.json`'s `bluetooth` matcher. Original uses an entirely different Wi-Fi-based protocol this codebase doesn't implement, and the maintainer has no Original hardware to test against. Don't add Original-specific BLE/protocol code on spec; if a change would only make sense for Original, flag it instead.

## BLE protocol

**Full reference**: [`docs/en/protocol.md`](docs/en/protocol.md) (Korean: [`docs/ko/protocol.md`](docs/ko/protocol.md)) — packet framing, the complete command table (every `APP_*`/`RD_*` id this integration sends or handles, with status/payload/notes), and a summary of known transport quirks. Written fresh from this integration's own captures and APK decompilation (`androguard`/`jadx` against the official Android app) — treat it as more authoritative than the vendored `src/xbloom-ble/PROTOCOL.md`.

Packet layout: `header(0x58 0x02) | dev_id | type | cmd(2 LE) | len(4 LE) | const(0x01) | payload | crc(2)`. Type-2 commands (`11506`–`11512` family — mode switch, Easy Mode slots, pour radius/vibration amplitude) need `type_code=2` and a `0xC2` response marker instead of the usual `0xC1`, plus ≥0.8s spacing between back-to-back type-2 sends. The `8100` MTU handshake gates every other command.

**Quick-reference checklist** — each line links to the memory entry with the full investigation history (hardware evidence, decompile trail, prior wrong turns):

- Machine ignores everything until `8100` lands, including on reconnect/retry → [[xbloom-8100-handshake-and-firmware-history]]
- `RD_MachineInfo` (40521) may arrive late or never; its string fields are `0xFF`-padded (use `strict_ascii()`, never naive UTF-8) → [[xbloom-machineinfo-reliability-and-padding]]
- `starting`/`brewing`/`ready` are only reliable via the raw status-heartbeat frame, not the cmd-tagged `RD_GRINDER_BEGIN`/`RD_BREWER_BEGIN`/etc.; a connected-but-never-brewed machine reports `idle`, not stuck `unknown` → [[xbloom-raw-state-heartbeat-vs-cmd-tagged]]
- Easy Mode slot writes (`11510`) must be a full A/B/C batch from PRO mode, no single-slot path → [[xbloom-easy-mode-slot-batch-write]]
- `40518`/`8104` semantics were disputed by third-party captures and settled by decompiling the official app directly → [[xbloom-40518-and-8104-third-party-claims-refuted]]
- Most of the command table was cross-checked against the official app's own bytecode → [[xbloom-full-command-table-androguard-sweep]]
- Pour radius / vibration amplitude / display brightness / grinder calibration payload shapes → [[xbloom-advanced-features-jadx-findings]]
- Type-2 commands (11506-11512 family) need `type_code=2`, `0xC2` marker, MachineInfo-gated timing, and ≥0.8s spacing — five-layer debugging history → [[xbloom-advanced-settings-transport-bugs]]
- Mode-switch ACK (`11511`) needs the same `0xC2` marker fix; retry logic mirrors the official app's ACK-timeout-while-sleeping spec → [[xbloom-easymode-ack-marker-and-mode-switch-retry]]
- Pause/resume/cancel must target the right command family (`_active_operation`: recipe vs. manual grind vs. manual pour) → [[xbloom-manual-operation-command-targeting]]
- The machine's own "insert pod" prompt (on NFC detection) needs `8017` to dismiss, folded into the cancel button → [[xbloom-dismiss-pod-prompt-8017]]
- Grinder calibration completion is `RD_CurrentGrinder == 85` (or a 180s timeout) — **never** `RD_Grinder_Stop`, which fires early as part of the sweep's own homing move → [[xbloom-grinder-calibration-completion-signal-saga]]
- `RD_ErrorLackOfWater` (40522) is bidirectional (0=empty, 1=refilled); never trust the connect-time `water_level_ok` snapshot directly → [[xbloom-water-shortage-and-level-derivation]]
- Display units and water source can be pushed *from* the machine (`8015`) and set *to* it (`4508`); both need `_NO_RELOAD_OPTION_KEYS` → [[xbloom-unit-and-water-source-sync]]
- Tea steeps pause/resume via `40515`/`9011`; every new event type needs `event.py` + all 3 translation files or it crashes at runtime → [[xbloom-tea-steep-events]]
- `SG_*` scale-gesture commands are not real (vendor-named but never sent by the official app) → [[xbloom-removed-features]]
- `temperature_c` accepts `"RT"`/`"BP"` — fixed constants (20/98), not computed values → [[xbloom-temperature-name-constants]]

If a quirk you're debugging isn't in this checklist, it may not have been hit yet — check `docs/en/protocol.md`'s command table for the id's confirmed/unconfirmed status before assuming new behavior, and write a new memory entry (project-type) once you've root-caused it, rather than growing this file.

## BLE connection management

Connects through HA's Bluetooth integration (`bluetooth.async_ble_device_from_address` + `bleak_retry_connector.establish_connection`), not a bare `BleakClient` — required for HA proxy routing and retry/cache-clear handling. Auto-reconnects on an unexpected drop, with a backstop poll-driven retry and a notification-silence watchdog (`_BLE_SILENCE_TIMEOUT_S`, 15s) mirroring the official app's own connection supervisor. Outbound writes are chunked to ≤100 bytes, matching the official app's BLE write splitting. Full history (why each piece exists, what broke before the fix, what's still unverified) → [[xbloom-connection-race-and-supervisor]].

**Changing the mode-select entity (or any bidirectional machine setting) must not reload the config entry** — reloading calls `async_unload_entry` → `coordinator.async_disconnect()` with nothing to reconnect automatically, silently dropping the connection on every change. Any option key backing a machine-pushable setting must be in `__init__.py`'s `_NO_RELOAD_OPTION_KEYS`.

## Device registry (4-device split)

Each config entry has **4 device-registry entries**, not 1: the main device plus Grinder/Scale/Brewer child devices, linked via `via_device` (`coordinator.grinder_device_info`/`scale_device_info`/`brewer_device_info`, backed by `_sub_device_info()`). `unique_id`s are untouched — pure device-page regrouping. Deliberately not HA's "config subentries" feature (wrong fit for fixed sub-components of one physical machine).

`via_device` does **not** give you translation (use `translation_key` + a top-level `device.<key>.name` block, never a literal `name=`) or area propagation (`_sub_device_info()` seeds `suggested_area` from the main device at creation time only, no ongoing sync) for free. The main device must be registered explicitly in `async_setup_entry` before `async_forward_entry_setups`, since platform registration order isn't fixed. Full history → [[xbloom-device-registry-4way-split]].

## XBloom cloud API

`_cloud_client.py` (no vendored library — this API has no upstream) talks to `client-api.xbloom.com` for optional cloud-account recipe management (`cloud_import_recipe`/`cloud_export_recipe` services, plus the one-time account seed) — entirely separate from the BLE protocol above, plain HTTPS. Login is optional; without `CONF_EMAIL`/`CONF_PASSWORD` the integration behaves exactly as it does BLE-only.

Endpoints, wire-format gotchas (missing `theName` field, pour-volume-sum constraints, server-assigned `share_url`, asymmetric delete idempotency), and the pattern/vibration mapping between local and cloud schemas → [[xbloom-cloud-wire-api-quirks]].

**`adaptedModel: 1` (Studio) is hardcoded** in `list_recipes()`'s `tuMyTeaRecipeCreated.tuhtml` payload and `create_recipe()`'s `_CREATE_STATIC_FIELDS` — copied from the reference implementation, never parameterized. Since this integration only supports Studio (see hard rule #6), this hasn't mattered in practice, but the account recipe seed and `cloud_export_recipe` are both unverified for whatever `adaptedModel` value Original uses.

A Product/Shared account recipe tab feature was implemented then reverted same-day for lacking a concrete use case → [[xbloom-removed-features]].

Two more, separate cloud backends exist beyond `client-api.xbloom.com`: `collective.xbloom.com`/`collective-api.xbloom.com` (public recipe hub, powers `cloud_search_collective_recipes`) and `backend-api.xbloom.com` (signed Retrofit API, used for the real per-device pour-radius center value) → [[xbloom-collective-hub-and-backend-api]].

## Recipe store architecture (local source of truth)

`entry.options[CONF_RECIPES]`, keyed by name, is the single source of truth. Each recipe dict carries optional metadata (`RECIPE_SCHEMA`): `uid` (`uuid4().hex[:12]`, assigned on create/import/seed; YAML recipes get a deterministic `"yaml-" + sha1(name)[:8]`), `cloud_table_id` + `share_url` (set on export/import), and `source` (`manual`/`import`/`seed_*`/`yaml`). Brewing ignores these fields. `schema.find_recipe(recipes, identifier)` resolves the cross-identifier every service/LLM tool takes — uid → cloud table id (int) → share URL/id → exact name, returning `(name, recipe)` — and `coordinator._looks_like_share_ref()` decides whether an unresolved identifier triggers auto-import (edit/write-slot do; execute doesn't).

Seeding is one-time, not a sync. `async_setup_entry` writes the bundled `default_recipes.py` set synchronously (only when the store is empty and `CONF_RECIPES_SEEDED` is unset, so the dropdown is never empty), then backgrounds `coordinator.async_seed_recipes()` via `hass.async_create_task(...)` so a slow cloud API can't stall setup. That task fetches the account's own recipes if a login is configured (flag `CONF_ACCOUNT_RECIPES_SEEDED` — linking an account later seeds once more) or XBloom's official public recipes otherwise (flag `CONF_RECIPES_SEEDED`, capped at `_OFFICIAL_RECIPE_SYNC_LIMIT`, `cup_type=["Omni"]` only); names already present locally (tombstones and YAML names included) are skipped, and a failed fetch leaves its flag unset for the next HA start to retry.

`default_recipes.py`'s coffee section is intentionally empty — the async official-recipe seed above is the sole coffee source, so the dropdown isn't empty on a fresh install but is never a stale hardcoded snapshot either. Its tea section stays static (4 entries, sourced from real product pages) since the async seed's `cup_type=["Omni"]` filter deliberately excludes tea.

`coordinator._rebuild_recipes()` merges two layers only: YAML (`hass.data[DOMAIN]["yaml_recipes"]`) < the local store, where a `None` store value tombstones a YAML name. All CRUD (`create_local_recipe`/`async_edit_local_recipe`/`delete_local_recipe`, plus import/export) funnels through `_write_options_recipes()`, which persists, rebuilds, and calls `async_update_listeners()`. Name collisions get a ` (2)` suffix (`dedupe_name`), never an overwrite. Config entry **v3** (`async_migrate_entry`) injects `uid`/`source` into pre-existing recipes, preserving tombstones.

`config_flow.py`'s `_all_visible_recipes()` duplicates this two-layer merge (the OptionsFlow needs it without going through the coordinator) — change both together.

## LLM tools platform (`llm/`)

> Introduced 2026-07 for HA ≥ 2026.8 (core's new `llm` integration platform —
> the reason for the `2026.8.0.dev*` floor in `hacs.json`); see
> `tasks/2026-07-llm-platform-migration-spec.md` for the full design.

The 15 Assist tools (`grind_xbloom`/`calibrate_xbloom_grinder` added 2026-07-17,
mirroring the manual-grind/grinder-calibration coordinator methods above) live
in the **`llm/` platform package** — `catalog.py`
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

`_attr_has_entity_name = True` + `_attr_translation_key = "<key>"` → HA looks up `entity.<platform>.<key>.name` from `translations/<ha_ui_lang>.json` (falls back to `strings.json`).

For state-enum sensors, also populate `entity.<platform>.<key>.state.<value>`. For event entities with attribute enums, populate `entity.<platform>.<key>.state_attributes.event_type.state.<value>`. For a `select` with a fixed, non-recipe-derived fallback option (e.g. "No recipes configured"), also populate `entity.select.<key>.state.<value>` — easy to miss since most `select`/`sensor` options here are dynamic (recipe names), not translatable strings.

Devices get the same treatment, one level up — see the Device registry section above.

**A recurring bug shape**: a property/method that returns a fixed placeholder string as if it were a real value (`"none"`, `"unknown"`, `"No recipes configured"`) instead of Python `None` bypasses HA's own localization of `None`/the generic Unknown state and ships untranslated. Check new sensors/selects for this pattern. Also check `sensor.py`'s `SensorDeviceClass.ENUM` entities' `_attr_options` list any time you add a new possible state value — HA raises `ValueError` on `async_write_ha_state()` if the state isn't in that list (`tests/test_sensor_state_enum_registration.py` pins this for `XBloomStateSensor`).

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
invariants, event-type registration, sensor ENUM registration) and runs
without an HA instance — on a pre-2026.8 host the success-path tests skip;
inside the devcontainer everything runs. Everything BLE-facing is still
validated manually:

1. Starting the devcontainer.
2. Adding the integration via Settings → Devices & Services with a real BLE MAC.
3. Driving each entity (pour / grind / recipe / cancel) and watching `home-assistant.log` for the `SEND CMD` / `RECV CMD` lines.

**The devcontainer host needs real Bluetooth hardware reachable from its Docker daemon** — confirmed this does *not* exist on a Mac running the devcontainer via Apple's `container` CLI virtualization (`/sys/class/bluetooth`, D-Bus, BlueZ all absent in that VM; no USB/device-passthrough flag available). Every BLE-dependent config-flow step fails identically in that setup (`cannot_connect`) — not a MAC/config problem, and not fixable by Docker flags. A devcontainer host with an actual Bluetooth adapter (a native Linux box, or a Pi) is needed for step 2 to succeed. **Any change to BLE framing, connection management, or the command table must be flagged to the user as needing real-hardware verification before promotion to stable** — this dev environment cannot test it.

## Release workflow

This repo (and other `ha-*` HACS components, excluding `ha-app*`) ships on a two-track rolling draft release, maintained by release-drafter since `e3bf99b` (#28): a `rc` (prerelease) draft and a `stable` draft, both updated continuously as PRs merge to `main`.

1. Verify locally with the devcontainer (`scripts/develop`) before merging — see Testing above.
2. Once merged and the `rc` draft looks right, publish it as a prerelease from the GitHub Releases UI.
3. After the prerelease has been exercised with no issues, promote/publish the corresponding `stable` draft.

**`legacy/1.4.x` is a separate, temporary branch** (created 2026-07-15) for users whose HA can't yet meet the `v1.5.0` line's `2026.8.0.dev*` floor (the LLM tools platform's HA-version requirement). Branched from the commit right before the LLM-platform merge (floor `2026.4.0` there), it cherry-picks only the non-LLM fixes/features from `main` (never the LLM-platform commits themselves) and ships its own `v1.4.1-rc.N` prereleases via `gh release create --target legacy/1.4.x` (release-drafter only watches `main`, so these are cut manually). Not an ongoing parallel release line — no new work is developed there, only backports of already-`main`'d fixes for real-hardware testing before the 2026.8 beta ships; once it does, `legacy/1.4.x` users switch to tracking `main`'s `v1.5.0`+ releases and the branch can be retired.

## When in doubt

- Localization broken? Check hard rule #2/#3 above before anything else.
- Sensor stuck `unknown`? Check the BLE protocol checklist above, especially [[xbloom-machineinfo-reliability-and-padding]] and [[xbloom-raw-state-heartbeat-vs-cmd-tagged]].
- Sensor shows a raw untranslated word instead of localized Unknown? See "A recurring bug shape" in Entity translation flow.
- Tea recipe doing nothing, or steeps flattening into one pour? Tea must go through `brewing._async_brew_tea` (8022 → 8102 → 8104 → 4513 → 4512) — `8004` does not trigger tea mode at all. See `docs/en/protocol.md` and `docs/en/brewing-notes.md`.
- `sensor.state` looks wrong specifically during/right after a real grind? See [[xbloom-raw-state-heartbeat-vs-cmd-tagged]] before assuming a new bug.
- Adding a new entity? Update `strings.json` AND every file under `translations/`. Add an `icons.json` entry. Don't set `_attr_name` or `_attr_icon` on the class.
- Adding a new **device** (not entity)? Same idea, one level up — see the Device registry section.
- Adding a new BLE command or event type? Check `docs/en/protocol.md`'s command table first (status: Active/Telemetry/Present-unconfirmed) — don't assume behavior from a command's name alone. New event types need `event.py` + all 3 translation files, see [[xbloom-tea-steep-events]].
- A protocol claim from a third-party capture repo conflicts with this integration's behavior? Decompile `xbloom_coffee_release.apk` directly rather than trusting either source on priors — see [[xbloom-40518-and-8104-third-party-claims-refuted]] and [[xbloom-full-command-table-androguard-sweep]] for the established methodology.
