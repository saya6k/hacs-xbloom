# Repository agent instructions

> `CLAUDE.md` and `GEMINI.md` are local symlinks to this file (gitignored) — edit `AGENTS.md`.

Agent assets live under `.agents/` (the source of truth): `skills/`, `workflows/` (commands), `agents/`, and `memory/` (Claude's per-project memory). `.claude/` is a real directory: its `settings.json` is Claude-specific and tracked; its per-item symlinks into `.agents/` (`skills`, `commands` → `workflows`, `agents`) and `settings.local.json` are local-only, as are the `CLAUDE.md`/`GEMINI.md` → `AGENTS.md` symlinks and `.gemini` → `.agents`.

This file briefs Claude / GPT / other coding agents on the conventions and load-bearing facts of `ha_xbloom`. Read this before making changes. It's deliberately a *current-state* reference, not a lab notebook — the forensic history behind non-obvious facts here (hardware reports, decompile trails, wrong turns and their corrections) lives in Claude's project memory (`.agents/memory/` / the auto-memory system), cross-referenced below by topic. Read a linked memory entry when you need the "why," not just the "what."

## Repository layout

```
ha_xbloom/
├── custom_components/xbloom/      ← the HA integration (edit this)
│   ├── llm/                       ← LLM tools platform (entry point + catalog + tools)
│   ├── translations/              ← per-locale entity/config UI strings
│   ├── strings.json               ← English source-of-truth for translations
│   ├── icons.json                 ← entity icons keyed by translation_key
│   ├── coordinator/               ← BLE lifecycle + state aggregation (single source of truth for entities); connection/state/recipes/advanced_settings/operations mixins + constants
│   ├── ble/                       ← native BLE client: constants, framing, models, connection, client, components
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

1. **The BLE client is a clean-room native implementation; the reverse-engineered upstreams are no longer vendored.** This integration's BLE client, framing, and command table live in `custom_components/xbloom/ble/` (`constants.py`/`framing.py`/`models.py`/`connection.py`/`client.py`/`components.py`/`scanner.py`) — built from this integration's own hardware findings and `docs/en/protocol.md`, not by copying or patching any upstream. The two upstreams it originally replaced (`fhenwood/PyBloom`, `brAzzi64/xbloom-ble`, both MIT) were once vendored under `custom_components/xbloom/src/` as byte-for-byte reference copies; per [ADR-001](adr/001-clean-room-reimplementation-of-xbloom-ble.md) (amended 2026-07-18) they have been **removed** and are now credited by link only (see README). No runtime or test code imports `xbloom.*` anymore — the former parity tests were converted to golden-vector tests (frozen wire bytes captured from the vendored oracle before removal; see `tests/test_ble_framing.py`). Do not re-add the vendored trees or reintroduce an `xbloom.*` import.
2. **Never set `_attr_name` on an entity that has `_attr_translation_key`.** HA's `Entity._name_internal` returns `_attr_name` first and never consults the translation map afterwards — this silently breaks every non-English UI. Pick one or the other.
3. **Translations live in two places.** `strings.json` is the English source of truth; `translations/<lang>.json` files are the localized copies. They must share the same key tree. Add a Korean entry to `translations/ko.json` whenever you add an English entry to `strings.json`.
4. **Icons live in `icons.json`, not in entity classes.** Don't set `_attr_icon` unless the icon is dynamic (e.g. `XBloomErrorSensor` flips based on string content). Static icons go in `icons.json` keyed by `entity.<platform>.<translation_key>.default` (with optional `.state` map).
5. **Coordinator is the single source of truth for state.** Entities read `self.coordinator.data[...]`; they do not call BLE methods directly. Side-effects (start brew, stop, etc.) go through `XBloomCoordinator.async_*` methods.
6. **XBloom Original (Wi-Fi) is out of scope.** This integration only supports XBloom Studio, connected over Bluetooth LE — see `manifest.json`'s `bluetooth` matcher. Original uses an entirely different Wi-Fi-based protocol this codebase doesn't implement, and the maintainer has no Original hardware to test against. Don't add Original-specific BLE/protocol code on spec; if a change would only make sense for Original, flag it instead.

## BLE protocol

**Full reference**: [`docs/en/protocol.md`](docs/en/protocol.md) (Korean: [`docs/ko/protocol.md`](docs/ko/protocol.md)) — packet framing, the complete command table (every `APP_*`/`RD_*` id this integration sends or handles, with status/payload/notes), and a summary of known transport quirks. Written fresh from this integration's own captures and APK decompilation (`androguard`/`jadx` against the official Android app) — treat it as the authoritative protocol reference (it superseded the upstream `xbloom-ble/PROTOCOL.md`, which is no longer vendored).

Packet layout: `header(0x58 0x02) | dev_id | type | cmd(2 LE) | len(4 LE) | const(0x01) | payload | crc(2)`. Type-2 commands (`11506`–`11512` family — mode switch, Easy Mode slots, pour radius/vibration amplitude) need `type_code=2` and a `0xC2` response marker instead of the usual `0xC1`, plus ≥0.8s spacing between back-to-back type-2 sends. The `8100` MTU handshake gates every other command.

`XBloomClient.send_and_wait(cmd, ..., timeout=ACK_TIMEOUT_S)` is the ACK-gated send primitive (added 2026-07-19): it resolves when the machine echoes the command id back, and raises `AckTimeout` otherwise. Multi-step sequences should chain on it rather than on fixed `asyncio.sleep()` — the official app's `AppBleManager.sendMessage` fires each next step from the previous one's success callback, which is what stops a sequence advancing past a step the machine never received. Defaults mirror the app: 1.5s (`DefaultTimeOut`), 3.0s for recipe sends. Measured ACK latency on real hardware is ~370-380ms. It does **not** retry — the sleep-retry policy stays one layer up in `coordinator._async_retry_while_sleeping`. Full migration plan: `tasks/2026-07-app-parity-spec.md` (local, untracked).

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
- Every user-triggered action (grind/pour/tare/calibrate/execute recipe/easy-slot write) must retry while the machine reports itself asleep, not just mode-switch — the official app's `DefaultTimeOut`/1.5s retry is universal, not mode-switch-specific → [[xbloom-wake-retry-universal-pattern]]
- `button.grind`/`button.pour`/`button.execute_recipe` are two-stage (arm then confirm on a 2nd press) — HA-button-only, services/LLM tools still act in one call → [[xbloom-two-stage-arm-confirm-buttons]]
- Cancelling an *armed* operation sends the quit command for that machine screen (`8012` grind / `8013` pour / `8017` recipe, `_ARMED_QUIT_COMMANDS`), never `8022`; and the local armed/active flags clear before the BLE send, regardless of whether it lands → [[xbloom-app-connection-lifecycle-and-page-quit]]

If a quirk you're debugging isn't in this checklist, it may not have been hit yet — check `docs/en/protocol.md`'s command table for the id's confirmed/unconfirmed status before assuming new behavior, and write a new memory entry (project-type) once you've root-caused it, rather than growing this file.

## BLE connection management

Connects through HA's Bluetooth integration (`bluetooth.async_ble_device_from_address` + `bleak_retry_connector.establish_connection`), not a bare `BleakClient` — required for HA proxy routing and retry/cache-clear handling. Auto-reconnects on an unexpected drop, with a backstop poll-driven retry and a notification-silence watchdog (`_BLE_SILENCE_TIMEOUT_S`, 15s) mirroring the official app's own connection supervisor. The backstop retry **backs off exponentially** (`_RECONNECT_BACKOFF_BASE_S` 5s, doubling to `_RECONNECT_BACKOFF_MAX_S` 300s) after consecutive failures, and only the first failure in a run logs at ERROR — without that, a machine that is merely off or out of range produced one connect attempt and one ERROR line on *every* poll tick indefinitely. The gate applies to the supervisor only: `_async_ensure_connected()` still connects on demand, so a user action never waits out a backoff. Outbound writes are chunked to ≤100 bytes, matching the official app's BLE write splitting. Full history (why each piece exists, what broke before the fix, what's still unverified) → [[xbloom-connection-race-and-supervisor]].

**The link is not held 24/7 (2026-07-19).** The official app never holds an unattended one — its supervise/reconnect loop is skipped entirely while backgrounded, and its own "heart check" answers a quiet link with `disconnect()`, not a reconnect. Matching that: the silence watchdog now only *drops* the link (`_async_drop_stale_link`, the supervisor's next 5s tick reconnects) and never fires while `client.is_sleeping()`; and after `session_timeout` seconds of inactivity (config-flow option "Idle disconnect timeout", 0 disables) the coordinator enters **idle standby** — `_async_enter_idle_standby()` drops the link and `_idle_disconnected` keeps the supervisor off until something wants the machine again. Every coordinator action therefore goes through `await self._async_ensure_connected()` (never the bare `_check_connected()`), which reconnects on demand. Full history → [[xbloom-app-connection-lifecycle-and-page-quit]].

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

`fetch_shared_recipe`'s identifier routing has had two real bugs in the collective-vs-share-h5 identifier-space distinction — a bare (non-URL) community recipe id is the latest → [[xbloom-collective-bare-id-import-bug]].

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

**The devcontainer host needs real Bluetooth hardware reachable from its Docker daemon** — confirmed this does *not* exist on a Mac running the devcontainer via Apple's `container` CLI virtualization (`/sys/class/bluetooth`, D-Bus, BlueZ all absent in that VM; no USB/device-passthrough flag available). Every BLE-dependent config-flow step fails identically in that setup (`cannot_connect`) — not a MAC/config problem, and not fixable by Docker flags. A devcontainer host with an actual Bluetooth adapter (a native Linux box, or a Pi) is needed for step 2 to succeed.

**But the BLE layer itself can be tested natively on the Mac** (established 2026-07-19 — the "this dev environment cannot test BLE" rule above is about the VM path only). `bleak`/CoreBluetooth reaches the machine directly: build a bare-`BleakClient` stand-in with the same interface as `HABleakConnection` and drive the integration's own `ble/` package with it, so the test exercises product code rather than a reimplementation. Protocol-level questions (is a command accepted? what does the ACK look like? what's the real telemetry cadence?) should be answered this way first — it takes minutes. Full-integration testing on macOS is still blocked by two things: CoreBluetooth identifies devices by per-host UUID, which `config_flow.py`'s `MAC_RE` rejects, and the local HA is far below the `2026.8.0.dev*` floor (not on PyPI). Anything that physically grinds, pours or heats needs the user's go-ahead before you send it. Full detail → [[xbloom-macos-native-ble-testing]].

**Any change to BLE framing, connection management, or the command table still needs real-hardware verification before promotion to stable** — but "verify it" now usually means running it natively here, not deferring to a prerelease.

## Release workflow

This repo (and other `ha-*` HACS components, excluding `ha-app*`) ships on a two-track rolling draft release, maintained by release-drafter since `e3bf99b` (#28): a `rc` (prerelease) draft and a `stable` draft, both updated continuously as PRs merge to `main`.

1. Verify locally with the devcontainer (`scripts/develop`) before merging — see Testing above.
2. Once merged and the `rc` draft looks right, publish it as a prerelease from the GitHub Releases UI.
3. After the prerelease has been exercised with no issues, promote/publish the corresponding `stable` draft.

**The `legacy/1.4.x` line is retired (2026-07-18).** It briefly existed (created 2026-07-15) as a temporary backport branch for users whose HA couldn't yet meet the `v1.5.0` line's `2026.8.0.dev*` floor, cutting its own `v1.4.1-rc.N` prereleases. That approach was dropped: the maintainer decided **not** to keep backporting and to support HA **2026.8+ only** going forward. The branch (local and `origin`) has been deleted — its already-published `v1.4.1-rc.N` release tags remain for anyone who installed them, but no further backports are cut and there is no parallel release line. All work ships from `main` on the `v1.5.0`+ track described above.

## When in doubt

- Localization broken? Check hard rule #2/#3 above before anything else.
- Sensor stuck `unknown`? Check the BLE protocol checklist above, especially [[xbloom-machineinfo-reliability-and-padding]] and [[xbloom-raw-state-heartbeat-vs-cmd-tagged]].
- Sensor shows a raw untranslated word instead of localized Unknown? See "A recurring bug shape" in Entity translation flow.
- Tea recipe doing nothing, or steeps flattening into one pour? Tea must go through `brewing._async_brew_tea` (8022 → 8102 → 8104 → 4513 → 4512) — `8004` does not trigger tea mode at all. Every step up to 4513 is ACK-gated (`send_and_wait`), so a chain that dies partway raises `AckTimeout` instead of silently reaching 4512. See `docs/en/protocol.md` and `docs/en/brewing-notes.md`.
- `sensor.state` looks wrong specifically during/right after a real grind? See [[xbloom-raw-state-heartbeat-vs-cmd-tagged]] before assuming a new bug.
- Adding a new entity? Update `strings.json` AND every file under `translations/`. Add an `icons.json` entry. Don't set `_attr_name` or `_attr_icon` on the class.
- Adding a new **device** (not entity)? Same idea, one level up — see the Device registry section.
- Adding a new BLE command or event type? Check `docs/en/protocol.md`'s command table first (status: Active/Telemetry/Present-unconfirmed) — don't assume behavior from a command's name alone. New event types need `event.py` + all 3 translation files, see [[xbloom-tea-steep-events]].
- A protocol claim from a third-party capture repo conflicts with this integration's behavior? Decompile `xbloom_coffee_release.apk` directly rather than trusting either source on priors — see [[xbloom-40518-and-8104-third-party-claims-refuted]] and [[xbloom-full-command-table-androguard-sweep]] for the established methodology.
- A service call targeting a specific machine (`config_entry_id`) silently matches nothing? `__init__.py`'s `_coordinators_for_call` treats it as a scalar, not a list — `ConfigEntrySelector` has no `multiple` option, so never iterate it. See [[xbloom-service-config-entry-targeting]].
