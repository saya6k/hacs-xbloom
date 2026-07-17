---
name: xbloom-device-registry-4way-split
description: "Each config entry registers 4 device-registry entries (main + Grinder/Scale/Brewer via via_device) for a cleaner device page, with no unique_id/entity_id changes; via_device does not propagate translation or area assignment automatically, and the main device must be explicitly registered before platform setup or via_device warnings appear."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

Each config entry has 4 device-registry entries, not 1: the main device
plus Grinder/Scale/Brewer child devices, linked via `via_device`
(`coordinator.grinder_device_info`/`scale_device_info`/`brewer_device_info`,
backed by `_sub_device_info()`). `unique_id`s are untouched — pure
device-page regrouping, no entity_id/automation breakage. Deliberately not
HA's "config subentries" feature (that's for dynamically add/removable
child items — wrong fit for fixed sub-components of one physical machine).

Two things `via_device` does **not** give for free, both hardware-confirmed
2026-07-15/16:

- **Translation**: a literal `name=` on child `DeviceInfo` ships
  English-only device names regardless of HA UI language. Needs
  `translation_key` + a top-level `device.<key>.name` block in
  `strings.json`/`translations/*.json` — the device-level analogue of the
  entity translation flow.
- **Area assignment**: setting the main device's area does not propagate to
  its `via_device`-linked children — each device's `area_id` is
  independent. `_sub_device_info()` passes `suggested_area` (the main
  device's *current* area, looked up via device/area registry) so newly-
  created sub-devices default into the same area, without forcing ongoing
  sync — a later manual change on either device is left alone.

**Registration order matters**: `async_forward_entry_setups` fans platforms
out concurrently, so entity registration order isn't fixed — if a platform
whose entities all point at a sub-device (e.g. `binary_sensor.py`, all
Grinder/Brewer/Scale) happens to register before any main-device entity
does, HA logs a "non existing via_device" warning (confirmed live). Fixed
by `__init__.py`'s `async_setup_entry` calling
`device_registry.async_get_or_create()` for the main device explicitly,
before `async_forward_entry_setups`.

**Why**: `via_device` handles the device-page hierarchy but nothing else —
easy to assume it's a complete solution when it only solves grouping.

**How to apply**: any new sub-device must use `translation_key` (never a
literal `name`) and get its `suggested_area` from `_sub_device_info()`'s
existing pattern. If a "non existing via_device" warning ever reappears,
check platform registration order before assuming a new bug.
