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

**A full native HA 2026.8 env now exists** (built 2026-07-19):
`/opt/homebrew/bin/python3.14 -m venv <scratch>/ha314` +
`pip install git+https://github.com/home-assistant/core.git@dev` →
`homeassistant 2026.8.0.dev0`. A git install ships core only, so
per-integration runtime deps must be added by hand — `aiousbwatcher`,
`serialx`, `aioesphomeapi` were the three needed here. With those,
`pytest tests/` runs **253 passed, 0 skipped** natively (the 3 llm-platform
tests gate on `importorskip("homeassistant.components.llm")`, not a
version string, so `2026.8.0.dev0` satisfies them).

**Full-stack native testing now WORKS, with a 2-line shim** (2026-07-19).
Real HA + real machine + real entities/services, 30/30 checks. Driver kept at
`scratchpad/verify_all.py` (session-local). Two macOS-only seams must be
bridged, both symptoms of the same root cause (habluetooth never sees an
advertisement on macOS):

1. `bluetooth.async_ble_device_from_address` → fall back to a bare
   `BleakScanner.discover()` cache. **Rebuild the `BLEDevice`**: CoreBluetooth
   hands back an `objc.pyobjc_unicode` address that `establish_connection`
   rejects with "incorrect type (expected str)". bleak 3.x's constructor is
   `BLEDevice(address, name, details)` — passing a 4th positional `rssi`
   raises `TypeError` (silently, if your scan loop swallows exceptions).
2. `bleak_retry_connector.establish_connection` → falls back to a direct
   `BleakClient.connect()`. Its slot manager refuses first with
   "No backend with an available connection slot … never seen by any
   scanner", since habluetooth's registry is empty.

So the bleak-retry-connector layer specifically is the *only* thing that
stays unexercised natively; everything above it is real.

Harness gotchas that cost a rerun each: HA refuses to start if a previous
instance is alive (`pkill -9 -f <script>` and confirm with `pgrep` before
relaunching, or you will read a stale process's output and think your edits
did nothing), and `button.execute_recipe` correctly refuses to arm with no
recipe selected — select one first or you get a false failure.

**Earlier finding, now superseded by the shim above** — kept because the
underlying HA behavior is unchanged:

- `config_flow.py`'s `MAC_RE` is NOT the blocker it looked like. Only the
  manual user step applies it; `async_step_bluetooth()` takes
  `discovery_info.address` verbatim, so a CoreBluetooth UUID would flow
  through the discovery path unmodified.
- Real HA boots fine on macOS with the integration installed (recipes
  seed, LLM API registers, coordinator polls) and its `bluetooth`
  component **does** set up, creating an
  `Apple Unknown MacOS Model (Core Bluetooth)` config entry.
- **But HA's bluetooth manager delivers no advertisements on macOS.** The
  only related log line is
  `ERROR bleak_retry_connector.bluez: Failed to stop discovery for Core
  Bluetooth because no manager` (a BlueZ code path on a non-BlueZ host),
  and `bluetooth.async_ble_device_from_address()` returns `None` forever:
  `XBloom device <uuid> not found via HA Bluetooth`, retried every 5s.
  Bare `bleak` in the same OS reaches the machine perfectly. So the
  `HABleakConnection` seam specifically is what can't be exercised here —
  everything above it can.

**Why**: "we can't test BLE here" quietly stopped being true, and it had
been shaping every recommendation to defer verification to a prerelease.

**How to apply**: for anything protocol-level (command accepted? ACK
shape? telemetry cadence? timing?), test it natively on the Mac first —
it's minutes, not a release cycle. Keep using the container for
HA-version-dependent work (the local HA is far below the floor, so the
3 llm-platform tests skip locally and only run there). Physical actions
(anything that grinds, pours, or heats) need the user's go-ahead first —
screen enter/leave commands like 8006/8007/8012/8013/8017 are safe.
