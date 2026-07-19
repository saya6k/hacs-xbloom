---
name: xbloom-macos-native-ble-testing
description: "BLE hardware testing IS possible on this Mac natively (bleak/CoreBluetooth reaches the machine) — the long-standing 'no Bluetooth in this dev environment' rule applies only to the Docker/VM path; the blockers for full-HA testing on macOS are CoreBluetooth UUIDs vs config_flow's MAC_RE and HA 2026.8 not being on PyPI."
metadata: 
  node_type: memory
  type: project
  originSessionId: efb12ddd-12cd-4a2f-8d7a-a3b406787f12
---

Established 2026-07-19, correcting a long-standing assumption in
`AGENTS.md`'s Testing section ("this dev environment cannot test BLE").
That is true of the **devcontainer/Apple-`container` VM path only** —
re-confirmed the same day: no `/sys/class/bluetooth`, no `/dev/rfkill`,
no `/run/dbus`, and no device-passthrough flag.

**Natively on the Mac, BLE works.** `bleak` 3.0.2 (CoreBluetooth),
`bleak-retry-connector`, `habluetooth` and `bluetooth-adapters` are all
installed in the system Python 3.12, `bluetooth-adapters` enumerates a
`Core Bluetooth` adapter, and a `BleakScanner.discover()` finds the
machine (`XBLOOM 4CV030`). A full connect + 8100 handshake + command
exchange against the real machine succeeds — see
[[xbloom-app-connection-lifecycle-and-page-quit]] for the results.

**The working harness pattern**: use the integration's own
`ble/` package (framing, `Command`, `XBloomClient`, the grinder/brewer
controllers) and swap ONLY the transport — a bare-`BleakClient` class with
the same interface as `HABleakConnection` (`connect`/`disconnect`/
`is_connected`/`write_command`/`start_notify`/`stop_notify`, reusing
`framing.split_write_chunks`). That way the test exercises product code,
not a reimplementation. Tap `client._on_notification` to timestamp raw
frames. Script kept at `scratchpad/hw_verify.py` (session-local; not in
the repo).

**Two blockers remain for running the FULL integration on macOS** (as
opposed to the BLE layer):

1. CoreBluetooth never exposes BLE MAC addresses — devices are identified
   by a per-host UUID (`5E17AC45-8AF9-37F8-387C-34F9F0EF543A`).
   `config_flow.py`'s `MAC_RE` (`^([0-9A-Fa-f]{2}:){5}...`) rejects that
   as `invalid_mac`, and `bluetooth.async_ble_device_from_address()` is
   keyed by MAC too.
2. Local HA is 2025.1.4; the integration's floor is `2026.8.0.dev*`, which
   is not on PyPI (see [[reference-ha-dev-version-channels]]) — a git
   install would be needed.

**Why**: "we can't test BLE here" quietly stopped being true, and it had
been shaping every recommendation to defer verification to a prerelease.

**How to apply**: for anything protocol-level (command accepted? ACK
shape? telemetry cadence? timing?), test it natively on the Mac first —
it's minutes, not a release cycle. Keep using the container for
HA-version-dependent work (the local HA is far below the floor, so the
3 llm-platform tests skip locally and only run there). Physical actions
(anything that grinds, pours, or heats) need the user's go-ahead first —
screen enter/leave commands like 8006/8007/8012/8013/8017 are safe.
