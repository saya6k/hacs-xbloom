# XBloom Original (J20) cloud protocol reference

> Source of truth — see [한국어](../ko/protocol-original-j20.md) for the Korean
> translation (may lag). Written entirely from statically decompiling the
> official Android app (`xbloom_coffee_release.apk`, package
> `com.chisalsoft.andite`, via `jadx` — inspected as a zip/dex/source dump
> only, never published or redistributed). **Unlike [`protocol.md`](./protocol.md)
> (Studio BLE), nothing here has been verified against real hardware** — this
> integration has no XBloom Original unit, does not implement Original, and
> Original is out of scope per `AGENTS.md` hard rule #6. This is a decompile-
> derived map kept so a future contributor with Original hardware has a
> starting point, not a spec this integration follows. Every claim traces to a
> specific class/method; anything not cross-checked is marked unconfirmed.

## Why Original is a separate document

The app internally splits the two machines by a `DeviceType` int
(`constant/DeviceType.java`):

| `DeviceType` | value | product | `productId` | transport |
|---|---|---|---|---|
| `DeviceJ15` | `1` | **Studio** | — | Bluetooth LE (see [`protocol.md`](./protocol.md)) |
| `DeviceJ20` | `2` | **Original** | `"53DDY4"` | Wi-Fi + cloud IoT thing-shadow |

`DeviceJ15 == 1` lines up with the cloud API's hardcoded `adaptedModel: 1`
(Studio). The two share almost nothing at the transport layer: every J20 screen,
scan flow, and networking class is a parallel `*J20*` sibling of the Studio one
(`MachineJ20Fragment`, `PairDeviceJ20Activity`, `BrewerJ20Activity`,
`GrinderJ20Activity`, `AutoJ20Activity`, `J20ScanVM`, …). **There is no BLE
brew/grind/pour command path for Original at all** — see "Relationship to the
Studio BLE protocol" at the bottom for why none of this integration's BLE stack
is reusable.

## Architecture: Wi-Fi + AWS IoT thing shadow

Original is a Wi-Fi appliance controlled through XBloom's cloud, not directly.
The pattern is a classic AWS IoT **thing shadow** (a.k.a. device shadow):

1. The app never sends a brew/grind command to the machine directly. It `POST`s
   a **desired state** document to the cloud (`/api/device/command`).
2. The cloud relays the desired state to the machine over its own IoT/MQTT link.
3. The machine reports back its **reported state**, which the cloud fans out to
   the app over a **WebSocket** as `state.reported.{...}` JSON.

So a HA integration for Original would be a **cloud polling/streaming client**,
not a Bluetooth client — closer in shape to `_cloud_client.py` than to
`ble/` or `coordinator/connection.py`.

## Hosts and auth

The IoT backend base URL is chosen by `ServiceConfig` (global vs. China),
`AboutActivity` confirms the global default:

- **Global**: `https://api-iot.xbloom.com/`
- **China**: `https://api-iot.xbloomcoffee.cn/`
- **WebSocket**: `ServiceConfig.getWebSocketUrl()` (host not string-literal in the
  decompile; resolved from the same config object — **unconfirmed exact URL**)

Auth is the same signed-header scheme the rest of the app uses
(`http/j15/RetrofitManager2.java`, a `TokenInterceptor` on the shared OkHttp
client — J20's `ApiDevice` rides the same manager):

```
platform: android
appid: <ServiceConfig.getAppId()>
version: <app version>
ts: <epoch millis>
nonce: <random, lowercased>
accept-language: <locale>
Authorization: token <bearer token>
```

`ts` + `nonce` + `appid` indicate an HMAC-style request signature (exact signing
input **unconfirmed** — the interceptor body wasn't fully traced here; the
Studio-side memory `[[xbloom-collective-hub-and-backend-api]]` documents the
analogous `backend-api.xbloom.com` signing scheme and is the closest lead).

## Onboarding / pairing (the only BLE that Original uses)

BLE appears exactly once for Original: handing Wi-Fi credentials to a factory-
fresh machine. `SetWifiActivity` collects SSID + password, then
`PairDeviceJ20Activity.startConn()` pushes them over BLE using MXChip's lock
SDK (`com.mxchip.locklib.BleLockManager`), **not** this app's own BLE stack:

```java
// PairDeviceJ20Activity.java ~line 207
WifiBean wifiBean = new WifiBean(
    new WifiInfoBean(wifiSSID, "", "", wifiPassword, token), null, 2, null);
BleLockManager.getInstance().connect(retrofit, deviceFindBean.getBean(), wifiBean, cb);
```

A cloud `token` is bundled with the credentials so the device can authenticate
to the IoT backend once it joins Wi-Fi. After provisioning, BLE is never used
again — all control is cloud-mediated.

## REST endpoints (`http/j20/ApiDevice.java`)

```
POST /api/device/command        body: DeviceCommandReq          → BaseResp<Object>
GET  /api/device/detail/        query: device_id                → BaseResp<DeviceJ20InfoDetailModel>
POST /api/device/thing_shadow/  body: { device_id, product_id } → BaseResp<DeviceJ20DetailModel>
```

- **`/command`** — push a desired-state shadow update (the write path).
- **`/detail/`** — one-shot device metadata (`sn`, `device_id`).
- **`/thing_shadow/`** — full current shadow (the reported-state read path,
  `deviceFullProperties`); used for the initial snapshot before the WebSocket
  takes over for live updates.

## Command model (the write path)

`req/DeviceCommandReq.java` — the POST body for `/api/device/command`:

```
DeviceCommandReq {
  device_id:  <device.deviceId>
  product_id: "53DDY4"            // DeviceType.getJ20ProductId(), constant
  desired:    <shadow document>   // see below
  home_id:    null                // observed null at every call site
}
```

The `desired` object is a nested AWS-IoT shadow document —
`model/Desired.java` → `State` → `BaseDesiredInside` — serializing to:

```json
{ "state": { "desired": { <one of the *DesiredInside payloads> } } }
```

Confirmed payload shapes (each `*DesiredInside` extends `BaseDesiredInside`), with
the call site that builds them:

| Action | Desired payload | Built at |
|---|---|---|
| **Grind** | `{ "grinding_start": 1, "setting_grind_size": <int> }` | `GrinderJ20Activity` L374 |
| **Grinder calibrate** (auto-zero) | `{ "auto_calibrate": 1 }` | `CalibrateGrinderJ20Activity` L84 |
| **Pour / brew** | `{ "bruw_curve": "FFFF1005<hex><hex>1E<outWaterType>" }` | `BrewerJ20Activity` L852 |
| **Stop water** | `{ "bruw_curve": "FFFF11" }` | `BrewerJ20Activity` L878 |

Notes:

- `setting_grind_size` is the grind number parsed straight from the UI text
  field (same 0–x scale the Studio grinder uses — **exact range unconfirmed**).
- `bruw_curve` (sic — the app's own typo for "brew curve") is a hex string, not
  a struct. The `"FFFF1005" + <two hex fields> + "1E" + outWaterType` layout
  encodes the pour; the two middle hex fields are computed from pour
  volume/temperature UI values (`upperCase`/`upperCase2` locals — **exact
  encoding unconfirmed**). `"1E"` = 30 is a fixed literal in the observed
  builder. `"FFFF11"` is the stop sentinel.
- `home_id` is a data-class field but null at all traced call sites.

## State / telemetry (the read path)

`manager/AppWsManager.java` opens the WebSocket and parses each frame's
`state.reported` object, re-broadcasting fields onto the app's `RxBus`. The
reported fields it handles (the de-facto Original telemetry schema):

| `state.reported.*` | meaning | notes |
|---|---|---|
| `is_online` | machine online flag | → `DeviceJ20OnlineEvent` |
| `work_mode` | power/wake + activity state | → `DeviceJ20SleepingEvent`; `==5` pod-inserted (carries `capsule_rfid_tag`), `==7` handled in `AppJ20AutoManager`, wake mapping via `isJ20WakeUp` |
| `warning` | error/warning code | → `DeviceJ20WarningEvent`; observed codes `162 / 169 / 171 / 176 / 182` branch specially (**meanings unconfirmed**), `182` = auto-flow finish |
| `grinding_start` | grinder run state | → `DeviceJ20GrinderStartEvent` |
| `auto_calibrate` | calibration state | mirrors the calibrate command field |
| `capsule_rfid_tag` | inserted pod's RFID/`xid` | `"IF0002"` treated as "no pod"; other values open the pod detail page |
| `disp_reserve` | dispense/brew progress | `<3` brew-progress (0/1/2), `3` recipe-changed, `4` start Easy-Mode recipe, `6` idle/ignore |

- The reported state is the reliable status source — same lesson as Studio's raw
  status heartbeat vs. cmd-tagged frames (`[[xbloom-raw-state-heartbeat-vs-cmd-tagged]]`).
- `thing_shadow/` gives the initial full snapshot; the WebSocket gives deltas.
- Corresponding models: `model/DeviceJ20DetailModel.java`
  (`capsule_rfid_tag`, `is_online`, `warning`, `work_mode`, `DM_SN`,
  `multimcuotainfo` → per-MCU `mcu_name`/`mcu_version`), `DeviceJ20Model.java`
  (`product_id`, `mac`, `device_id`, `enduser_id`, `sn`).

## Relationship to the Studio BLE protocol — none of it ports

For anyone tempted to add Original as a flag on the existing code path: the two
share **no transport surface**.

| Concern | Studio (J15, this integration) | Original (J20) |
|---|---|---|
| Link | Bluetooth LE via HA Bluetooth stack | Wi-Fi, cloud-mediated |
| Framing | `0x58 0x02` packets, CRC, MTU `8100` handshake | JSON over HTTPS + WebSocket |
| Command table | `APP_*`/`RD_*` ids, type-1/type-2 markers | shadow `desired` documents |
| State | raw BLE status heartbeat | cloud `state.reported` push |
| Auth | none (local BLE) | signed cloud token per request |
| HA building block | `bluetooth` matcher + `coordinator/connection.py` | a cloud stream client (`DataUpdateCoordinator` polling `thing_shadow` + WS) |

So Original support is effectively a **second, cloud-only integration** sharing
only the recipe store and the `_cloud_client.py`-style HTTP plumbing — not a
small branch on the BLE coordinator. This is exactly what `AGENTS.md` hard rule
#6 anticipated; this document is the evidence behind that decision, not a plan to
reverse it.

## Open questions (blocked without Original hardware)

- Exact request-signing input for `api-iot.xbloom.com` (the `ts`/`nonce`/`appid`
  HMAC).
- The WebSocket URL, subprotocol, subscribe/auth handshake, and reconnect/ping
  cadence (`WsManager` is a vendored `com.mixchip.websocketclient`).
- `bruw_curve` hex encoding (how pour volume / temperature / water source map
  into the two middle hex fields and `outWaterType`).
- `setting_grind_size` valid range and whether it matches Studio's scale.
- Full `warning` and `work_mode` code tables.
- Whether tea recipes have a J20 desired-state form at all.
