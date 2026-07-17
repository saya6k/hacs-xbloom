---
name: xbloom-unit-and-water-source-sync
description: "Display units and water source are bidirectional - cmd 8015 (RD_UNIT_CHANGE) pushes touchscreen-side unit changes to HA, and cmd 4508 actually sets water source on the machine; required adding unit/water-source keys to the no-reload option-change path, and (2026-07-18) a dirty-flag gate so the SET commands only go out on an explicit user change, not on every reconnect."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Implemented 2026-07-17, decompile-verified, **not yet hardware-verified**.
From `DeviceUnitBleModel`: the `8015` payload is three LE uint32s —
[0:4] weight unit (0=g/1=oz/2=ml, same codes as outbound `8005`), [4:8]
temp unit (0=C/1=F, same as `8010`), [8:12] water source (0=tank/1=direct)
— pushed when changed on the machine's own touchscreen (the app bails
below 12 payload bytes; so does this integration). `_client.py` fires it as
a coordinator-internal `("settings", "unit_change")` event (filtered out of
the user-facing event entities, which only surface `error`/`notification`);
`coordinator._async_sync_units_from_machine` folds it into stored
preferences.

**Water source now has a real SET command**: the app's
`BleCodeFactory.switchWaterFeed` sends cmd `4508` with a single LE uint32 —
on Studio the value is `WaterSourceType.ordinal()` (tank=0, direct/TAP=1,
matching `WATER_SOURCE_TANK`/`DIRECT`); the 8/50 values in the same
decompiled helper are J20-only, not applicable here. `select.water_source`
used to be HA-local only (manual-pour payload + shortage gate);
`coordinator.async_set_water_source` now actually sends 4508, and
`_apply_unit_preferences` re-asserts it at connect alongside `8005`/`8010`.

**Required a no-reload fix**: the unit/water-source option keys are now in
`__init__.py`'s `_NO_RELOAD_OPTION_KEYS` — the water-source select's persist
used to full-reload the config entry (dropping BLE) on every change, the
same latent bug shape `CONF_MODE` had before. The no-reload path calls
`coordinator._handle_unit_options_change`, which pushes changed values to
the machine in place and recognizes echoes of the coordinator's own persist
by value equality, so a `8015`-sync → persist → listener chain can't loop.

**Why**: this is the same "full config-entry reload drops the BLE
connection" bug shape as the earlier `CONF_MODE` fix — worth checking
`_NO_RELOAD_OPTION_KEYS` whenever a new machine-pushed setting gets a local
HA counterpart.

**How to apply**: any new bidirectional (machine-pushable) setting must be
added to `_NO_RELOAD_OPTION_KEYS` and routed through the same echo-
recognition pattern, or it will silently drop the connection on every
change from either direction.

**2026-07-18 update — `select.water_source` removed, moved into the
config_flow Settings step (options flow) alongside `weight_unit`/
`temp_unit`; `coordinator.async_set_water_source` was deleted as dead code
once its only caller (the select entity) was gone** — water_source now
follows the exact same path weight_unit/temp_unit always used
(`config_flow.py`'s `async_step_settings` → `entry.options` →
`_handle_unit_options_change`), no dedicated setter method needed.

**Also fixed the same day, hardware-reported: the machine's own
unit-settings screen was popping up first on every single reconnect.**
Root cause: `async_connect()` called `_apply_unit_preferences()`
(8005/8010/4508 SET) unconditionally on every connect, to "re-assert"
the stored preference since the ACKs carry no echoed value. Decompiled
`MachineJ15Fragment`/`ScaleActivity` (`xbloom_coffee_release.apk`,
2026-07-18): the official app only ever sends those three SET commands
from an explicit button tap in its own Settings screen
(`loadListener$3`–`$9`) — never automatically on connect, anywhere in the
app. Receiving one of those SET commands is indistinguishable to the
firmware from a real button tap, so blindly resending them every
reconnect made the machine jump to its own settings screen every time.

Fixed with a `_unit_preferences_dirty` flag (`coordinator/__init__.py`):
`_handle_unit_options_change` sets it only when a Settings-step change
couldn't reach the machine because it was disconnected at the time (the
connected case still pushes immediately — that's the real "explicit user
action" the app's button taps represent); `async_connect()` only calls
`_apply_unit_preferences()` if the flag is set, then clears it. The
machine→HA direction (`_async_sync_units_from_machine`, cmd 8015) is
unaffected — it never sets the flag, since there's nothing to push back
when the machine is the one that just told us its value. Tests:
`tests/test_unit_preferences_dirty.py`. **Not hardware-verified** — the
decompile evidence is about as direct as this integration ever gets (a
1:1 command-id + call-site match with no automatic-send code path
anywhere), but the actual "does the settings screen still pop up"
behavior needs a real reconnect to confirm.
