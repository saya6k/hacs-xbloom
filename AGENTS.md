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
  Independently cross-verified 2026-07-16 by static analysis of `cryptofishbug/xbloom-recipe-cli`'s
  `1.0` release asset (`xbloom-firmware-switcher-release_Compatibility.apk`, an unofficial Android
  BLE firmware flasher — inspected as a zip/dex string dump only, never installed/run): its
  `classes.dex` names this exact command `PACKET_8100` and logs `"send 8100 official MTU/session
  primer attempt"` / `"8100 ACK, session ready"` / `"OTA blocked: device did not answer 8100.
  Disconnect, power-cycle xBloom, then scan/connect again."` — same command id, same role, same
  recovery procedure, from a fully independent reverse-engineering effort. That app also revealed a
  follow-on `PACKET_8101` ("send 8101, wait official ACK, then ymodem") that puts the machine into
  YMODEM firmware-receive mode for OTA updates — undocumented here since flashing firmware is out of
  scope for this integration, but worth knowing the command exists if `8101` ever shows up in a
  capture. The same app bundles 4 firmware images for the "J15" board (`V12.0D.210/300/410/500`).
  Release notes for the 4 images imply pour-pattern (`spiral`) behavior has changed across firmware
  versions — no confirmed mapping of which build to which behavior, but a reason to suspect firmware
  drift before assuming a code regression if a pour-pattern bug appears on a machine whose firmware
  version is unknown. The 4 bundled builds' internal version strings turned out to be independently
  checkable two ways. First, xBloom's own support site (Zendesk "xBloom Studio Firmware Update
  Summary" section, https://tbdxsupport.zendesk.com/hc/en-us/sections/25914689676443, fetched
  2026-07-16 via its public Help Center API — the page itself 403s to a plain fetch) documents an
  official history of `V12.0D.122` (2024-07-12) → `V12.0D.210` (2024-12-24, **introduces Auto/Easy
  Mode** — cmd `11510`/`11511`/`11512` don't exist before this) → `V12.0D.300` (2025-03-20,
  **introduces tea recipes** — cmd `4512`/`4513` don't exist before this, requires official app
  ≥2.1.0) → `V12.0D.400` (2025-07-02, extends tea steep to 360s + multi-temperature brewing) — no
  official `V12.0D.410` article exists, confirming the switcher app's own note that its `.410` file is
  what "public notes call D400". Second, and more conclusively, for the `.500` file that Zendesk
  doesn't cover at all: the **official Android app's own `classes*.dex`** (`xbloom_coffee_release.apk`,
  downloaded and statically inspected 2026-07-16, never installed) names the live update-check
  endpoint `tUpToDateFirmwareVersion.thtml` on the same `client-api.xbloom.com` host `_cloud_client.py`
  already talks to (Kotlin classes `UpToDateFirmwareVersionForm`/`...Transfer`/`...Response`,
  found alongside `MachineJ15Fragment` — confirming "J15" = Studio). Calling it live
  (`{"interfaceVersion": 19700101, "skey": "testskey"}`, no login) returned `version_string:
  "V12.0D.500"`, a 5-line English changelog, and `md5_string: "5E351B943FA5DA82BA40DE4ADF740259"` —
  which matched the switcher app's bundled `.500` file **byte-for-byte** (`md5` on both sides), so that
  file is now confirmed as a genuine, unmodified official release, not just self-reported. **Acted on
  2026-07-16**: `coordinator.py`'s `MIN_FIRMWARE_EASY_MODE`/`MIN_FIRMWARE_TEA` constants +
  `_firmware_at_least()` gate `async_write_easy_slot()` and the tea path of `async_execute_recipe()` so
  a machine on firmware older than a feature's introduction gets a clear "firmware too old" message
  instead of the machine silently ignoring commands it doesn't understand.
  `_cloud_client.get_latest_firmware()` wraps `tUpToDateFirmwareVersion.thtml` (public, no login, same
  class as `fetch_shared_recipe`) and `update.py`'s `XBloomFirmwareUpdateEntity` polls it live — no
  `install()` (this integration does not flash firmware, see the `8100`/`8101` OTA note above for why)
  — on a deliberately slow `SCAN_INTERVAL` (24h): it's xBloom's production API, not a dedicated
  status/CDN endpoint, and there's no published rate limit to stay safely under.
- **`RD_MachineInfo` (cmd 40521) may still arrive late or not at all on some firmwares.** The retry loop in `coordinator.py:_machine_info_retry_loop` and the manual-signature scanner in `_client.py:_scan_for_machine_info` handle the common cases, plus a GATT 180A read fallback. If all three fail, the Model / Serial / Firmware sensors will stay `unknown`. `_status.water_level_ok` (set only inside the `RD_MachineInfo` handler at `src/xbloom/core/client.py:272`) likewise stays `False` — `coordinator._async_update_data` therefore *cannot* trust the raw flag at idle. It uses `serial_number` non-empty as a proxy for "MachineInfo has been seen"; otherwise it derives water-shortage state from the `water_shortage` error event stream.
- **Tea recipes use the dedicated `4513`/`4512` path — NOT `8004`.** A PacketLogger HCI capture of the official iOS app (2026-05-28, CRC-verified) confirmed `8104` (set_cup) → `4513` (`APP_TEA_RECIP_CODE`) → `4512` (`APP_TEA_RECIP_MAKE`); `8004` with tea cup bounds was tested locally and the firmware did NOT enter tea mode (no tea UI, no siphon). Lives in `brewing.py` (`_async_brew_tea`/`_build_tea_payload`); do not patch the vendored library. Multi-steep separation, real soak, and tea→coffee grinding were all fixed 2026-05-29 (pattern=1 substep byte + siphon-cap top-up trick + dropping a QUIT prelude that was killing the grinder) — see `docs/en/brewing-notes.md` for the byte-level history.
- **MachineInfo string fields are 0xFF-padded, not NUL-padded.** The `theModel` slice of the `RD_MachineInfo` (40521) payload is filled with `0xFF` on machines that don't populate it. A naive `decode('utf-8', errors='ignore')` lets some `0xFF` runs through whenever they form valid UTF-8 sequences with neighboring bytes — produces garbage in the Model sensor. Always run MachineInfo / GATT 180A bytes through `_client.strict_ascii()` (printable 0x20–0x7E only), cherry-picked from `src/xbloom-ble/python/xbloom.py:_handshake_notify._hex_ascii`.
- **Easy Mode slot writes (cmd 11510) are type-2 packets** — the type byte at packet offset 2 is `0x02`, not the usual `0x01`. Use `client._send_command_raw(11510, payload, type_code=2)`. Payload prefix is `[slot_index][flags]` followed by the same recipe blob `build_recipe_payload` produces for 8001/8004 brews.
- **Easy Mode slots must be written as a full A/B/C batch, with no commit frame, and PRO mode first.** Hardware-confirmed 2026-07-15: writing a single slot hangs the machine at status `0x43` ("saving", RETRY) — completing all three back-to-back unsticks it (`0x43`→`0xf8`→`0x25`→idle). Writing from Easy/Auto mode is also refused (stays at `0x41`/RETRY) — the machine must be switched to PRO first. `coordinator.async_write_easy_slot()` handles both: it resolves the other two slots' current contents before writing, force-switches to PRO if needed (restoring the prior mode after), and `brewing.async_write_easy_slots()` always sends all three frames in one call — there is no single-slot write path. **The BLE-level "write all three" requirement must not leak into HA's own bookkeeping of which slots the user actually assigned.** Hardware-confirmed 2026-07-17: writing only slot A while B/C had never been configured made the `easy_slot_a`/`b`/`c` sensors *all* show as registered — `async_write_easy_slot()` mirrors the target recipe into the BLE payload for any never-written slot (there's no other valid payload to send, and no readback to preserve instead), but was also persisting that synthetic mirror into `entry.options["easy_slots"]` for all three letters. Fixed to persist only the target letter; the fallback recipe still goes out over BLE for the other two (unavoidable), it just isn't reported back to the user as a real assignment.
- **No-grind coffee recipes need a real, nonzero dose sent to `8102` — `dose=0` silently hangs the arm.** Hardware-confirmed 2026-07-15: even with a healthy 8004 footer ratio byte, `client.set_bypass(vol, temp, dose=0)` makes the machine never reach `armed` (`0x1f`) — no refusal notification, just permanent silence. This is unrelated to whether the grinder actually runs (opcode 8001 vs 8004 already governs that) — `dose` must track `recipe.bean_weight` whenever it's `>0`, never zeroed just because `grinding` is `False`. See `brewing.py`'s `_async_brew_coffee`.
- **The raw status-heartbeat frame (not the cmd-tagged `RD_*` responses) is the only reliable way to track `starting`/`brewing`/`ready`.** Hardware-confirmed 2026-07-16 (a real ~11 s grind): `RD_GRINDER_BEGIN` never fired at all, `RD_BREWER_BEGIN` fired immediately after commit (long before pouring actually starts), and `RD_Grinder_Stop` flips vendored `DeviceState` to `IDLE` the instant grinding *ends* — moments before real pouring begins. `_client.py`'s `_scan_for_status_frame`/`_RAW_STATE_LABEL_MAP` reads the raw frame directly (header(0x58|0x02) | dev_id | `0x57` | ... | `0xc1` marker | state_byte | ...; state byte is the first byte after the same 10-byte preamble the cmd-tagged frames use) for `0x22`(starting)/`0x10`,`0x23`,`0x3B`(brewing)/`0x24`(ready), overriding the vendored value only for those codes — `coordinator._async_update_data`'s state priority is `no_beans → water_shortage → raw_label → vendored s.state.value`.
- **cmd `40518` is `BREW_PAUSE`, not "start" — CONFIRMED, no longer open.** Hardware-confirmed 2026-07-15/16 (see the original observation below), and as of 2026-07-16 settled beyond doubt: the **official Android app's own compiled bytecode** (`xbloom_coffee_release.apk`, decompiled with `androguard` — see the cmd-ID validation sweep two bullets below) has a class `com/chisalsoft/andite/manager/AppJ15AutoManager` whose method literally named `pause()` sends `const/16 v3, 40518`; the sibling `restart()`/`stop()` methods send `40524`/`40519`. This directly refutes the Janczykkkko/xbloom-ble claim that 40518 is the post-commit "go" and confirms brAzzi64's `CMD_BREW_PAUSE` naming. Original hardware observation (still the operationally relevant part): sending it into an already-progressing brew resets it back to `armed` — across two live grind-path brews, one where it was sent after only a 3 s stall at `awaiting_confirm` (the brew reset to `armed` and never resumed on its own, needing a manual `stop_recipe()`), and one where it was never sent at all (the brew completed naturally in ~65 s — a ~9 s `awaiting_confirm` delay before `starting` is apparently normal for a real grind, not a hang). Still do not send it speculatively — it's a real pause, not a no-op.
- **cmd `8104` is genuinely cup weight bounds — CONFIRMED, no longer open.** Our shipped code (`brewing.py`, `src/xbloom/core/client.py:set_cup`) sends two floats as `(max, min)` cup-weight bounds; a third-party capture (Janczykkkko/xbloom-ble) had claimed the identical payload shape was two preheat "stage temps" instead, and on-device `RD_BREWER_TEMPERATURE` telemetry couldn't settle it either way (see the original note this replaces). Settled 2026-07-16 by decompiling the **official app itself**: `com/xbloom/util/BleCodeFactory$Companion.setCup()` and three separate call sites (`PodsDetailActivity`/`RecipeDetailActivity`'s `sendCupJ15()`) all send `const/16 v_, 8104` from a method literally named "setCup", and the official app's own `j15code.S_CupType`/cup-bounds-building code (`theMax`/`theMin` field names — the same names `denull0/xbloom-agent`'s cloud-API `create_recipe()` uses) matches our cup-weight-bounds interpretation, not preheat temps. The Janczykkkko claim is now refuted at the source, not just out-competed on priors.
- **The full command-id table was cross-checked against the official app's own compiled bytecode 2026-07-16 — near-total confirmation, one real gap found.** Downloaded `xbloom_coffee_release.apk` (multidex, 5 `classes*.dex`) and parsed it with `androguard` (proper DEX bytecode access — field/enum values and method-body constants, not just string-grepping the way the earlier `cryptofishbug/xbloom-recipe-cli` switcher-app analysis had to). A scripted sweep for every known command id as a `const`/`const-16` literal, across all 5 dex files, hit almost every one of them in a class/method whose name matches its documented purpose — `com/xbloom/util/BleCodeFactory$Companion` (`backToHome`→8022, `setCup`→8104, `teaRecipeCode`→4513, `makeTea`→4512, `quitRecipeStart`→8017, `easyModeRecipe`→11510, `easyModeSwitch`→11511, `easyModeRecipesOrder`→11512), `com/chisalsoft/andite/manager/AppJ15AutoManager` (`pause`→40518, `restart`→40524, `stop`→40519), `com/chisalsoft/andite/manager/AppBleManager.mtuSuccess`→8100, `.../activity/machine/FwUpgradeActivity`→8101, `RecipeDetailActivity`/`PodsDetailActivity` (`sendBypassJ15`→8102, `sendCodeJ15`→8001/8004, `sendCupJ15`→8104, `startJ15`→8002), and `com/chisalsoft/andite/model/ble/BaseBleModel$Companion.create` — a single dispatcher containing essentially the entire inbound `RD_*` table (10507/20501/40510/40523/40512/40507/40511/40521/8203/8204/40517/40522/40526/8023/11518/8111/9009/9010/8107/8108/8105/8106/9003/9005/9001/9000/9004/40502/9011/40515) in one place. Also resolved the cloud pattern-mapping question from the `xbloom-recipe-cli` review: `j15code.S_PourPattern`'s `<clinit>` assigns `center=1, spiral=2, circular=3` — matching our own live-account-verified `_LOCAL_PATTERN_TO_CLOUD` exactly and refuting `cryptofishbug/xbloom-recipe-cli`'s README table (which had spiral/circular swapped); `j15code.S_CupType` likewise confirms `XPod=1, XDripper=2, Other=3`. **The one real, actionable gap** (fixed same day): `easyModeRecipesOrder` (cmd 11512, `Ljava/lang/String;` hex payload — same shape Mel0day/xbloom-ai-brew's `framesEasyMode` sends) is a genuine method the official app calls after writing all three Easy Mode slots — flagged in the `xbloom-recipe-cli` review as possibly just a display-order hint since our A/B/C batch write already worked without it, but confirmed as real official-app behavior, not a third-party embellishment. `brewing.async_write_easy_slots()` now sends it too (payload `[3, 0, 1, 2]`, matching Mel0day's observed default) — untested on real hardware.
- **"Advanced Features" (pour radius / vibration amplitude / grinder calibration) reverse-engineered via `jadx`, not just `androguard` — two of three landed, two more (descale, scale calibration) hit a dead end.** `androguard`'s bytecode access finds command-*id* literals fine but not payload *encoding* (parameter types, scaling, response parsing) — `jadx` decompiles to near-source Kotlin/Java, which resolved both in one pass. `MachineSetPourRadiusActivity`/`MachineSetVibrationAmplitudeActivity`/`MachineAdvancedFeaturesJ15Activity` (all `.java`, 2026-07-16) gave: pour radius is GET `11506`/SET `11507`, a **5-level discrete control** (not continuous) centered on a per-device value read back from the machine, each level ±80 apart (`radius = center - (2 - level) * 80`); vibration amplitude is GET `11508`/SET `11509`, same shape. Response format confirmed from the app's own parsing code (`it.substring(0,8)` → `reverseHex()` → parse as hex int — byte-reversing a big-endian hex dump is the same operation as reading little-endian): payload\[0:4\] as LE uint32, matching every other integer RD_* payload in this codebase. Neither 11506 nor 11508 exist in the vendored `XBloomResponse` enum, so `_parse_response`'s `XBloomResponse(cmd)` raises `ValueError` and silently drops them before reaching `_handle_response` — **the official app has the exact same problem and solves it the same way we do**: reading `AppBleManager`'s source shows it keeps no fixed response registry at all, just parallel `codeList`/callback lists it matches an incoming notification's raw cmd against — confirming `_client.py`'s established raw-pre-scan pattern (`_scan_for_status_frame`/`_scan_for_machine_info`) was the right model to extend, not a workaround. `_client.py`'s `_scan_for_advanced_settings` does exactly that now. Grinder calibration is `CalibrateGrinderActivity`'s confirm button: `CodeModule(3502, "磨豆档位归0", 1000)` — cmd `3502`, single fixed payload `[1000]`; the ~120s calibration sweep then runs autonomously on the machine, matching the Zendesk Cleaning & Maintenance doc. **Display brightness** (found 2026-07-17 chasing a follow-up question, same `jadx` method): `MachineDisplayActivity`'s save button sends `BleCodeFactory.switchLed(value)` → `CodeModule(CommandParams.RD_LetType, "亮度切换", value)` — `CommandParams.RD_LetType = 8103` (a gap in our command table between the already-known `8102`/`8104` we hadn't noticed), 3 fixed presets (L1/L2/L3 → raw `1`/`8`/`15`), no GET counterpart (the app reads the current value from its own cached account/device record, not a fresh BLE read, so there's nothing to poll here either). All four are exposed as a single `advanced_settings` service (`coordinator.async_set_advanced_settings`) plus two new read-only sensors (`pour_radius`, `vibration_amplitude` — brightness has none, matching its no-GET reality) rather than several always-visible entities — deliberately not `number`/`button` entities for settings nobody adjusts often. The service takes **levels** (`pour_radius_level` 0-4 / `vibration_amplitude_level` 0-5 / `display_brightness_level` 1-3), not raw values, matching the official app's L1-L5/L1-L6/L1-L3 picker UIs — see `coordinator._pour_radius_level_to_raw`/`_vibration_level_to_raw`/`_client._DISPLAY_BRIGHTNESS_RAW`. **Descale and scale calibration were NOT found** despite the same `jadx` treatment: `DescaleActivity`/`DescaleFragment` turned out to be a pure 7-page tutorial image carousel with zero `CodeModule`/`CodeModule2` calls anywhere in the class hierarchy, and `CalibrateScaleJ15Activity` likewise has none in its own methods — the actual trigger is delegated somewhere neither `androguard`'s const-sweep nor a `CodeModule(` grep across all decompiled sources could reach (candidates: the separate `ScaleActivity` class's `8003`/`8014` scale-mode entry/exit commands, or the `AppWsManager` websocket manager — genuinely unresolved, not just deprioritized).
- **`_scan_for_advanced_settings` only checked byte offset 0 of the BLE notification buffer — hardware-confirmed broken 2026-07-17.** After deploying the Advanced Features work above, the user reported `pour_radius`/`vibration_amplitude` sensors stuck `unknown` after connect even though nothing errored. Unlike this file's other raw pre-scans (`_scan_for_machine_info` does `raw.find(...)` anywhere in the buffer; `_split_and_parse` walks byte-by-byte for a header match and advances by each frame's real length), the original `_scan_for_advanced_settings` assumed the target frame started at offset 0 — silently missing it whenever a single BLE notification carried a leading unrelated/partial frame first (routine given the weight/water-volume telemetry stream floods concurrently). Fixed to walk the whole buffer exactly like `_split_and_parse` (header byte scan, length-field bound check, marker-byte check, advance by the real frame length on a match) — see `_client.py`. Two regression tests added (`test_frame_found_when_not_at_offset_zero`, `test_frame_found_after_a_preceding_full_frame`) since the original single-frame-at-offset-0 tests didn't and couldn't have caught this. Also removed the redundant `firmware_version` sensor (same info now on the `update.py` entity from the earlier bullet).
- **The offset-0 fix above didn't actually fix it — the machine was never responding to the GET at all.** Follow-up hardware report 2026-07-17 (still `unknown` after the fix, on a fresh reconnect). Root-caused by connecting directly to the real machine over BLE from a plain Python script (bypassing Home Assistant entirely — no HA instance was reachable from this environment, so this was the only way to get a live capture), reusing the actual unmodified `_client.py`/vendored `XBloomClient` code: sending `11506`/`11508` with the default `type_code=1` gets zero response, ever (confirmed by capturing every notification for several seconds after sending — no match, not even a malformed one). Resending with `type_code=2` — the same packet type the `11510` Easy Slot family needs — got an immediate reply. **The response's marker byte is also type-dependent**: type-2 responses carry `0xC2` at offset+9, not the `0xC1` `_NOTIFICATION_MARKER_BYTE` constant every other command in this file uses (apparently the marker is `0xC0 | type_code`, not a fixed protocol-wide constant — never surfaced before because every other command this integration sends is type-1). `_scan_for_advanced_settings` was rejecting the real responses on marker mismatch even after type_code was fixed, so both bugs had to be fixed together. Values read back on live hardware cross-confirmed the whole chain: `pour_radius: 750` (matches this exact machine's `initPouringRadius` from the cloud API, live-verified 2026-07-16) and `vibration_amplitude: 1000` (matches `_vibration_level_to_raw`'s level-0 raw value). All four commands (`async_get_pour_radius`/`async_set_pour_radius`/`async_get_vibration_amplitude`/`async_set_vibration_amplitude`) now send `type_code=2` via `_ADVANCED_SETTINGS_TYPE_CODE`, and the scan checks `_ADVANCED_SETTINGS_MARKER_BYTE` (0xC2) instead of the shared constant.
- **Third layer of the same bug: the GET was fired before the machine was actually awake.** After the type_code=2 fix above shipped, the same user still saw `unknown` sensors after a real HA restart + reconnect. Root cause this time (found by adding first-party logging — see the `xbloom.core.client` suppression bullet below — since it had been silently masking every earlier attempt to observe this): the GET was fired unconditionally right after `client.connect()` returns, but on this exact machine/session MachineInfo did *not* arrive from the first 8100 handshake — the retry loop needed a second handshake ("Re-sending 8100 handshake to retrigger MachineInfo") roughly 5 seconds later before `RD_MachineInfo` actually showed up. The pour_radius/vibration_amplitude GET, sent during that dead window, was silently dropped exactly like the documented "machine ignores every command until the handshake truly lands" firmware quirk predicts — it's a request/response command, just as vulnerable to that window as MachineInfo itself, but it was never gated on the same signal. Fixed: `async_connect()` now only fires `_async_refresh_advanced_settings()` if `client.status.serial_number` is *already* populated (MachineInfo already confirmed) right after connect; `_machine_info_retry_loop()` fires it instead, at both of its own MachineInfo-confirmed success points, when MachineInfo arrives late. No double-fire — the retry loop only ever spawns when the connect-time check didn't already have serial_number.
- **A fourth, orthogonal finding surfaced while debugging the above: the vendored `xbloom.core.client` logger's SEND CMD/RECV CMD output can be silenced independently of `custom_components.xbloom.*`.** A real user's log dump showed zero `SEND CMD`/`RECV CMD` lines anywhere — not even the connect-time 8100 handshake, which unconditionally fires — while `custom_components.xbloom.coordinator`/`._client`'s own DEBUG/INFO lines were clearly present throughout. Something in that install's logger config (a per-logger level override, plausible given `xbloom.core.client` logs every single telemetry frame at INFO) was suppressing that one namespace. This made "grep the log for the command id" a dead end for real diagnosis in that environment even though nothing was actually wrong at the protocol level at that point in the investigation. `_async_refresh_advanced_settings()` and `_scan_for_advanced_settings()` now also log on `custom_components.xbloom`'s own loggers (confirmed visible in the same log dump) — request sent, GET completed, and any parsed response — so this class of command is diagnosable without depending on a third-party logger namespace nobody expects to need to re-enable.
- **A fifth layer, found after all of the above shipped: pour_radius worked, vibration_amplitude still didn't — the 0.3s gap between the two GETs was too short.** The same user reported pour_radius finally populated (750) but vibration_amplitude stayed `unknown`. Reproduced directly on the real machine (4 repeated trials each): a 0.3s gap between the `async_get_pour_radius()` and `async_get_vibration_amplitude()` calls made the vibration GET's `SEND CMD 11508` go out correctly every time but get **zero response**, consistently, while pour_radius always succeeded; 0.6s/1.0s/1.5s gaps all succeeded consistently. The machine appears to still be busy replying to the first type-2 request when the second one arrives, and silently drops it rather than queuing it — this is a genuinely new, narrower timing constraint on top of the type_code=2 requirement itself (a correctly-typed, correctly-marked request can still get dropped if sent too soon after a sibling request). `_async_refresh_advanced_settings()`'s gap is now 0.8s (up from 0.3s) for margin.
- **The 0.3s-gap-drops-the-second-type-2-command finding generalizes beyond GET — confirmed on SET too, and applied defensively to Easy Slot writes.** Directly reproduced on the real machine: `async_set_advanced_settings`'s `SET pour_radius` → `SET vibration_amplitude` pair (sent when both `pour_radius_level` and `vibration_amplitude_level` are given in one service call) dropped the second SET's ACK at a 0.3s gap in 2/2 trials, succeeded at 0.8s in 2/2 trials — same signature as the GET pair. Both gaps in `async_set_advanced_settings` widened to 0.8s. `brewing.py`'s Easy Slot writes (`11510` per slot A/B/C, then `11512` order frame — same 115xx type-2 family) use the identical 0.3s-gap pattern and were widened to 0.8s too, on the reasoning that the drop is a transport-layer property of back-to-back type-2 commands (the machine still busy replying to the previous one) rather than something specific to which command it is — **not independently hardware-verified for 11510 itself**, since that would mean deliberately testing with real Easy Mode slot writes (risking overwriting a user's actual configured slots) rather than a harmless no-op SET.
- **The mode-switch ACK (cmd 11511 / `RD_EASYMODE_TYPE`) has been silently dropped this whole time by the same marker-byte assumption — a different bug from the 0.3s-gap family above, found while implementing a fix for user-reported mode-switch flakiness.** `_split_and_parse` only ever accepted marker `0xC1` (`_NOTIFICATION_MARKER_BYTE`), but cmd 11511 is sent as `type_code=2`, so its response carries marker `0xC2` like every other type-2 command in this file — `RD_EASYMODE_TYPE` *is* in the vendored `XBloomResponse` enum and would otherwise flow through the normal `_handle_response` path (unlike pour_radius/vibration, which needed the separate `_scan_for_advanced_settings` pre-scan workaround because they aren't in the enum at all), but the marker check silently discarded the frame before it ever got there. Hardware-confirmed 2026-07-17: captured the real ACK frame (`580207f72c10000000c2913278569080`, marker `0xc2`, payload matching the "easy" mode code) arriving on the wire while `_mode_ack_hex` stayed `None` the whole time. Renamed `_ADVANCED_SETTINGS_MARKER_BYTE` to the more accurate `_TYPE2_MARKER_BYTE` (0xC2, not specific to advanced settings) and widened `_split_and_parse`'s check to accept both `_NOTIFICATION_MARKER_BYTE` and `_TYPE2_MARKER_BYTE` — this is a general fix to the shared notification pipeline, not a workaround scoped to one command. Re-verified live after the fix: `_mode_ack_hex` now correctly populates on every mode switch.
- **Mode switching now retries on ACK timeout, matching the official app's own spec — decompiled 2026-07-17.** `com/chisalsoft/andite/manager/AppBleManager.java`'s `sendMessage` (the app's general command-send wrapper, used for `setDeviceMode` same as everything else — there is no mode-switch-specific reconnect/disconnect logic in the app at all) retries the *same* command on a 1.5s ACK timeout while `AppDeviceManager.isSleeping()` is true, up to `retryCount < 3` (i.e. 4 total sends: 1 initial + 3 retries) before giving up and surfacing a "BLE ACK Timeout" error — never tears down the connection for this. `coordinator._async_switch_mode_with_retry()` now mirrors this exactly (`_MODE_SWITCH_ACK_TIMEOUT_S=1.5`, `_MODE_SWITCH_MAX_ATTEMPTS=4`), replacing the previous blind `await asyncio.sleep(0.5)` in all four mode-switch call sites (`async_set_mode`, `_ensure_pro_mode`, `_restore_persisted_mode`, `async_write_easy_slot`'s force-switch-to-Pro). This only works because of the marker-byte fix above — without it, every retry would exhaust all 4 attempts for nothing, since the ACK could never be observed. Live-verified: 4/4 mode switches (easy→pro→easy→pro) confirmed on the first attempt, no retries needed.

**Every service's `device_id` field is now `config_entry_id` — a `config_entry` selector, not `device`.** First attempt (reverted same day): narrowing the `device_id` field's `device` selector to the main device only via `filter[0].entity: {domain: update}` — `hassfest` rejects `entity` as a key inside a plain **field**-level `device` selector's `filter` (`extra keys not allowed`; that sub-key is only valid inside a **`target:`** block, a materially different mechanism this integration doesn't use). The failure cascaded into spurious `required key not provided @ ...['target']` errors on every *other* service in the file too — a single bad schema branch anywhere in services.yaml makes voluptuous retry the whole document against an unrelated alternative schema, so an unrelated-looking wall of errors can point at one root cause. Second attempt (kept): a `config_entry` selector sidesteps the problem structurally rather than filtering it away — each XBloom config entry already maps 1:1 to a physical machine, so the picker only ever lists one item per machine regardless of how many device-registry entries (main + Grinder/Scale/Brewer) it owns. **Confirmed against HA core's actual `dev` branch source** (`homeassistant/helpers/selector.py`, fetched directly — this repo's own installed `homeassistant` test dependency was version 2025.1.4, a full year behind the `2026.8.0.dev*` floor this integration targets, so its `ConfigEntrySelector` schema wasn't trustworthy to test against locally): `ConfigEntrySelector.CONFIG_SCHEMA` only accepts `integration` — **no `multiple` key at all**, and `__call__` validates the result as a bare string, not a list. So a `config_entry` selector can only ever pick one machine, never several; the two services that previously accepted several devices at once (`execute_recipe`/`execute_tea_recipe` looping over every targeted coordinator, `cloud_import_recipe` doing the same) can now only target one specific machine or (leaving the field blank) all of them — the "no selection" behavior in `_coordinators_for_call` was unchanged, so that fallback still means "every configured machine," just the "several, but not all" middle case is gone. `_coordinators_for_call` no longer touches the device registry at all — `call.data.get("config_entry_id")` maps directly to `hass.data[DOMAIN][entry_id]`.
- **Removed `sensor.last_error`** (`XBloomErrorSensor`) — a byte-for-byte duplicate of `binary_sensor.problem`'s own `last_error` extra-state-attribute (both just read `coordinator.data["error"]"). `event.error_event` is not a duplicate of either — it's a momentary occurrence log (fires once per error with an `event_type` attribute), not an ongoing-state surface, so it stays.
- **A third, separate cloud backend exists — `backend-api.xbloom.com`, a signed Retrofit/JSON API, unrelated to `API_BASE`(`client-api.xbloom.com`)/`COLLECTIVE_API_BASE` in `_cloud_client.py`.** Found 2026-07-16 chasing where the official app gets pour-radius's per-device factory-default center (`Device.pouringRadiusInit` — see the bullet above; this integration has no access to it otherwise, since it's account/serial-keyed, not a fixed constant). Reverse-engineered from `RetrofitManager2`/`ApiDevicePour`/`ServiceConfig`/`WebConfig`/`ConfigBean` (`com.chisalsoft.andite.http.j15` / `cn.com.library.config`) via `jadx`: `GET /app/device/getInitPouringRadius?serialNumber=...&pouringRadius=...` returns `{code, message, request_id, data: {initPouringRadius, pouringRadius}}` (`code == 0` = success — note `BaseResp.isSuccess()` elsewhere in the same class also accepts `200`, but the one call site that matters, `DevicePourRep.kt`, uses `.convert()`, which only accepts `0`). Every request needs a signed header set, **no separate login** — `LoginActivity.loginSuccess()` calls `ServiceConfig.saveToken(response.getProjectToken())`, a *second* token field (`projectToken`) in the exact same `tMemberLogin.thtml` response our own `login()` already parses, previously discarded. Signature: `sign = uppercase(MD5("{appId},{appSecret},{nonce},{ts}"))`, `nonce` = a random UUID (hyphens stripped, lowercased), `ts` = unix seconds, plus `Authorization: token {projectToken}` and static `platform`/`appid`/`version`/`accept-language` headers. `appId`/`appSecret` are baked into every build variant identically (`ServiceConfig.kt`'s `ConfigBean(baseUrl, appId, appSecret, webSocketUrl)` — confirmed field order from the `data class` decompile; dev/test/release/China-release all share the same pair) — they authenticate "this is the app," not the user; `projectToken` is what actually scopes access to the caller's own account/devices. Implemented as `_cloud_client.py`'s `BACKEND_API_BASE`/`_backend_api_sign`/`XBloomCloudClient.get_pour_radius_init_center`, wired into `coordinator.async_set_advanced_settings`. **`pour_radius_level` now requires a logged-in cloud account outright** (rejected up front with `cloud_login_required` otherwise) — the current-value-as-center approximation this originally shipped with was dropped once the real cloud value was confirmed reachable, since that approximation is only valid on a machine nobody has ever nudged the level on before, which this integration can't verify either way. **Live-verified 2026-07-16** — a standalone script (`verify_pour_radius_center.py`, needs `XBLOOM_EMAIL`/`XBLOOM_PASSWORD`/`XBLOOM_SERIAL` env vars, never committed) was handed to the user to run with their own real account rather than asking for credentials directly; they ran it against their real account (member_id 23237) and device (serial `J15A01B4CV030`) and got back a real `initPouringRadius` of `750` — confirming the request shape, the `projectToken`-reuse-from-`tMemberLogin.thtml` assumption, and the signing scheme are all correct on the first live attempt, not just plausible-looking reverse-engineering. Two unrelated local-environment issues surfaced along the way (both fixed in the verification script, neither an API/code issue): an `aiodns`/`pycares` version mismatch breaking aiohttp's default resolver (worked around with `aiohttp.ThreadedResolver()`), and the same local SSL CA trust-store gap noted in the cloud-recipes history (fixed by pointing the connector's SSL context at `certifi.where()`).
- **Tea steeps end on `RD_TEA_RECIP_PAUSE` (40515) → "paused"** or `RD_ENJOY` (40512) → "recipe_complete". The firmware fires these between steeps inside one `8004` recipe — entities can listen via the event bus rather than orchestrating per-steep.
- **A second, independent notification-framing check: every real response frame carries a constant marker byte (`0xc1`) right after the length field.** `_client.py`'s `_split_and_parse` requires it alongside the existing `_MAX_PACKET_LEN` bound, making a coincidental false-positive header match (right length *and* right marker, purely by chance, inside the noisy weight/water-volume telemetry stream) even less likely. Confirmed on every captured `RD_MachineInfo` frame this session.

## BLE protocol primer

Packet layout: `header(0x58 0x02) | dev_id | type | cmd(2 LE) | len(4 LE) | const(0x01) | payload | crc(2)`.

Helpful constants live in `src/xbloom/protocol/constants.py`; the most thoroughly-decoded protocol reference is `src/xbloom-ble/PROTOCOL.md` (HCI snoop captures from the official iOS app). Notable inbound responses: `RD_MachineInfo` (40521), `RD_WATER_VOLUME` (40523), `RD_BREWER_PAUSE` (9010), `RD_TEA_RECIP_PAUSE` (40515), `RD_ENJOY` (40512), `RD_BLOOM`, `RD_BREWER_BEGIN`, `RD_Brewer_Stop`, `RD_GRINDER_BEGIN`, `RD_Grinder_Stop`. Notable outbound commands: `APP_BREWER_START`, `APP_RECIPE_SEND_AUTO` (8001, with grinding), `APP_RECIPE_SEND_MANUAL` (8004, no grinding), `APP_TEA_RECIP_CODE` (4513) / `APP_TEA_RECIP_MAKE` (4512, the live tea path), `APP_RECIPE_EXECUTE` (8002), `APP_RECIPE_STOP` (40519), `8022` (Back to Home, sent at the start of every recipe).

## BLE connection management

- **Connects through HA's Bluetooth integration, not a bare `BleakClient`.** The vendored `src/xbloom/connection/bleak_impl.py` opens `BleakClient(mac_address)` directly — no HA proxy routing, no `bleak-retry-connector` retry/cache-clear handling. `_client.HABleakConnection` (injected via the vendored `XBloomClient(connection=...)` constructor param, never by editing the vendored file) resolves the address through `bluetooth.async_ble_device_from_address` and connects via `bleak_retry_connector.establish_connection` instead. `manifest.json` depends on the `bluetooth` integration and requires `bleak-retry-connector` for this. **Every** BLE connection this integration makes must use `HABleakConnection` + `XBloomClientWithEvents` (from `_client.py`) — `config_flow.py`'s discovery-confirm and manual-MAC-entry connect-tests used the bare vendored `XBloomClient()` with no `connection=` arg until 2026-07-15, which bypassed both this and the notification-framing fixes below; confirmed live via the exact "Partial packet received" / "connect() called without bleak-retry-connector" warnings those fixes exist to prevent.
- **Auto-reconnects on an unexpected BLE drop.** Before 2026-07-04 nothing ever called `coordinator.async_connect()` again after an unrequested disconnect — only the connection switch's `async_turn_on` did — so any drop left the switch stuck "off" until manually flipped. `HABleakConnection`'s `disconnected_callback` now calls `coordinator._handle_unexpected_disconnect()`, which reconnects unless the drop was caused by `async_disconnect()` itself (tracked via `_manual_disconnect`, so turning the switch off on purpose doesn't immediately reconnect).
- **Connection supervisor + silence watchdog (2026-07-17), deliberately mirroring the official Android app's `AppDeviceManager` poll loop** (decompiled via `jadx`/`androguard` from `xbloom_coffee_release.apk` — `initTimer()`'s `Observable.interval(0, 5, SECONDS)`, `initHeartCheck()`/`removeHeartCheck()`, and `blueNotifyMessage`'s `onCharacteristicChanged` resetting the watchdog on every notification). Two gaps this closes that `_handle_unexpected_disconnect()` alone didn't cover:
  1. **No backstop retry.** `_handle_unexpected_disconnect()` fires once per BLE-level drop and gives up silently if that one `async_connect()` attempt fails (e.g. adapter briefly busy) — nothing retries again until another drop event, which can't happen while already disconnected. `coordinator._async_update_data()` now also drives `_maybe_schedule_reconnect()` on every poll tick (`update_interval`, default 5s — same cadence as the app's timer): if not connected, not mid-connect (`_connect_lock.locked()`), and not user-disconnected this session (`_manual_disconnect`), it schedules another `async_connect()`. This also means the integration now auto-connects at HA startup for free — `async_setup_entry`'s initial `await coordinator.async_refresh()` calls `_async_update_data()` once with `self.client is None`, which schedules the first connect attempt; previously nothing anywhere called `async_connect()` until the user flipped the connection switch on.
  2. **A GATT link can go silent without ever firing a disconnect event.** `client.is_connected` only reflects the GATT-level connection state, not whether the firmware is still actually talking — a wedged link would never trigger `_handle_unexpected_disconnect()` at all. `_client.py`'s `_on_notification()` now stamps `self._last_notification_monotonic` on every raw notification (the telemetry stream floods at multi-Hz under normal operation per the framing-bug note below, so a large gap is a reliable stale-link signal), exposed via `seconds_since_last_notification()`. `coordinator._async_update_data()` forces a reconnect (`_async_force_reconnect()`, going through `async_disconnect()` for proper teardown then immediately clearing `_manual_disconnect` again so it isn't mistaken for a user-requested disconnect) if that gap exceeds `_BLE_SILENCE_TIMEOUT_S` (15s).
  - **The 15s threshold is a deliberately conservative placeholder, not hardware-verified** — the devcontainer has no real Bluetooth reachable in this environment (see Testing below), so the app's own 2s couldn't be cross-checked against our actual telemetry cadence. If the watchdog ever fires spuriously during a real idle period (or, conversely, never fires when it should), that's a signal to retune `_BLE_SILENCE_TIMEOUT_S`, not evidence the mechanism is wrong.
  - **Deliberately session-only**, not persisted to `entry.options` — unlike the app, which stores its `autoConnect`/`isDisconnect` preference in the device DB so a relaunch remembers a deliberate disconnect. Turning the connection switch off only sets the in-memory `_manual_disconnect` flag; an HA restart creates a fresh coordinator and will auto-connect again regardless of the last session's switch state.
- **A stray header byte inside telemetry can produce a garbage frame length.** The vendored framing loop (`src/xbloom/core/client.py:_on_notification`) scans raw notification bytes for a header byte (`0x58`/`0x02`) and reads the next 4 bytes as the packet length with no bounds check — a false match inside the weight/water-volume telemetry stream (which floods at multi-Hz) can read garbage (e.g. `0xc2000001` = 3254779905) and, in the vendored code, discards the rest of the buffer with a misleading "Partial packet received" warning. `_client.py`'s `_on_notification` override replaces the framing loop (`_split_and_parse`) with the same logic plus a `_MAX_PACKET_LEN` (256) sanity bound: anything larger is a false-positive header byte, skipped instead of aborting the buffer.
- **Changing the mode-select entity must not reload the config entry.** `coordinator.async_set_mode()` persists the preference via `hass.config_entries.async_update_entry()`, which fires `__init__.py`'s `_async_update_listener`. `CONF_MODE` is in `_NO_RELOAD_OPTION_KEYS` (alongside the recipe-store keys) specifically so this doesn't trigger `hass.config_entries.async_reload()` — a reload's `async_unload_entry` calls `coordinator.async_disconnect()`, and nothing in `async_setup_entry` reconnects automatically, so every mode switch used to drop the connection and leave it dropped (confirmed live 2026-07-04, and easy to mistake for a firmware quirk — it wasn't).

## Device registry (4-device split)

Each config entry has **4 device-registry entries**, not 1: the main
device plus Grinder/Scale/Brewer child devices, linked via `via_device`
(`coordinator.grinder_device_info` / `scale_device_info` /
`brewer_device_info`, both backed by `_sub_device_info()`). `unique_id`s
are untouched — this is a pure device-page regrouping, no
entity_id/automation breakage. Deliberately not HA's "config subentries"
feature (that's for dynamically add/removable child items — wrong fit for
fixed sub-components of one physical machine).

Two things `via_device` does **not** give you for free, both
hardware-confirmed 2026-07-15/16:

- **Translation.** A literal `name=` on child `DeviceInfo` ships
  English-only device names regardless of the user's HA UI language. Use
  `translation_key` + a top-level `device.<key>.name` block in
  `strings.json`/`translations/*.json` (a device-level analogue of the
  entity translation flow below) instead.
- **Area assignment.** Setting the main device's area does not propagate
  to its `via_device`-linked children — each device's `area_id` is
  independent. `_sub_device_info()` passes `suggested_area` (the main
  device's *current* area, looked up via `device_registry`/`area_registry`)
  so newly-created sub-devices default into the same area, without forcing
  ongoing sync — a later manual change on either device is left alone.

**The main device must be registered before any platform is set up**,
not left to whichever platform's entities happen to register first.
`async_forward_entry_setups` fans platforms out concurrently, so entity
registration order isn't fixed — if a platform whose entities all point
at a sub-device (e.g. `binary_sensor.py`, all of whose entities are now
Grinder/Brewer/Scale) happens to register before any main-device entity
does, HA logs a "non existing via_device" warning (confirmed live). Fixed
by `__init__.py`'s `async_setup_entry` calling
`device_registry.async_get_or_create()` for the main device explicitly,
before `async_forward_entry_setups`.

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

**The official app's Product/Shared account recipe tabs (`MyRecipeType.PRODUCT`/`SHARED`
— see the app's `tuMyRecipeProduct.tuhtml`/`tuMyRecipeShared.tuhtml`) were
implemented (`cloud_search_my_recipes`/`cloud_import_my_recipe` services + LLM
tools, 2026-07-17) and reverted same day.** Decompile-driven completeness ("the
app has it, we don't") wasn't backed by an actual use case: Product recipes
(bundled with a purchased pod) are a narrow audience for a BLE-first
integration, Shared recipes (account-to-account push via the app's own Share
button) are a rare path next to the public share_url links
`cloud_import_recipe` already covers, the feature required a cloud login for
what's designed to work fully over Bluetooth without one, and none of it was
ever verified against a live account. If this gap resurfaces from a future
decompile diff, that's not new information — don't re-implement without a
concrete use case first.

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
capped at `_OFFICIAL_RECIPE_SYNC_LIMIT`, `cup_type=["Omni"]` only — the
collective hub's similarly-named "Omni Brewer" cup type is the tea
accessory, not a coffee one; excluding it avoids duplicating what the
tea seed below already covers); names already present locally —
tombstones and YAML names included — are skipped, and a failed fetch
leaves its flag unset for the next HA start to retry.

`default_recipes.py`'s **coffee** section is intentionally empty
(2026-07-16) — it held 6 hand-authored, non-official recipes until the
async official-recipe seed above became the sole coffee source, so the
dropdown isn't empty on a fresh install but is never a stale hardcoded
snapshot either. Its **tea** section stays static (4 entries, sourced
from real xBloom/Passenger Coffee & Tea product pages) since the async
seed's `cup_type=["Omni"]` filter deliberately excludes tea.

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
For a `select` with a fixed, non-recipe-derived fallback option (e.g. "No
recipes configured"), also populate `entity.select.<key>.state.<value>` —
easy to miss since most `select`/`sensor` options here are dynamic
(recipe names), not translatable strings.

**Devices get the same treatment, one level up**: `translation_key` (not
a literal `name`) on `DeviceInfo` + a top-level `device.<key>.name` block
— see the Device registry section below. A property/method that returns
a fixed placeholder string as if it were a real value (`"none"`,
`"unknown"`, `"No recipes configured"`) instead of Python `None` is a
recurring bug shape in this codebase — HA already localizes `None`/the
generic Unknown state; a raw literal string bypasses that and ships
untranslated (fixed in `sensor.py` for `easy_slot`/`last_error`
2026-07-15/16 — check new sensors/selects for the same pattern).

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

**The devcontainer host needs real Bluetooth hardware reachable from its
Docker daemon** — confirmed 2026-07-15 that it does *not* on a Mac running
the devcontainer via Apple's `container` CLI virtualization (checked:
`/sys/class/bluetooth`, D-Bus, BlueZ all absent in that VM; Apple's
Containerization framework has no USB/device-passthrough flag as of
`container` 1.1.0). Every BLE-dependent config-flow step fails identically
in that setup (`cannot_connect`) — not a MAC/config problem, and not fixable
by Docker flags. Step 2 above needs a devcontainer host with an actual
Bluetooth adapter (a native Linux box, or a Pi) to ever succeed.

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

**`legacy/1.4.x` is a separate, temporary branch** (created 2026-07-15) for
users whose HA can't yet meet the `v1.5.0` line's `2026.8.0.dev*` floor
(the LLM tools platform's HA-version requirement — see that section
below). Branched from the commit right before the LLM-platform merge
(floor `2026.4.0` there), it cherry-picks only the non-LLM fixes/features
from `main` (never the LLM-platform commits themselves, which don't
apply cleanly to that base anyway) and ships its own `v1.4.1-rc.N`
prereleases via `gh release create --target legacy/1.4.x` (release-drafter
only watches `main`, so these are cut manually). Not an ongoing parallel
release line — no new work is developed there, only backports of
already-`main`'d fixes for real-hardware testing before the 2026.8 beta
ships; once it does, `legacy/1.4.x` users switch to tracking `main`'s
`v1.5.0`+ releases and the branch can be retired.

## When in doubt

- Localization broken? Check (2) above before anything else.
- Sensor stuck `unknown`? Check the firmware-quirks section.
- Sensor shows a raw untranslated word (`"none"`, `"unknown"`, an English
  literal) instead of localized Unknown? A property is almost certainly
  returning that literal string instead of Python `None` — see the Entity
  translation flow section's note on this recurring bug shape.
- Tea recipe doing nothing, or steeps flattening into one pour? Tea must go through `brewing._async_brew_tea` (8022 → 8102 → 8104 → 4513 → 4512) — `8004` does not trigger tea mode at all. See the firmware-quirks entry.
- `sensor.state` looks wrong specifically during/right after a real grind (stuck on a stale value, or briefly flips to `idle` mid-brew)? The cmd-tagged `RD_*` path is known-unreliable for the grinding→brewing transition — check `_RAW_STATE_LABEL_MAP` in the firmware-quirks section before assuming a new bug.
- Adding a new entity? Update `strings.json` AND every file under `translations/`. Add an `icons.json` entry. Don't set `_attr_name` or `_attr_icon` on the class.
- Adding a new **device** (not entity)? Same idea, one level up — see the Device registry section.
