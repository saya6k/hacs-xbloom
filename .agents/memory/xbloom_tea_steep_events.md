---
name: xbloom-tea-steep-events
description: "Tea steeps end on RD_TEA_RECIP_PAUSE (40515) -> \"paused\" or RD_ENJOY (40512) -> \"recipe_complete\", and resume on RD_TEA_RECIP_RESTART (9011) -> \"tea_resumed\"; every event type fired in _client.py must also be registered in event.py and all three translation files or HA raises on the unregistered type at runtime."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

The firmware fires `RD_TEA_RECIP_PAUSE` (40515)/`RD_TEA_RECIP_RESTART`
(9011) between steeps inside one tea recipe — entities can listen via the
event bus rather than orchestrating per-steep. `9011`'s handling
(added 2026-07-17) matches the official app's `TeaRestartBleModel`: a bare
notification, no payload.

**A general invariant this surfaced**: every event type fired anywhere in
`_client.py`'s `_NOTIFICATION_MAP`/`_ERROR_MAP` must also be present in
`event.py`'s `NOTIFICATION_EVENT_TYPES`/`ERROR_EVENT_TYPES` **and** all
three translation files (`strings.json`, `translations/en.json`,
`translations/ko.json`). HA's `EventEntity._trigger_event` raises on an
unregistered type — this bit the integration live with
`tea_soak_time_changed`, which was added to `_NOTIFICATION_MAP` but never
registered anywhere else. `tests/test_event_type_registration.py` now pins
this invariant so it fails CI instead of shipping.

**Why**: this is a narrow but easy-to-miss failure mode — adding a new
notification mapping in `_client.py` alone looks complete but crashes the
event entity at runtime the moment that event actually fires.

**How to apply**: any new entry added to `_NOTIFICATION_MAP`/`_ERROR_MAP`
must be added to `event.py` and all three translation files in the same
change, or `test_event_type_registration.py` will (correctly) fail.
