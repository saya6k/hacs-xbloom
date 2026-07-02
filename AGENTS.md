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

## When in doubt

- Localization broken? Check (2) above before anything else.
- Sensor stuck `unknown`? Check the firmware-quirks section.
- Tea recipe doing nothing? It must go through `brewing.async_execute_recipe` (8022 → 8102 → 8104 → 8004 → 8002), not the firmware's `4512`/`4513` constants — see the firmware-quirks entry.
- Adding a new entity? Update `strings.json` AND every file under `translations/`. Add an `icons.json` entry. Don't set `_attr_name` or `_attr_icon` on the class.
