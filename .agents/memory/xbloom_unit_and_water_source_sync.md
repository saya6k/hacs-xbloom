---
name: xbloom-unit-and-water-source-sync
description: "Display units and water source are bidirectional - cmd 8015 (RD_UNIT_CHANGE) pushes touchscreen-side unit changes to HA, and cmd 4508 actually sets water source on the machine (previously HA-local only); required adding unit/water-source keys to the no-reload option-change path to avoid dropping the BLE connection on every change."
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
