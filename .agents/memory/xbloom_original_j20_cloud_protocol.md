---
name: xbloom-original-j20-cloud-protocol
description: "XBloom Original = J20 = Wi-Fi + AWS IoT thing-shadow cloud protocol, no BLE control path; fully documented in docs/*/protocol-original-j20.md."
metadata: 
  node_type: memory
  type: project
  originSessionId: 33a80524-3a0d-43b5-81e3-0b3d55205e70
---

XBloom **Original** is device type **J20** (`DeviceType.DeviceJ20 = 2`,
`productId "53DDY4"`); Studio is **J15** (`= 1`, matches cloud `adaptedModel: 1`).
Confirmed by decompiling `xbloom_coffee_release.apk` (pkg `com.chisalsoft.andite`)
2026-07-18.

**Original is NOT a BLE machine.** Its only BLE use is Wi-Fi onboarding via
MXChip's `com.mxchip.locklib.BleLockManager` (pushes `WifiBean{ssid,password,token}`),
never this app's own BLE stack. All control is cloud-mediated over an **AWS IoT
thing-shadow** pattern on `api-iot.xbloom.com` (China: `api-iot.xbloomcoffee.cn`):

- Write: `POST /api/device/command` body `DeviceCommandReq{device_id, product_id:"53DDY4", desired, home_id:null}` where `desired = {state:{desired:{...}}}`. Grind = `{grinding_start:1, setting_grind_size:N}`; calibrate = `{auto_calibrate:1}`; pour = `{bruw_curve:"FFFF1005<hex><hex>1E<outWaterType>"}`; stop = `{bruw_curve:"FFFF11"}`.
- Read snapshot: `POST /api/device/thing_shadow/`; `GET /api/device/detail/`.
- Live state: WebSocket (`AppWsManager` + vendored `com.mixchip.websocketclient`) pushing `state.reported.{is_online,work_mode,warning,grinding_start,auto_calibrate,capsule_rfid_tag,disp_reserve}`.
- Auth: shared signed-header scheme (`appid`/`ts`/`nonce`/`Authorization: token`), same OkHttp `TokenInterceptor` as J15.

**Why:** confirms `AGENTS.md` hard rule #6 with evidence — Original support is a
second cloud-only integration (shape of `_cloud_client.py`, not `ble/`), sharing
zero transport surface with Studio. Not a flag on the BLE coordinator.

**How to apply:** if anyone asks to "add Original support," point them at
`docs/en/protocol-original-j20.md` (full decompile-derived map, everything marked
unverified — no Original hardware exists to test). Unknowns still blocked without
hardware: exact request-signing input, WebSocket URL/handshake, `bruw_curve` hex
encoding, `setting_grind_size` range, full `warning`/`work_mode` code tables.
Related: [[xbloom-collective-hub-and-backend-api]] (analogous signing),
[[xbloom-raw-state-heartbeat-vs-cmd-tagged]] (reported-state-is-truth parallel).
