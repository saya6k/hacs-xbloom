---
name: xbloom-machineinfo-reliability-and-padding
description: "RD_MachineInfo (40521) can arrive late or never on some firmwares; three fallback layers exist; its string fields are 0xFF-padded not NUL-padded, requiring strict_ascii() decoding."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

`RD_MachineInfo` (cmd 40521) may still arrive late or not at all on some
firmwares even after the [[xbloom-8100-handshake-and-firmware-history]]
handshake lands. Three fallback layers exist: the retry loop in
`coordinator.py:_machine_info_retry_loop`, a manual-signature scanner in
`_client.py:_scan_for_machine_info` (scans raw notification bytes for the
cmd-id signature directly, recovering serial/firmware even when the
vendored length-based parser bails on a corrupt-looking length field), and
a GATT 180A read fallback. If all three fail, Model/Serial/Firmware sensors
stay `unknown`.

`_status.water_level_ok` is set only inside the `RD_MachineInfo` handler
(`src/xbloom/core/client.py:272`) from a connect-time snapshot, so it can
never self-correct mid-session. This eventually led to a real bug — see
[[xbloom-water-shortage-and-level-derivation]] — where trusting this raw
flag caused a permanent false "problem" reading; the coordinator no longer
reads it at all, deriving water state purely from the event-driven
water-shortage flag instead.

**String field padding**: `theModel`'s payload slice is filled with `0xFF`
on machines that don't populate it. A naive `decode('utf-8',
errors='ignore')` lets `0xFF` runs through whenever they form valid UTF-8
sequences with neighboring bytes, producing garbage in the Model sensor.
Always run MachineInfo / GATT 180A bytes through `_client.strict_ascii()`
(printable 0x20–0x7E only), cherry-picked from
`src/xbloom-ble/python/xbloom.py:_handshake_notify._hex_ascii`.

**Why**: MachineInfo is the only connect-time source for serial/firmware/
mode/grind-size/voltage — its unreliability on some units is why so much of
this integration has fallback logic layered on top of a single expected
notification.

**How to apply**: never assume a naive UTF-8 decode is safe for any
fixed-width string field in this protocol — check for `strict_ascii()`
first. If a new sensor reads `unknown` specifically on a machine that
otherwise connects fine, suspect MachineInfo non-arrival before assuming a
new bug.
