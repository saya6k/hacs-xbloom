# XBloom Coffee Machine — Home Assistant Integration

[![Built with Claude Code](https://img.shields.io/badge/Built%20with%20Claude%20Code-D97757?style=for-the-badge&logo=claude&logoColor=white)](https://claude.ai/code)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/)
[![Bluetooth](https://img.shields.io/badge/Bluetooth-0082FC?style=for-the-badge&logo=bluetooth&logoColor=white)](https://www.bluetooth.com/)
[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Shell](https://img.shields.io/badge/Shell-4EAA25?style=for-the-badge&logo=gnubash&logoColor=white)](https://www.gnu.org/software/bash/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/saya6k)

Local Bluetooth control of an [XBloom Studio](https://xbloom.com/) coffee machine from Home Assistant. Pour, grind, run saved recipes, expose the brewer to Assist (LLM) — all without the cloud.

Built on two reverse-engineered BLE upstreams, both vendored:

- [`fhenwood/PyBloom`](https://github.com/fhenwood/PyBloom) at `custom_components/xbloom/src/xbloom/` — the class-based client library powering connection, status, grinder/brewer/scale components, and the coffee brew flow.
- [`brAzzi64/xbloom-ble`](https://github.com/brAzzi64/xbloom-ble) at `custom_components/xbloom/src/xbloom-ble/` — HCI-snoop-confirmed protocol decode (`PROTOCOL.md`) that the tea recipe flow in `brewing.py` cherry-picks from.

Huge thanks to Frederic, the PyBloom contributors, and Bruno Azzinnari for the protocol work that makes this integration possible.

## Features

- **Saved recipes** — edit, add, or delete recipes directly from the HA UI (Settings → Devices & Services → XBloom → Configure). Built-in default recipes (Korean coffee and tea) are editable and deletable too — deleted defaults can be re-added anytime. Recipes can also be defined in `configuration.yaml`. Single-button execution from the dashboard.
- **Manual control** — pour with custom temperature/volume/flow rate/pour pattern, grind with custom size/RPM, **tare** the scale, vibrate the tray.
- **Per-brew overrides** — selecting a recipe syncs the Grind Size / RPM sliders to it; tweak them (or call the `xbloom.execute_recipe` service / ask Assist) to brew the saved recipe with adjusted grind, RPM, or bypass without editing the recipe. Bypass is recipe-scoped (no slider) — override it per brew via the service or Assist. Tea / no-grind recipes are left untouched.
- **Tea recipes** (`cup_type: tea`) — every steep encoded as a pour with `pausing` = soak seconds; the firmware drives pour → soak → siphon-drain internally.
- **Easy Mode slot writing** — push the currently-selected recipe to the machine's onboard slot A / B / C (Auto/Easy Mode buttons on the device).
- **Live telemetry** — brewer temperature, scale weight, water-level state, current brew step.
- **Event entities** — error events (water shortage, no beans, abnormal dose, abnormal gear) and notifications (grinding started/complete, brewing started, pour complete, bloom, paused, recipe complete, tea soaking).
- **LLM API** — exposes pour, recipe execution, recipe listing, and status to Home Assistant Assist with safety confirmations (beans, filter, cup-on-scale).
- **Korean and English** UI translations.

## Installation (HACS)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=saya6k&repository=ha-xbloom&category=integration)

1. In HACS → Integrations → ⋮ → **Custom repositories**, add this repo URL with category **Integration**.
2. Install **XBloom Coffee Machine**.
3. Restart Home Assistant.
4. Settings → Devices & Services → **Add integration** → search "XBloom".
5. Enter the device's BLE MAC address (`xbloom scan` from a terminal, or check XBloom Studio).

## Manual installation

Copy `custom_components/xbloom/` into your HA config's `custom_components/` folder and restart.

## Configuration

The config flow handles MAC + telemetry interval + idle disconnect timeout.

Recipes can be managed from the HA UI: Settings → Devices & Services → XBloom → **Configure**. Use **Add a recipe** / **Edit a recipe** / **Delete a recipe** to manage all recipes, including the built-in defaults (Korean coffee and tea). Edits to a default recipe are saved as a per-machine override — the original stays intact in the integration. Deleting a default hides it; add a same-named recipe to restore it.

Recipes can also be defined in `configuration.yaml` (lowest priority — UI recipes win by name):

```yaml
xbloom:
  recipes:
    morning_v60:
      name: Morning V60
      cup_type: omni_dripper
      grind_size: 35
      bean_weight: 18
      pours:
        - volume: 50
          temperature: 93
          flow_rate: 3.0
          pausing: 30
        - volume: 200
          temperature: 92
          flow_rate: 3.0
          pausing: 0
    sencha:
      name: Sencha Tea
      cup_type: tea
      pours:
        - volume: 150
          temperature: 80
          pausing: 60
        - volume: 150
          temperature: 80
          pausing: 90
```

For tea recipes, each pour represents one steep cycle: `volume` is the steep water, `temperature` is the water temperature, `pausing` is the soak time in seconds. The machine handles the siphon drain automatically.

### Per-brew overrides

A saved recipe can be run with adjustments that apply to a single brew without editing the recipe. Choosing a recipe in the **Recipe** select syncs the **Grind Size** and **Grinder RPM** number entities to that recipe's values; whatever those sliders hold at brew time is what gets used. Tea and no-grind recipes ignore the grind/RPM overrides (tea never grinds).

Bypass (extra dilution water added after the pours) is a recipe-scoped parameter rather than a live slider — override it per brew via the service or Assist below. Bypass can be added even to recipes that have none; tea recipes never bypass.

These overrides are available via the `xbloom.execute_recipe` service:

```yaml
service: xbloom.execute_recipe
target:
  device_id: <your xbloom device>   # optional if you only have one machine
data:
  recipe_name: Morning V60          # optional — defaults to the selected recipe
  grind_size: 42
  rpm: 90
  bypass_volume: 50
  bypass_temperature: 92
```

Through Assist (LLM), `get_xbloom_recipe` returns a recipe's full detail (grind, RPM, bypass, and each pour's volume / flow rate / pattern) and `execute_xbloom_recipe` accepts optional `grind_size`, `rpm`, `bypass_volume`, `bypass_temperature`, and per-pour `pour_overrides` (volume / flow rate / pattern keyed by 0-based `pour_index`), so an agent can tune individual pours on request.

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

- **MachineInfo on some firmwares**: certain XBloom firmware revisions do not push the `RD_MachineInfo` BLE notification, so the Model / Serial / Firmware sensors may stay `unknown`. The water-level binary sensor falls back to event-driven detection (RD_ErrorLackOfWater) on those firmwares.
- **Manual cup detection**: the scale auto-tares any weight present at power-on, so a cup placed before boot reads as 0 g. The LLM `execute_xbloom_recipe` tool will ask for explicit confirmation when this happens.
- **Recipe water source**: the manual pour entity respects the water-source select (tank vs. direct plumbed). Recipe execution does not — the firmware controls its own pour sequence internally.

## Development

See `AGENTS.md` for the architecture and coding conventions used in this repo.

A devcontainer is provided for testing the integration against a real Home Assistant install. Open the folder in VS Code with the Dev Containers extension and run:

```bash
scripts/develop
```

HA binds the standard port 8123 inside the container. The container's hostname is set to `ha-xbloom-dev` so it's distinguishable from any production HA instance you run on the host network. VS Code forwards 8123 to the host (and auto-picks a different host port if 8123 is already taken there).

## License

[MIT](LICENSE) — preserves both vendored upstream copyrights (`fhenwood/PyBloom` at `src/xbloom/`, `brAzzi64/xbloom-ble` at `src/xbloom-ble/`, each carrying its own MIT `LICENSE` file) and adds the integration's own copyright line.
