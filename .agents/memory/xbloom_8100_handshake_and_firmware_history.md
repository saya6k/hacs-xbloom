---
name: xbloom-8100-handshake-and-firmware-history
description: "The 8100 MTU handshake gates all XBloom BLE commands; cross-verified independently via a second APK; firmware version history D122->D500 confirmed via Zendesk + official app's own update-check endpoint (md5-matched)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 04d79599-66b2-466f-af60-c5174f4dfda7
---

The XBloom Studio machine ignores every BLE command — no display wake, no
LED, no `RD_MachineInfo` (40521) — until it receives `8100`
(`build_packet_type1(8100, [185, 1])`). The vendored `XBloomClient.connect`
sends `APP_RECIPE_STOP`/`BREWER_QUIT`/`GRINDER_QUIT` but never `8100`, so on
strict firmwares MachineInfo never fires. `_client.XBloomClientWithEvents.
_reset_state` sends `8100` first; `coordinator._machine_info_retry_loop`
re-sends the handshake (not `APP_RECIPE_STOP`) when MachineInfo hasn't
arrived.

**Independently cross-verified** (2026-07-16) via a *second*, unrelated
reverse-engineering effort: `cryptofishbug/xbloom-recipe-cli`'s firmware
switcher APK (`xbloom-firmware-switcher-release_Compatibility.apk`,
inspected as a zip/dex string dump only, never installed/run) names this
exact command `PACKET_8100` and logs the same "session primer"/"ACK, session
ready" role. A follow-on `PACKET_8101` puts the machine into YMODEM
firmware-receive mode for OTA — out of scope for this integration, which
never flashes firmware, but worth knowing if `8101` ever shows up in a
capture.

**Firmware version history**, confirmed two independent ways: xBloom's own
Zendesk "Firmware Update Summary" article gives `V12.0D.122` (2024-07-12) →
`V12.0D.210` (2024-12-24, introduces Auto/Easy Mode — cmds `11510`/`11511`/
`11512` don't exist before this) → `V12.0D.300` (2025-03-20, introduces tea
recipes — cmds `4512`/`4513` don't exist before this) → `V12.0D.400`
(2025-07-02, tea steep to 360s + multi-temp brewing). No official `.410`
article exists — the switcher app's own notes say `.410` is what public
notes call `D400`. The `.500` build (uncovered by Zendesk) was confirmed by
calling the **official app's own live update-check endpoint**
(`tUpToDateFirmwareVersion.thtml` on `client-api.xbloom.com`, no login) —
its returned `md5_string` matched the switcher app's bundled `.500` file
byte-for-byte, confirming it as a genuine unmodified release.

**Why**: without the handshake, every other command (and this integration's
core connect-time telemetry) silently no-ops with no error — the single
highest-leverage protocol fact in the whole codebase.

**How to apply**: any new command that appears to be ignored on connect —
check the handshake has actually landed before assuming the command itself
is wrong. Firmware-gated features (Easy Mode, tea) should check
`_firmware_at_least()` against the version table above rather than assuming
availability. See [[xbloom-machineinfo-reliability-and-padding]] for what
happens when MachineInfo still doesn't arrive after the handshake.
