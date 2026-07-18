# XBloom Coffee Machine — Home Assistant Integration

> Source of truth — see [한국어](../ko/index.md) for the Korean translation (may lag).

Local Bluetooth control of an [XBloom Studio](https://xbloom.com/) coffee machine from Home Assistant. Pour, grind, run saved recipes, expose the brewer to Assist (LLM) — all without the cloud.

Built on the protocol work of two reverse-engineered BLE upstreams, kept in the repo as unmodified reference/attribution copies (see [ADR-001](../../adr/001-clean-room-reimplementation-of-xbloom-ble.md) — the BLE client itself is a clean-room native implementation, not a runtime dependency on either):

- [`fhenwood/PyBloom`](https://github.com/fhenwood/PyBloom) at `custom_components/xbloom/src/xbloom/`.
- [`brAzzi64/xbloom-ble`](https://github.com/brAzzi64/xbloom-ble) at `custom_components/xbloom/src/xbloom-ble/`.

Huge thanks to Frederic, the PyBloom contributors, and Bruno Azzinnari for the protocol work that makes this integration possible.

## Features

- **Local recipes are the source of truth** — every recipe gets a stable local `uid` and lives in HA; that's what the Recipe dropdown shows and brews. Seeded once at install (from your cloud account if linked, else XBloom's official public recipes), then no background sync — manage it from the HA UI, the recipe services, or `configuration.yaml`.
- **Cross-identifier addressing** — every service/tool takes one `recipe` field: local uid, cloud table id, share URL/id, or exact name.
- **Manual control** — pour with custom temperature/volume/flow rate/pour pattern, grind with custom size/RPM, **tare** the scale, vibrate the tray.
- **Two-stage grind/pour/execute-recipe buttons** — the first press queues the operation on the machine (enter grinder/pour mode, or queue the selected recipe) without starting it, giving you time to place a cup/dripper; a second press on the same button sends the actual go command. `sensor.xbloom_state` shows `armed_grind`/`armed_pour`/`armed_recipe` while waiting for the second press; the cancel button backs out of an armed-but-unconfirmed operation. HA-button-only — the `execute_recipe`/`execute_tea_recipe` services and every LLM tool still brew in one call.
- **Per-brew overrides** — brew a recipe with adjusted grind, RPM, dose, ratio, cup type, or bypass without editing it (dose/ratio rescales the pours proportionally); selecting a recipe also syncs the Grind Size / RPM sliders to it.
- **Tea recipes** (`cup_type: tea`) — each steep is a pour with `pausing` = soak seconds; the firmware handles pour → soak → siphon-drain internally. See [`brewing-notes.md`](./brewing-notes.md) for the siphon mechanics.
- **Selected-recipe inspection** — the recipe select entity exposes the full recipe (pours, bypass, temperatures, etc.) under its `recipe` attribute. View at Developer Tools → States → `select.xbloom_recipe`, or in templates via `{{ state_attr('select.xbloom_recipe', 'recipe').pours }}`.
- **Easy Mode slot writing** — push any recipe to onboard slot A/B/C via the slot buttons or the `write_recipe_to_easy_slot` service (auto-imports a share URL that isn't local yet); read-only sensor entities show what's stored in each slot.
- **Cloud as an import/export boundary** — pull a shared recipe in (`cloud_import_recipe`, no account needed), push a local one out for a share link (`cloud_export_recipe`), or browse XBloom's public community hub (`cloud_search_collective_recipes`). An account is optional, only needed for export. See [Recipe services](#recipe-services) below.
- **Live telemetry** — brewer temperature, scale weight, water-level state, current brew step.
- **Event entities** — errors (water shortage, no beans, abnormal dose/gear) and notifications (grinding/brewing/pour/bloom/pause/complete/tea soaking).
- **LLM API** — status, recipe CRUD, brewing, slot writing, import/export, and hub search exposed to voice/chat agents through the opt-in XBloom LLM API (see [Assist / LLM tools](#assist--llm-tools)) with safety confirmations (beans, dripper, filter, cup-on-scale, delete) — skipped entirely for no-grind recipes (e.g. a water-only pour).
- **Korean and English** UI translations.

## Installation (HACS)

> **Requires Home Assistant 2026.8.0 or newer** (until the 2026.8 beta ships,
> that means a dev nightly ≥ `2026.8.0.dev202607110310`). The Assist/LLM
> tools ride on HA's new `llm` tools platform; on older versions the LLM API
> fails at conversation time.

1. In HACS → Integrations → ⋮ → **Custom repositories**, add this repo URL with category **Integration**.
2. Install **XBloom Coffee Machine**.
3. Restart Home Assistant.
4. Settings → Devices & Services → **Add integration** → search "XBloom".
5. Enter the device's BLE MAC address (`xbloom scan` from a terminal, or check XBloom Studio).

## Manual installation

Copy `custom_components/xbloom/` into your HA config's `custom_components/` folder and restart.

## Configuration

The initial config flow handles MAC address + telemetry interval + idle disconnect timeout. Everything else is done through the Options flow (Settings → Devices & Services → XBloom → ⋯ → **Configure**).

### Recipes

On first install the recipe store is seeded **once**: a small bundled set is written immediately (so the dropdown is never empty), then a background task fetches your XBloom cloud account's recipes (if linked in the config flow's account step) or XBloom's official public recipes otherwise, skipping any name that already exists. A failed fetch (e.g. no internet at first boot) retries on the next restart. Linking an account **later** seeds its recipes once at that point. No background sync after that — the local store is yours.

Recipes can also be defined in `configuration.yaml` — lower priority than the local store (a same-named store recipe wins; deleting a YAML recipe from the UI hides it):

```yaml
xbloom:
  recipes:
    - name: Morning V60
      cup_type: omni_dripper      # x_pod | omni_dripper | other | tea
      grind_size: 35
      dose_g: 18
      ratio: 13.9                 # total water = dose_g * ratio
      bypass_volume: 0            # 0 disables the bypass
      bypass_temperature: 0
      pours:
        - volume_ml: 50
          temperature_c: 93
          flow_rate: 3.0
          pause_seconds: 30
          pattern: spiral         # center | circular | spiral
          vibration: after        # none | before | after | both
        - volume_ml: 200
          temperature_c: 92
          flow_rate: 3.0
          pause_seconds: 0
          pattern: spiral
    - name: Sencha
      cup_type: tea               # dose_g must be 0; ratio is meaningless for tea
      grind_size: 0
      dose_g: 0
      pours:
        - volume_ml: 120
          temperature_c: 80
          pause_seconds: 60       # soak time before the next steep
        - volume_ml: 120
          temperature_c: 80
          pause_seconds: 0
```

For tea recipes, each pour represents one steep. `pause_seconds` is the real soak time (water held in the brewer), as long as the per-steep volume stays under the siphon threshold, which the integration enforces automatically — see [`brewing-notes.md`](./brewing-notes.md) for the full siphon-mechanics explanation.

### Recipe management via UI

Settings → Devices & Services → XBloom → ⋯ → **Configure** → **Add a recipe** / **Edit a recipe** / **Delete a recipe**. Deleting is local-only and immediate; a copy on your cloud account is never touched. YAML recipes appear in Edit/Delete too — editing one saves the edit as a local override (the YAML file is never written to); deleting one tombstones it (add a same-named recipe to restore it).

### Assist / LLM tools

The LLM tools are **opt-in per conversation agent**: in your agent's settings
(Settings → Voice assistants → *your assistant* → conversation agent options)
enable the **"XBloom Coffee Machine (MAC)"** API under the LLM API selection.
The tools never ride along in the plain Assist API — an agent without the
XBloom API selected sees none of them, and the tool code isn't even loaded
until the API is first used. One API is registered per machine, so
multi-machine households pick per agent.

With the [MCP Server integration](https://www.home-assistant.io/integrations/mcp_server/)
set up, the same tools are also served over MCP at
`/api/mcp/xbloom_coffee_<entry_id>` (admin access token required).

### Per-brew overrides

A saved recipe can be run with adjustments for a single brew without editing it. Choosing a recipe in the **Recipe** select syncs the **Grind Size** / **Grinder RPM** sliders to its values; whatever they hold at brew time is used. Tea and no-grind recipes ignore grind/RPM.

Every top-level scalar can be overridden per brew: `grind_size`, `rpm`, `dose_g`, `ratio`, `cup_type`, `bypass_volume`, `bypass_temperature`. A `dose_g`/`ratio` override rescales the pour volumes proportionally (sum of pours + bypass = dose × ratio). Bypass can be added even to recipes that have none; tea recipes never bypass or grind.

```yaml
service: xbloom.execute_recipe
target:
  device_id: <your xbloom device>   # optional if you only have one machine
data:
  recipe: Morning V60   # uid / cloud id / share URL / name — optional, defaults to the selected recipe
  grind_size: 42
  rpm: 90
  dose_g: 20            # pours rescale to keep total water = dose × ratio
  bypass_volume: 50
  bypass_temperature: 92
```

Through Assist (LLM), `get_xbloom_recipe` returns a recipe's full detail (grind, RPM, bypass, and each pour's volume / flow rate / pattern) and `execute_xbloom_recipe` accepts the same scalar overrides plus per-pour `pour_overrides` (volume / flow rate / pattern keyed by 0-based `pour_index`), so an agent can tune individual pours on request.

## Recipe services

Nine services cover the whole recipe surface (Developer Tools → Actions). Wherever a service takes a `recipe`, it accepts the recipe's local **uid**, **cloud table id**, **share URL/id**, or exact **name** — `list_recipes` returns the uids.

| Service | Does |
| --- | --- |
| `list_recipes` | List every local recipe (uid, source, cup type, dose, grind, pour count, and any cloud id / share URL), optionally filtered by a name query. |
| `create_recipe` | Create a new local recipe from inline `recipe_yaml`. Returns its `uid`. Nothing is uploaded. |
| `edit_recipe` | Change one or more fields of a local recipe; omitted fields keep their values. Pointing it at a share URL that isn't local yet imports a copy first and edits that. |
| `delete_recipe` | Delete a local recipe — the dropdown updates immediately. A copy on your cloud account is **not** touched (cloud deletion happens in the official app). |
| `execute_recipe` | Brew a recipe, with optional per-brew scalar overrides (see above). |
| `write_recipe_to_easy_slot` | Store a recipe on onboard Easy Mode slot A/B/C. A share URL that isn't local yet is auto-imported first. |
| `cloud_import_recipe` | Fetch a recipe from a `share-h5.xbloom.com` link, a `collective.xbloom.com/recipe/{id}` community-hub link, or a share id, and save it locally (with a new uid). No account needed. |
| `cloud_export_recipe` | Push a local recipe to **your** XBloom cloud account and return its cloud `id`, share `link`, and the recipe. Re-exporting the same recipe updates the same cloud entry (the link stays stable). Without an account configured, nothing is uploaded and only the recipe is returned. |
| `cloud_search_collective_recipes` | Search XBloom's **public** community recipe hub (collective.xbloom.com) — no account needed. Filter by keyword, coffee/tea, official/user, and multi-select machine / cup type / origin / varietal / process / roast / flavor facets, with sorting. |

```yaml
service: xbloom.cloud_import_recipe
data:
  share_url: "https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D"
```

The collective-search facet dropdowns are a snapshot of the hub's category codes. If XBloom adds a category the dropdown doesn't know yet, type its numeric code directly (the fields accept custom values) — and please [open an issue](https://github.com/saya6k/hacs-xbloom/issues) with the code so it can be added to the snapshot and translated in the next release.

**Cloud account (optional)** — only `cloud_export_recipe` needs one. Enter your XBloom app email/password in the config flow's "XBloom Cloud Account" step during initial setup, or add/update/remove it later via Settings → Devices & Services → XBloom → ⋯ → **Configure** → **Cloud account**. Signed in with Apple and have no XBloom password? Use XBloom's own "forgot password" flow (with the email Apple relays, visible in the app's account settings) to set one first.

Through Assist (LLM), the same surface is exposed as tools: `list_xbloom_recipes`, `get_xbloom_recipe`, `create_xbloom_recipe`, `edit_xbloom_recipe`, `delete_xbloom_recipe` (asks for explicit confirmation before deleting), `execute_xbloom_recipe`, `write_xbloom_easy_slot`, `import_xbloom_cloud_recipe`, `export_xbloom_recipe`, and `search_xbloom_collective_recipes`.

## Grind size reference (XBloom Studio scale, 0–80)

| Brew method            | Range  |
| ---------------------- | ------ |
| Turkish                | 0–3    |
| Espresso               | 0–18   |
| Moka Pot               | 17–44  |
| Filter Coffee Machine  | 12–66  |
| Aeropress              | 13–71  |
| Siphon                 | 18–57  |
| V60                    | 21–47  |
| Pour Over              | 22–68  |
| Steep-and-release      | 25–59  |
| Cupping                | 26–61  |
| French Press           | 47–80  |
| Cold Brew              | 58–80  |
| Cold Drip              | 59–80  |

## Known limitations

- **XBloom Original is not supported**: this integration only talks to XBloom **Studio** over Bluetooth LE (see `manifest.json`'s `bluetooth` matcher) — Original uses an entirely different Wi-Fi protocol, and the maintainer has no Original unit to test. The cloud API also hardcodes `adaptedModel: 1` (Studio), so the account recipe seed and `cloud_export_recipe` are unverified for an Original-only account.
- **MachineInfo on some firmwares**: certain firmware revisions never push `RD_MachineInfo`, so the Model / Serial / Firmware sensors may stay `unknown`. The water-level binary sensor falls back to event-driven detection on those firmwares.
- **Manual cup detection**: the scale auto-tares any weight present at power-on, so a cup placed before boot reads as 0 g — the LLM `execute_xbloom_recipe` tool asks for explicit confirmation when this happens.
- **Recipe water source**: the manual pour entity respects the water source configured under Settings → Devices & Services → XBloom → Configure → Settings (tank vs. direct plumbed); recipe execution does not — the firmware runs its own pour sequence internally.
- **Tea soak timing is approximately calibrated**: the wait between steeps is scaled from the recipe's `pausing` seconds using a factor derived from a couple of stopwatch measurements — see [`brewing-notes.md`](./brewing-notes.md) for details if you need tighter timing.

## Development

See `AGENTS.md` for the architecture and coding conventions used in this repo. For BLE-level details of the brew sequences, firmware behavior, and Tea Brewer siphon mechanics see [`brewing-notes.md`](./brewing-notes.md); for the full packet framing and command-id reference see [`protocol.md`](./protocol.md). See [ADR-001](../../adr/001-clean-room-reimplementation-of-xbloom-ble.md) for why the BLE client is a clean-room native implementation rather than a vendored-and-patched one.

A devcontainer is provided for testing the integration against a real Home Assistant install. Its base image is the official HA **dev-nightly** Docker image (pinned in `.devcontainer/devcontainer.json` to the same version as `hacs.json`'s floor), so HA core and every runtime dependency come baked in — `scripts/setup` only installs dev tools. Open the folder in VS Code with the Dev Containers extension and run:

```bash
scripts/develop
```

HA binds the standard port 8123 inside the container. The container's hostname is set to `hacs-xbloom-dev` so it's distinguishable from any production HA instance you run on the host network. VS Code forwards 8123 to the host (and auto-picks a different host port if 8123 is already taken there).

## License

[MIT](../../LICENSE) — preserves both vendored upstream copyrights (`fhenwood/PyBloom` at `src/xbloom/`, `brAzzi64/xbloom-ble` at `src/xbloom-ble/`, each carrying its own MIT `LICENSE` file) and adds the integration's own copyright line.
