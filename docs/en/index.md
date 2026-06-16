# XBloom Coffee Machine — Home Assistant Integration

> Source of truth — see [한국어](../ko/index.md) for the Korean translation (may lag).

Local Bluetooth control of an [XBloom Studio](https://xbloom.com/) coffee machine from Home Assistant. Pour, grind, run saved recipes, expose the brewer to Assist (LLM) — all without the cloud.

Built on two reverse-engineered BLE upstreams, both vendored:

- [`fhenwood/PyBloom`](https://github.com/fhenwood/PyBloom) at `custom_components/xbloom/src/xbloom/` — the class-based client library powering connection, status, grinder/brewer/scale components, and the coffee brew flow.
- [`brAzzi64/xbloom-ble`](https://github.com/brAzzi64/xbloom-ble) at `custom_components/xbloom/src/xbloom-ble/` — HCI-snoop-confirmed protocol decode (`PROTOCOL.md`) that the tea recipe flow in `brewing.py` cherry-picks from.

Huge thanks to Frederic, the PyBloom contributors, and Bruno Azzinnari for the protocol work that makes this integration possible.

## Features

- **Manual control** — pour with custom temperature/volume, grind with custom size/RPM, **tare** the scale, vibrate the tray.
- **Recipes — three layers**:
  1. **10 bundled defaults** ship with the integration (`default_recipes.py`) — light / medium-light / dark roast hot+iced, plus hibiscus / black / green / iced-hibiscus tea. Visible immediately on install.
  2. **`configuration.yaml`** recipes (the legacy path) override defaults by name.
  3. **OptionsFlow CRUD** lets you add / edit / delete recipes from the UI without restarting HA. Overrides defaults and YAML by name. Settings → Devices & Services → XBloom → ⋯ → **Configure**.
- **Tea recipes** (`cup_type: tea`) — every steep encoded as a pour with `pausing` = idle seconds between steeps; the firmware drives pour → soak → siphon-drain internally.
- **Selected-recipe inspection** — the recipe select entity exposes the full recipe (pours, bypass, temperatures, etc.) under its `recipe` attribute. View at Developer Tools → States → `select.xbloom_recipe`, or in templates via `{{ state_attr('select.xbloom_recipe', 'recipe').pours }}`.
- **Easy Mode slot writing** — push the currently-selected recipe to the machine's onboard slot A / B / C (Auto/Easy Mode buttons on the device).
- **Live telemetry** — brewer temperature, scale weight, water-level state, current brew step.
- **Event entities** — error events (water shortage, no beans, abnormal dose, abnormal gear) and notifications (grinding started/complete, brewing started, pour complete, bloom, paused, recipe complete, tea soaking).
- **LLM API** — exposes pour, recipe execution, recipe listing, and status to Home Assistant Assist with safety confirmations (beans, filter, cup-on-scale).
- **Korean and English** UI translations.

## Installation (HACS)

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

Three layers, in increasing precedence:

| Layer | Where | Mutable from | Notes |
| --- | --- | --- | --- |
| Defaults | `custom_components/xbloom/default_recipes.py` | code only | 10 bundled recipes. Read-only at runtime. |
| YAML | `configuration.yaml` `xbloom: recipes:` | edit + restart HA | Same shape as below. Overrides defaults by name. |
| OptionsFlow | `entry.options[CONF_RECIPES]` | HA UI | Add / edit / delete. Overrides everything by name. |

To override a bundled default, just add a same-named recipe in YAML or via the OptionsFlow.

### YAML recipe shape

```yaml
xbloom:
  recipes:
    - name: Morning V60
      cup_type: omni_dripper      # x_pod | omni_dripper | other | tea
      grind_size: 35
      bean_weight: 18
      total_water: 250
      bypass_volume: 0            # 0 disables the bypass
      bypass_temperature: 0
      pours:
        - volume: 50
          temperature: 93
          flow_rate: 3.0
          pausing: 30
          pattern: spiral         # center | circular | spiral
          vibration: after        # none | before | after | both
        - volume: 200
          temperature: 92
          flow_rate: 3.0
          pausing: 0
          pattern: spiral
    - name: Sencha
      cup_type: tea               # grind_size + bean_weight must be 0
      grind_size: 0
      bean_weight: 0
      pours:
        - volume: 120
          temperature: 80
          pausing: 60             # idle seconds before the next steep
        - volume: 120
          temperature: 80
          pausing: 0
```

For tea recipes, each pour represents one steep. The xBloom Omni Tea Brewer's siphon triggers at ~120 ml (leaf-volume dependent) — `pausing` is *idle time between steeps*, not actual steep time. See [`brewing-notes.md`](./brewing-notes.md) for the full siphon-mechanics explanation.

See the **YAML recipe shape** above for the field-by-field reference.

### Recipe management via UI (OptionsFlow)

Settings → Devices & Services → XBloom → ⋯ → **Configure** → menu:

- **Settings** — telemetry interval, idle disconnect timeout.
- **Add a recipe** — paste a YAML block; validated against the schema; saved into options; integration auto-reloads.
- **Edit a recipe** — pick from UI-managed recipes (defaults / YAML are read-only here); edit the pre-filled YAML; renaming via `name:` is allowed.
- **Delete a recipe** — pick from UI-managed recipes and confirm.

Bundled defaults and YAML recipes don't appear in the Edit/Delete dropdowns by design — those are sourced from code or files outside HA's UI ownership. To remove a default, override it by adding a same-named recipe via OptionsFlow.

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

- **Tea → coffee grinding fails**: after any tea brew, the next coffee brew skips the grinder phase (pour still works, but no beans are ground). No documented BLE command restores the grinder once the firmware enters the tea state — see [`brewing-notes.md`](./brewing-notes.md#known-limitation--grinding-fails-after-a-tea-brew). **Workaround:** power-cycle the machine between a tea brew and the next coffee brew.
- **Tea siphon is flash-extract, not long-soak**: the xBloom Omni Tea Brewer drains at ~120 ml regardless of `pausing`. Recipes designed for long submersion (matcha, gong-fu styles with sub-minute steeps that need water in the brewer) won't behave as expected. Detail in [`brewing-notes.md`](./brewing-notes.md#xbloom-omni-tea-brewer--siphon-mechanics).
- **MachineInfo on some firmwares**: certain XBloom firmware revisions do not push the `RD_MachineInfo` BLE notification, so the Model / Serial / Firmware sensors may stay `unknown`. The water-level binary sensor falls back to event-driven detection (RD_ErrorLackOfWater) on those firmwares.
- **Manual cup detection**: the scale auto-tares any weight present at power-on, so a cup placed before boot reads as 0 g. The LLM `execute_xbloom_recipe` tool will ask for explicit confirmation when this happens.
- **Recipe water source**: the manual pour entity respects the water-source select (tank vs. direct plumbed). Recipe execution does not — the firmware controls its own pour sequence internally.

## Development

See `AGENTS.md` for the architecture and coding conventions used in this repo. For BLE-level details of the brew sequences, firmware behavior, known limitations (tea → coffee grinding, etc.), and Tea Brewer siphon mechanics see [`brewing-notes.md`](./brewing-notes.md).

A devcontainer is provided for testing the integration against a real Home Assistant install. Open the folder in VS Code with the Dev Containers extension and run:

```bash
scripts/develop
```

HA binds the standard port 8123 inside the container. The container's hostname is set to `ha-xbloom-dev` so it's distinguishable from any production HA instance you run on the host network. VS Code forwards 8123 to the host (and auto-picks a different host port if 8123 is already taken there).

## License

[MIT](LICENSE) — preserves both vendored upstream copyrights (`fhenwood/PyBloom` at `src/xbloom/`, `brAzzi64/xbloom-ble` at `src/xbloom-ble/`, each carrying its own MIT `LICENSE` file) and adds the integration's own copyright line.
