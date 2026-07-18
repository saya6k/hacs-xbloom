# XBloom Original (J20) 클라우드 프로토콜 레퍼런스

> 이 페이지는 [`en/protocol-original-j20.md`](../en/protocol-original-j20.md)의
> 번역본입니다. 영문판이 source of truth이며, 한글본은 뒤늦게 동기화될 수
> 있습니다. 이 문서는 전적으로 공식 안드로이드 앱
> (`xbloom_coffee_release.apk`, 패키지 `com.chisalsoft.andite`)을 `jadx`로
> 정적 디컴파일한 결과(zip/dex/소스 덤프로만 확인 — 배포·재배포된 적 없음)를
> 바탕으로 작성되었습니다. **[`protocol.md`](./protocol.md)(Studio BLE)와 달리,
> 여기 내용은 실기로 검증된 것이 하나도 없습니다** — 이 통합은 XBloom Original
> 기기가 없고, Original을 구현하지 않으며, `AGENTS.md` 하드룰 #6에 따라
> Original은 범위 밖입니다. 이 문서는 나중에 Original 하드웨어를 가진
> 기여자가 출발점으로 쓸 수 있도록 남기는 디컴파일 기반 지도이지, 이 통합이
> 따르는 스펙이 아닙니다. 모든 주장은 특정 클래스/메서드로 추적 가능하며,
> 교차 확인되지 않은 내용은 unconfirmed로 표시했습니다.

## Original이 별도 문서인 이유

앱은 내부적으로 두 기기를 `DeviceType` 정수로 구분합니다
(`constant/DeviceType.java`):

| `DeviceType` | 값 | 제품 | `productId` | 전송 방식 |
|---|---|---|---|---|
| `DeviceJ15` | `1` | **Studio** | — | Bluetooth LE ([`protocol.md`](./protocol.md) 참조) |
| `DeviceJ20` | `2` | **Original** | `"53DDY4"` | Wi-Fi + 클라우드 IoT thing-shadow |

`DeviceJ15 == 1`은 클라우드 API에 하드코딩된 `adaptedModel: 1`(Studio)과
일치합니다. 두 기기는 전송 계층에서 공유하는 것이 거의 없습니다 — 모든 J20
화면, 스캔 플로우, 네트워킹 클래스가 Studio 쪽의 병렬 `*J20*` 형제입니다
(`MachineJ20Fragment`, `PairDeviceJ20Activity`, `BrewerJ20Activity`,
`GrinderJ20Activity`, `AutoJ20Activity`, `J20ScanVM`, …). **Original에는 BLE
brew/grind/pour 명령 경로가 아예 없습니다** — 이 통합의 BLE 스택 중 재사용
가능한 것이 왜 하나도 없는지는 맨 아래 "Studio BLE 프로토콜과의 관계" 참조.

## 아키텍처: Wi-Fi + AWS IoT thing shadow

Original은 직접 제어가 아니라 XBloom 클라우드를 통해 제어되는 Wi-Fi
가전입니다. 전형적인 AWS IoT **thing shadow**(디바이스 섀도우) 패턴입니다:

1. 앱은 기기에 brew/grind 명령을 직접 보내지 않습니다. **원하는 상태(desired
   state)** 문서를 클라우드로 `POST`합니다(`/api/device/command`).
2. 클라우드가 그 desired 상태를 자체 IoT/MQTT 링크로 기기에 전달합니다.
3. 기기는 **보고 상태(reported state)**를 되돌려주고, 클라우드는 이를
   **WebSocket**으로 `state.reported.{...}` JSON 형태로 앱에 팬아웃합니다.

즉 Original용 HA 통합은 Bluetooth 클라이언트가 아니라 **클라우드
폴링/스트리밍 클라이언트**가 됩니다 — `ble/`나 `coordinator/connection.py`보다
`_cloud_client.py`에 훨씬 가까운 형태입니다.

## 호스트와 인증

IoT 백엔드 베이스 URL은 `ServiceConfig`(글로벌 vs 중국)가 선택하며,
`AboutActivity`가 글로벌 기본값을 확인해 줍니다:

- **글로벌**: `https://api-iot.xbloom.com/`
- **중국**: `https://api-iot.xbloomcoffee.cn/`
- **WebSocket**: `ServiceConfig.getWebSocketUrl()` (호스트가 디컴파일에서 문자열
  리터럴로 안 나옴 — 같은 config 객체에서 해석됨, **정확한 URL unconfirmed**)

인증은 앱의 나머지 부분이 쓰는 것과 동일한 서명 헤더 스킴입니다
(`http/j15/RetrofitManager2.java`, 공유 OkHttp 클라이언트의 `TokenInterceptor`
— J20의 `ApiDevice`도 같은 매니저를 탑니다):

```
platform: android
appid: <ServiceConfig.getAppId()>
version: <앱 버전>
ts: <epoch millis>
nonce: <랜덤, 소문자화>
accept-language: <로케일>
Authorization: token <bearer 토큰>
```

`ts` + `nonce` + `appid` 조합은 HMAC 방식 요청 서명을 시사합니다(정확한 서명
입력은 **unconfirmed** — 인터셉터 본문은 여기서 완전히 추적하지 않음.
Studio 쪽 메모리 `[[xbloom-collective-hub-and-backend-api]]`가 유사한
`backend-api.xbloom.com` 서명 스킴을 문서화하고 있으며 가장 가까운 단서입니다).

## 온보딩 / 페어링 (Original이 BLE를 쓰는 유일한 곳)

Original에서 BLE는 딱 한 번 등장합니다: 공장 초기 상태의 기기에 Wi-Fi
자격증명을 넘겨줄 때입니다. `SetWifiActivity`가 SSID + 비밀번호를 수집한 뒤,
`PairDeviceJ20Activity.startConn()`이 이 앱 자체 BLE 스택이 **아니라** MXChip의
lock SDK(`com.mxchip.locklib.BleLockManager`)로 그것을 BLE로 밀어 넣습니다:

```java
// PairDeviceJ20Activity.java ~207행
WifiBean wifiBean = new WifiBean(
    new WifiInfoBean(wifiSSID, "", "", wifiPassword, token), null, 2, null);
BleLockManager.getInstance().connect(retrofit, deviceFindBean.getBean(), wifiBean, cb);
```

기기가 Wi-Fi에 붙은 뒤 IoT 백엔드에 인증할 수 있도록 클라우드 `token`이
자격증명과 함께 번들됩니다. 프로비저닝 후 BLE는 다시는 사용되지 않으며, 모든
제어는 클라우드를 경유합니다.

## REST 엔드포인트 (`http/j20/ApiDevice.java`)

```
POST /api/device/command        body: DeviceCommandReq          → BaseResp<Object>
GET  /api/device/detail/        query: device_id                → BaseResp<DeviceJ20InfoDetailModel>
POST /api/device/thing_shadow/  body: { device_id, product_id } → BaseResp<DeviceJ20DetailModel>
```

- **`/command`** — desired-state 섀도우 업데이트 푸시(쓰기 경로).
- **`/detail/`** — 일회성 기기 메타데이터(`sn`, `device_id`).
- **`/thing_shadow/`** — 전체 현재 섀도우(보고 상태 읽기 경로,
  `deviceFullProperties`); WebSocket이 실시간 갱신을 넘겨받기 전 초기 스냅샷용.

## 명령 모델 (쓰기 경로)

`req/DeviceCommandReq.java` — `/api/device/command`의 POST 본문:

```
DeviceCommandReq {
  device_id:  <device.deviceId>
  product_id: "53DDY4"            // DeviceType.getJ20ProductId(), 상수
  desired:    <섀도우 문서>        // 아래 참조
  home_id:    null                // 모든 호출 지점에서 null 관측
}
```

`desired` 객체는 중첩된 AWS-IoT 섀도우 문서입니다 —
`model/Desired.java` → `State` → `BaseDesiredInside` — 다음으로 직렬화됩니다:

```json
{ "state": { "desired": { <아래 *DesiredInside 페이로드 중 하나> } } }
```

확인된 페이로드 형태(각 `*DesiredInside`는 `BaseDesiredInside`를 상속)와 이를
구성하는 호출 지점:

| 동작 | Desired 페이로드 | 구성 위치 |
|---|---|---|
| **분쇄(Grind)** | `{ "grinding_start": 1, "setting_grind_size": <int> }` | `GrinderJ20Activity` L374 |
| **그라인더 캘리브레이션**(오토 제로) | `{ "auto_calibrate": 1 }` | `CalibrateGrinderJ20Activity` L84 |
| **추출(Pour/brew)** | `{ "bruw_curve": "FFFF1005<hex><hex>1E<outWaterType>" }` | `BrewerJ20Activity` L852 |
| **급수 정지** | `{ "bruw_curve": "FFFF11" }` | `BrewerJ20Activity` L878 |

참고:

- `setting_grind_size`는 UI 텍스트 필드에서 바로 파싱한 분쇄 숫자입니다(Studio
  그라인더와 같은 0–x 스케일 — **정확한 범위 unconfirmed**).
- `bruw_curve`(sic — 앱 자체의 "brew curve" 오타)는 구조체가 아니라 hex
  문자열입니다. `"FFFF1005" + <hex 필드 2개> + "1E" + outWaterType` 레이아웃이
  추출을 인코딩하며, 중간 hex 필드 2개는 추출 양/온도 UI 값에서 계산됩니다
  (`upperCase`/`upperCase2` 로컬 변수 — **정확한 인코딩 unconfirmed**). `"1E"` =
  30은 관측된 빌더의 고정 리터럴입니다. `"FFFF11"`은 정지 센티넬입니다.
- `home_id`는 data 클래스 필드지만 추적된 모든 호출 지점에서 null입니다.

## 상태 / 텔레메트리 (읽기 경로)

`manager/AppWsManager.java`가 WebSocket을 열고 각 프레임의 `state.reported`
객체를 파싱하여 필드들을 앱의 `RxBus`로 재방송합니다. 이것이 처리하는 보고
필드들(사실상의 Original 텔레메트리 스키마):

| `state.reported.*` | 의미 | 비고 |
|---|---|---|
| `is_online` | 기기 온라인 플래그 | → `DeviceJ20OnlineEvent` |
| `work_mode` | 전원/깨어남 + 활동 상태 | → `DeviceJ20SleepingEvent`; `==5` 팟 삽입(`capsule_rfid_tag` 동반), `==7` `AppJ20AutoManager`에서 처리, 깨어남 판정은 `isJ20WakeUp` |
| `warning` | 오류/경고 코드 | → `DeviceJ20WarningEvent`; 관측 코드 `162 / 169 / 171 / 176 / 182`가 특수 분기(**의미 unconfirmed**), `182`는 오토 플로우 완료 |
| `grinding_start` | 그라인더 동작 상태 | → `DeviceJ20GrinderStartEvent` |
| `auto_calibrate` | 캘리브레이션 상태 | 캘리브레이션 명령 필드와 대칭 |
| `capsule_rfid_tag` | 삽입된 팟의 RFID/`xid` | `"IF0002"`는 "팟 없음"으로 취급, 다른 값은 팟 상세 페이지를 엶 |
| `disp_reserve` | 급수/추출 진행도 | `<3` 추출 진행(0/1/2), `3` 레시피 변경됨, `4` Easy-Mode 레시피 시작, `6` 유휴/무시 |

- 보고 상태가 신뢰할 수 있는 상태 소스입니다 — Studio의 raw 상태 하트비트 vs
  cmd-tagged 프레임 교훈과 동일(`[[xbloom-raw-state-heartbeat-vs-cmd-tagged]]`).
- `thing_shadow/`가 초기 전체 스냅샷을, WebSocket이 델타를 제공합니다.
- 대응 모델: `model/DeviceJ20DetailModel.java`(`capsule_rfid_tag`, `is_online`,
  `warning`, `work_mode`, `DM_SN`, `multimcuotainfo` → MCU별
  `mcu_name`/`mcu_version`), `DeviceJ20Model.java`(`product_id`, `mac`,
  `device_id`, `enduser_id`, `sn`).

## Studio BLE 프로토콜과의 관계 — 아무것도 이식되지 않음

기존 코드 경로에 플래그 하나로 Original을 얹고 싶은 사람을 위해: 두 기기는
**전송 표면을 전혀 공유하지 않습니다**.

| 항목 | Studio (J15, 이 통합) | Original (J20) |
|---|---|---|
| 링크 | HA Bluetooth 스택 경유 BLE | Wi-Fi, 클라우드 경유 |
| 프레이밍 | `0x58 0x02` 패킷, CRC, MTU `8100` 핸드셰이크 | HTTPS + WebSocket 위 JSON |
| 명령 테이블 | `APP_*`/`RD_*` id, type-1/type-2 마커 | 섀도우 `desired` 문서 |
| 상태 | raw BLE 상태 하트비트 | 클라우드 `state.reported` 푸시 |
| 인증 | 없음(로컬 BLE) | 요청마다 서명된 클라우드 토큰 |
| HA 빌딩블록 | `bluetooth` 매처 + `coordinator/connection.py` | 클라우드 스트림 클라이언트(`thing_shadow` 폴링 + WS의 `DataUpdateCoordinator`) |

따라서 Original 지원은 사실상 레시피 스토어와 `_cloud_client.py` 스타일의 HTTP
배관만 공유하는 **두 번째 클라우드 전용 통합**입니다 — BLE 코디네이터에 얹는
작은 분기가 아닙니다. 이는 `AGENTS.md` 하드룰 #6이 정확히 예견한 바이며, 이
문서는 그 결정을 뒤집으려는 계획이 아니라 그 결정의 근거입니다.

## 미해결 질문 (Original 하드웨어 없이는 막힘)

- `api-iot.xbloom.com`의 정확한 요청 서명 입력(`ts`/`nonce`/`appid` HMAC).
- WebSocket URL, 서브프로토콜, subscribe/인증 핸드셰이크, 재연결/ping 주기
  (`WsManager`는 벤더 라이브러리 `com.mixchip.websocketclient`).
- `bruw_curve` hex 인코딩(추출 양/온도/급수원이 중간 hex 필드 2개와
  `outWaterType`에 어떻게 매핑되는지).
- `setting_grind_size` 유효 범위와 Studio 스케일과의 일치 여부.
- 전체 `warning` 및 `work_mode` 코드 테이블.
- Tea 레시피가 J20 desired-state 형태를 갖는지 여부.
