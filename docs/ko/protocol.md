# XBloom Studio BLE 프로토콜 레퍼런스

> **이 문서는 XBloom Studio(BLE)만 다룹니다.** XBloom Original은 BLE 제어 경로가
> 없는 Wi-Fi + 클라우드 IoT 프로토콜의 다른 기기입니다 —
> [`protocol-original-j20.md`](./protocol-original-j20.md)의 (디컴파일 전용,
> 미검증) 지도를 참조하세요.

> 이 페이지는 [`en/protocol.md`](../en/protocol.md)의 번역본입니다. 영문판이
> source of truth이며, 한글본은 뒤늦게 동기화될 수 있습니다. 이 문서는 이
> 통합 자체의 실제 하드웨어 캡처와, 공식 안드로이드 앱
> (`xbloom_coffee_release.apk`)을 `androguard`/`jadx`로 정적 디컴파일한
> 결과(zip/dex/소스 덤프로만 확인 — 배포되거나 재배포된 적 없음)를 바탕으로
> 새로 작성되었습니다. upstream 문서인 `xbloom-ble/PROTOCOL.md`를 1차
> 레퍼런스로 삼던 방식을 대체합니다(이 upstream은 예전에 저장소에 벤더링되어
> 있었으나 이후 제거됨) — 이유는
> [ADR-001](../../adr/001-clean-room-reimplementation-of-xbloom-ble.md) 참고.
> 아래 모든 주장은 실기 캡처 또는 특정 디컴파일된 클래스/메서드로 추적
> 가능하며, 독립적으로 확인되지 않은 내용은 사실처럼 서술하지 않고 그렇게
> 표시했습니다.

## 패킷 프레이밍

```
header(0x58 0x02) | dev_id | type | cmd(2, LE) | len(4, LE) | const(0x01) | payload | crc(2)
```

- **`type`**: 대부분의 아웃바운드 명령은 `0x01`, 특정 계열은 `0x02` —
  모드 전환(`11511`), Easy Mode 슬롯 쓰기(`11510`/`11512`),
  pour-radius/vibration-amplitude GET/SET(`11506`–`11509`). 이 명령들을
  type-1로 보내면 아예 응답이 없습니다(2026-07-17 하드웨어 확인, HA를
  거치지 않은 별도 캡처).
- **응답 마커 바이트**: length 필드 바로 뒤(offset+9) — type-1 명령의
  응답은 `0xC1`, type-2 명령의 응답은 `0xC2`. 경험적으로
  `0xC0 | type_code` — 2026-07-17 이전 이 통합이 보내던 모든 명령이 우연히
  type-1이었기 때문에, 위 115xx 계열이 필요해지기 전까지는 type-2 마커의
  존재가 드러나지 않았습니다. `0xC1`만 확인하는 파서는 모든 type-2 응답을
  조용히 버립니다.
- **현실적인 최대 패킷 길이**: 파싱 시 256바이트로 제한합니다. 무게/수위
  텔레메트리 스트림이 초당 여러 번 흘러오는데, 그 잡음 속에서 헤더 바이트가
  우연히 일치하면 4바이트 길이 필드를 쓰레기 값으로 읽을 수 있습니다 —
  상한을 두면 버퍼가 통째로 깨지는 대신 단순히 재동기화 후 건너뛰게 됩니다.
- **아웃바운드 쓰기는 ≤100바이트로 분할**됩니다
  (`min(100, mtu_size - 3)`, 하한 20) — 공식 앱의 fastble
  `setSplitWriteNum(100)`과 동일. 펌웨어는 여러 번의 BLE 쓰기로부터 명령을
  재조립합니다 — 프레이밍이 헤더+길이 기반이지 쓰기 경계 기반이 아니므로,
  패킷 중간에서 쓰기가 끊겨도 문제없습니다. 긴 페이로드(`8001`/`8004` 레시피
  전송, `11510` Easy Slot 쓰기)를 저-MTU 경로(예: ESPHome BLE 프록시)로
  보낼 때 특히 중요합니다.
- **`8100` MTU 핸드셰이크가 모든 것을 게이팅**합니다. `8100`
  (페이로드 `[185, 1]`)이 전송·확인되기 전까지 머신은 다른 모든 명령을
  조용히 무시합니다 — 디스플레이 웨이크도, LED도, `RD_MachineInfo`도 없음.
  독립된 별개의 리버스 엔지니어링 결과(`cryptofishbug/xbloom-recipe-cli`의
  펌웨어 스위처 APK, 정적 분석)로도 교차 확인됨 — 동일한 명령 id, 동일한
  "세션 프라이머" 역할, 동일한 전원 재순환 복구 안내. 후속 `8101`은 머신을
  OTA 업데이트용 YMODEM 수신 모드로 전환합니다 — 이 통합은 펌웨어를 플래싱하지
  않으므로 범위 밖이며, `8100` 바로 옆 id라서 참고용으로만 문서화합니다.
- **연속된 type-2 명령 사이에는 간격이 필요**합니다. 두 개의 type-2
  전송(GET-then-GET, GET-then-SET, 또는 연속된 Easy Slot 쓰기) 사이 간격이
  약 0.5초 미만이면 *두 번째* 명령의 응답이 안정적으로 드롭됩니다 — 머신이
  첫 번째 응답을 처리하느라 아직 바쁜 것으로 보입니다. 0.3초(실패) vs.
  0.8초/1.0초/1.5초(성공)로 반복 시도하여 하드웨어로 확인했으며, 이 통합의
  모든 type-2 호출 지점은 여유를 두고 0.8초 간격을 사용합니다.
- **CRC 오류는 의도적으로 무시합니다.** 공식 앱의 머신 CRC 오류 핸들러
  (`ErrorCRCBleModel.excute()`)는 빈 메서드입니다 — 재전송도, 사용자 노출도,
  리셋도 없습니다. 재전송 루프로 "고치려" 하지 마세요: CRC 오류 시 재전송은
  공식 클라이언트와의 괴리이지 개선이 아닙니다.

## 명령 테이블

상태 범례: **Active** — 이 통합이 오늘 실제로 보내거나 처리하며 페이로드
형태가 확인됨. **Telemetry** — 인바운드, 고빈도, 센서에 직접 반영됨.
**Present, unconfirmed** — 벤더 enum 또는 공식 앱 자체의 상수 테이블에 실재하는
명령 id이지만, 이 통합에서 페이로드 의미나 호출 지점이 확인되지 않음 — 이름만
보고 동작을 추정하지 말 것.

### 아웃바운드 (`APP_*` 및 이름 없는 setter)

| id | 이름 | 페이로드 | 상태 | 비고 |
| ---: | --- | --- | --- | --- |
| 3500 | `APP_GRINDER_START` | 굵기, 속도 | Active | 수동 + 레시피 그라인딩; Easy 모드에서도 동작 (2026-07-19 하드웨어 — 모드 관문 부재는 8001 항목 참고) |
| 3502 | `CMD_CALIBRATE_GRINDER` | `[1000]` 고정 | Active | 발사 후 방치; 머신이 약 120초 스윕을 자율적으로 수행 |
| 3505 | `APP_GRINDER_STOP` | — | Active | 수동 그라인딩 정지 전용, 레시피 전체 정지 아님 |
| 4506 | `APP_BREWER_START` | 용량, 온도, 유량, 패턴 | Active | 수동 추출 |
| 4507 | `APP_BREWER_STOP` | — | Active | 수동 추출 정지 전용 |
| 4508 | 급수원 설정 | LE u32 (0=탱크,1=직결) | Active | `WaterSourceType.ordinal()`; J20 전용 값(8/50)은 Studio에 해당 없음 |
| 4510 | `APP_BREWER_SET_TEMPERATURE` | LE u32 `round(온도℃ × 10)` | Active | jadx 2026-07-19: `BrewerActivity.checkAndSetTemperature`가 추출 페이지에서 온도 슬라이더가 바뀔 때마다 실시간 전송; 실제 추출이 도는 동안에는 앱이 슬라이더를 비활성화. 같은 날 하드웨어 확인: 880(88.0℃) 전송 시 ACK payload가 해석된 값을 float32로 echo (`00005c44` = 880.0) |
| 4512 | `APP_TEA_RECIP_MAKE` | — | Active | 큐에 넣은 티 레시피 실행 |
| 4513 | `APP_TEA_RECIP_CODE` | 티 레시피 블롭 | Active | 티 레시피 큐잉; **8004가 아님** — brewing-notes.md 참고 |
| 8001 | `APP_RECIPE_SEND_AUTO` | 레시피 블롭 | Active | 그라인딩 포함 커피 레시피; 앱은 `recipe.isSetGrinderSize`로 8001/8004를 선택 (1 → 8001, 그 외 → 8004). 앱의 실행 체인(`8102` 바이패스 → `8104` 컵 → `8001`/`8004` → `8002`)에는 **모드 관문이 없음** — 하드웨어도 불필요함을 확인 (2026-07-19 라이브: Easy 모드 상태에서 전체 체인이 ACK되고 분쇄 단계가 시작됨; 과거의 "Easy 모드는 추출 명령 무시, 물만 나옴" 관측은 ratio footer 버그의 오귀속이었음) |
| 8002 | `APP_RECIPE_EXECUTE` | — | Active | 큐에 넣은 레시피 커밋/시작 |
| 8003 | *(enum 이름 없음 — 앱 내 raw 리터럴)* | — | Active | "电子秤功能进入指令" — 기기에 저울 화면 표시; 앱은 자기 저울 페이지를 열기 전에 ACK 확인 후 전송 (`HomeActivity.onClickOperator3`). 2026-07-19 라이브 하드웨어 확인: ACK 후 상태코드가 홈 `0x01` → `0x04` → `0x05`(저울 화면)로 이동; 노브 진입 시의 9002/9008 보고는 BLE 명령 경로에서는 발화하지 않았음 |
| 8004 | `APP_RECIPE_SEND_MANUAL` | 레시피 블롭 | Active | 그라인딩 없는(바이패스) 커피 레시피 — 앱의 선택 기준은 8001 항목 참고 |
| 8006 | `APP_GRINDER_IN` | 굵기, 속도 | Active | "그라인딩 화면 진입"; 수동/레시피 그라인딩 전에 내부적으로 전송. 앱은 그라인딩 페이지에서 실행 중이 아닐 때 굵기/RPM 슬라이더가 바뀌면 이를 **실시간 조절 명령으로 재전송** (`GrinderActivity.adjustGrinder`, 실패 무시 best-effort) — 재전송이 하드웨어에서 깔끔히 ACK됨 (2026-07-19 라이브), 그리고 분쇄 페이지는 Easy 모드에서도 열림 (8023 index `0x02`로 보고) |
| 8007 | `APP_BREWER_IN` (enum 이름 `RD_BREWER_IN`) | — | Active | "추출 화면 진입"; 앱 동작 일치를 위해 수동 추출 전에 전송, 필수는 아님. 추출 화면을 엶(상태/8023 코드 `0x03`) — 단, 한 라이브 런에서는 이후 코드 방출이 없었어서 보고가 완전히 일관되지는 않음 |
| 8012 | `APP_GRINDER_QUIT` | — | Active | 분쇄 페이지 나가기 — armed 수동 분쇄 취소 |
| 8013 | `APP_BREWER_QUIT` | — | Active | 추출 페이지 나가기 — armed 수동 추출 취소 |
| 8014 | *(enum 이름 없음 — 앱 내 raw 리터럴)* | — | Active | "退出称重页面" — 저울 화면 나가기; 앱 저울 페이지의 뒤로가기 핸들러에서 전송 (`ScaleActivity.onBackPressed`). 2026-07-19 라이브 하드웨어 확인: ACK 후 상태가 홈 `0x01`로 복귀 |
| 8016 | `APP_BREWER_SET_PATTERN` | LE u32 패턴 코드 | Active | jadx 2026-07-19: `BrewerActivity.checkAndSetSpiral`이 추출 페이지에서 패턴을 탭할 때마다 실시간 전송; 추출이 도는 동안에는 비활성화. 하드웨어: 같은 날 ACK 확인 (빈 payload echo) |
| 8017 | `APP_RECIPE_START_QUIT` | — | Active | 머신 자체의 "포드 삽입" 프롬프트 취소, armed 레시피 취소 |
| 8018 | `APP_GRINDER_PAUSE` | — | Active | 수동 그라인딩 일시정지 전용, 레시피 전체 아님 |
| 8019 | `APP_BREWER_PAUSE` | — | Active | 수동 추출 일시정지 전용 |
| 8020 | `APP_GRINDER_RESTART` | — | Active | 수동 그라인딩 재개 |
| 8021 | `APP_BREWER_RESTART` | — | Active | 수동 추출 재개 |
| 8022 | `RD_BackToHome` (이름과 달리 아웃바운드) | — | Active | UI 상태 초기화, 모든 레시피 시작 시 전송 |
| 8100 | MTU 핸드셰이크 | `[185, 1]` | Active | 위 패킷 프레이밍 참고; 전송 전까지 다른 모든 명령을 차단 |
| 8102 | `APP_SET_BYPASS` | (max, min) 컵 무게 float | Active | 공식 앱의 `setCup`과 일치함을 확인 — 한때 서드파티 캡처가 주장했던 "예열 단계 온도"가 아님 |
| 8103 | 디스플레이 밝기 (`RD_LetType`) | `{1, 8, 15}` 중 하나 | Active | 고정 3단계(L1/L2/L3); GET 대응 없음 |
| 8104 | `APP_SET_CUP` | (max, min) 컵 무게 float | Active | 8102와 동일한 형태; 커피/티 컵 범위 설정에 사용 |
| 11506 | pour-radius GET | — | Active | type-2; 응답은 payload offset 0의 LE u32 |
| 11507 | pour-radius SET | LE u32 | Active | type-2; 클라우드 API에서 가져온 기기별 중심값 기준 ±80 간격의 5단계 |
| 11508 | vibration-amplitude GET | — | Active | type-2 |
| 11509 | vibration-amplitude SET | LE u32 | Active | type-2; 6단계 |
| 11510 | `RD_EASYMODE_RECIPE_SEND` (아웃바운드) | 슬롯 레시피 블롭 | Active | type-2; A/B/C 세 슬롯 모두 배치로 전송해야 하며 단일 슬롯 쓰기는 불가 |
| 11511 | `RD_EASYMODE_TYPE` (아웃바운드: 모드 전환) | 모드 코드 | Active | type-2; 머신이 sleeping 상태로 응답할 때만 ACK 타임아웃 시 재시도 |
| 11512 | `RD_EASYMODE_RECIPE_ORDER` (아웃바운드) | hex 문자열 `[3,0,1,2]` | Active | type-2; Easy Slot 배치 쓰기 이후 전송 |
| 40518 | 레시피 전체 일시정지 | — | Active | `AppJ15AutoManager.pause()`; 레시피 모드 브루잉 전용, 수동 그라인딩/추출 아님 |
| 40519 | `APP_RECIPE_STOP` | — | Active | 레시피 전체 정지 |
| 40524 | 레시피 전체 재개 | — | Active | 40518과 짝을 이룸 |
| 8500 | 저울 영점(tare) | — | Active | `CMD_TARE`, `xbloom-ble`에서 cherry-pick |

### 인바운드 (`RD_*`)

| id | 이름 | 페이로드 | 상태 | 비고 |
| ---: | --- | --- | --- | --- |
| 8009 | `RD_MachineSleeping` | — | Active | sleep 플래그 설정; 모드 전환 재시도를 게이팅 |
| 8011 | `RD_MachineNotSleeping` | — | Active | sleep 플래그 해제 |
| 8015 | `RD_UNIT_CHANGE` | LE u32 3개 (무게/온도/급수원 단위) | Active | 머신 자체 터치스크린에서 단위가 바뀌면 push됨 |
| 8023 | `RD_MachineActivity` | LE u32 `index` | Active | sleep 플래그를 무조건 해제. `index`는 raw 상태 하트비트의 상태 코드와 바이트 단위로 동일 (2026-07-19 라이브 확인: `0x01` 홈, `0x1F` 레시피 로드, `0x1E` 확인 대기, `0x22` 시작이 두 채널에서 동시 도착) — 단, 항상 엄격한 짝은 아님: Easy 모드에서 분쇄 페이지를 열면 8023 `index=0x02`만 오고 대응하는 raw 하트비트 프레임은 **없었음** — 8023이 더 완전한 페이지 전환 채널. 이 통합은 상태를 하트비트 프레임에서 읽으며 `index`는 미사용. 앱 쪽 소비(jadx): `index == 1`(홈)은 버스 이벤트로 재게시되어 `AppJ15AutoManager`가 자동 추출 트래킹의 세션 종료로 처리; `TeaAutoFragment`는 `index == 35`에서 푸어 리스트를 갱신 |
| 8105 | `RD_GRINDER_SIZE` | LE u32, `-30` 오프셋 | Telemetry | 실시간 그라인딩 굵기 노브 |
| 8106 | `RD_GRINDER_SPEED` | LE u32 | Telemetry | 실시간 RPM; 그라인딩 정지 시 명시적으로 0 처리(0은 실제 값이지 "알 수 없음"이 아님) |
| 8107 | `RD_BREWER_MODE` | LE u32, 0/1/2 | Telemetry | 실시간 추출 패턴 노브 |
| 8108 | `RD_BREWER_TEMPERATURE` | LE u32 | Telemetry | 실시간 추출 온도 |
| 8111 | `RD_EASYMODE_BEGIN` | LE u32, 0–2 | Active | 머신 자체 다이얼에서 Easy Mode 추출 시작; A/B/C 슬롯에 매핑 |
| 8113 | `RD_TEA_RECIP_CHANGE_SOAK_TIME` | — | Active | `"tea_soak_time_changed"` 알림에 매핑 |
| 8203 | `RD_AbnormalGearPosition` | — | Active | 에러 이벤트 |
| 8204 | `RD_AbnormalDoseOrWater` | — | Active | 에러 이벤트 |
| 9000 / 9001 / 9002 | `RD_IN_GRINDER`/`RD_IN_BREWER`/`RD_IN_SCALE` | — | Present, unconfirmed | 모드 진입 ACK, 이 통합에 핸들러 없음 |
| 9003 | `RD_GRINDER_BEGIN` | — | Active, 신뢰 불가 | 실제 그라인딩 중 발생하지 않을 수 있음 — 아래 raw status-heartbeat 프레임 참고 |
| 9004 / 9006 / 9008 | `RD_OUT_GRINDER`/`RD_OUT_BREWER`/`RD_OUT_SCALE` | — | Present, unconfirmed | 모드 종료 ACK, 핸들러 없음 |
| 9005 | `RD_BREWER_BEGIN` | — | Active, 조기 발생 | 커밋 직후 즉시 발생 — 실제 추출 시작보다 훨씬 이름 |
| 9009 | `RD_GRINDER_PAUSE` | — | Present, unconfirmed | 핸들러 없음 |
| 9010 | `RD_BREWER_PAUSE` | — | Active | `"paused"` 알림에 매핑 |
| 9011 | `RD_TEA_RECIP_RESTART` | — | Active | 스팀 사이 일시정지 후 재개 |
| 9012 | `RD_TEA_RECIP_SOAK` | — | Active | `"tea_soaking"`에 매핑 |
| 10507 | `RD_CURRENT_WEIGHT` | float32 | Telemetry | 20501과 동일한 레이아웃 |
| 11518 | `RD_EASYMODE_RECIPE_STATE` | — | Present, unconfirmed | 디컴파일로 확인 — 이름과 달리 슬롯/진행 상황과 무관한 중복 모드 표시 echo |
| 20501 | `RD_CURRENT_WEIGHT2` | float32 | Telemetry | 저울 무게, 주 채널 |
| 40501 | `RD_Pods` | 6 raw bytes → ASCII | Active | NFC 포드 감지; 앱은 12 hex 문자(=6바이트)를 디코딩, 12 raw bytes가 아님 |
| 40502 | `RD_BREWER_COFFEE_START` | — | Active | 대체 "추출 시작" 신호 |
| 40505 | `RD_GearReport` | — | Present, unconfirmed | 핸들러 없음 |
| 40506 | *(APK 상수 테이블에 없음 — "grinder begin")* | — | Confirmed, unhandled | 그라인더가 도는 정확히 그 순간 발화하며 호퍼 상태와 무관 (2026-07-19 라이브 캡처 3회: 빈 호퍼 레시피 분쇄 ×2, 찬 호퍼 ×1, **수동** 3500 분쇄 포함), 모든 정지/취소에 40507(`RD_Grinder_Stop`)이 응답 — 범용 grinder begin/stop 짝. 9003 `RD_GRINDER_BEGIN`이 끝내 제공하지 못한 신뢰 가능한 분쇄-시작 신호. 앱 자체 상수 테이블에 없는 id(펌웨어가 앱보다 최신); 이 통합엔 아직 핸들러 없음 — 신뢰 가능한 `grinding_started` 이벤트 소스 후보 |
| 40507 | `RD_Grinder_Stop` | — | Active | 그라인딩 종료; 실시간 RPM을 0으로 설정; 캘리브레이션의 홈 이동 중에도 발생하므로 **캘리브레이션 완료 신호로 유효하지 않음** |
| 40510 | `RD_BLOOM` | — | Active | 블룸 알림 |
| 40511 | `RD_Brewer_Stop` | — | Active | 추출 종료 |
| 40512 / 40513 | `RD_ENJOY` / `RD_ENJOY2` | — | Active | 레시피 완료 |
| 40515 | `RD_TEA_RECIP_PAUSE` | — | Active | 스팀 사이 일시정지/종료 |
| 40517 | `RD_ErrorIdling` | — | Active | `"no_beans"` 에러에 매핑 |
| 40520 | `RD_BYPASS` | — | Present, 페이로드 없음 확인 | 디컴파일로 확인된 페이로드 없는 UI 펄스, 노출할 상태 없음 |
| 40521 | `RD_MachineInfo` | 고정 오프셋 구조체 | Active | 연결 시점 스냅샷: 시리얼, 펌웨어, 모드, 급수 정상 비트, 굵기/전압; 일부 펌웨어에서는 아예 오지 않을 수 있음 — AGENTS.md의 재시도/폴백 항목 참고 |
| 40522 | `RD_ErrorLackOfWater` | LE u32 (0=비어있음, 1=보충됨) | Active | 양방향 — 일회성 에러가 아님, "water-level" 처리 참고 |
| 40523 | `RD_WATER_VOLUME` | LE u32 | Telemetry | 실시간 탱크 수위 |
| 40525 | `RD_EASYMODE_RECIPE_NUM` | — | Present, unconfirmed | 핸들러 없음 |
| 40526 | `RD_CurrentGrinder` | LE u32, `-30` 오프셋 | Active | 8105와 동일 값; `is_calibrating_grinder` 중 `raw == 85`가 실제 캘리브레이션 완료 신호 |
| 40527 | `RD_BeforeVibration` | — | Present, 페이로드 없음 확인 | 디컴파일로 확인된 페이로드 없는 펄스 |
| 50038 / 50039 | `RD_CalibrateStart` / `RD_Calibrating` | — | Active, best-effort | 캘리브레이션 시작/진행 펄스; 모든 기기에서 안정적으로 오지 않음 — `async_calibrate_grinder()`는 시작 추적에 50038을 필요로 하지 않음 |
| Raw status-heartbeat 프레임 (cmd id 없음, 별도 프레이밍, `type` 바이트 `0x57`) | — | state byte | Active | `starting`/`brewing`/`ready`의 유일하게 신뢰 가능한 신호; 위 cmd 태그 경로(9003/9005/40507)는 바로 이 전환 구간에서 신뢰할 수 없음 — AGENTS.md 참고. 2026-07-19 라이브에서 매핑 외 화면/상태 코드 추가 관측: `0x01` 홈(PRO), `0x41` 홈(Easy 모드), `0x02` 분쇄 화면, `0x03` 추출 화면, `0x04` → `0x05` 저울 화면, `0x1D` 연결 직후 홈 전 짧은 과도 상태 — 모두 `_RAW_STATE_LABEL_MAP` 미매핑(현재 `idle`로 폴백). 수동 추출은 `0x03` → `0x23`(brewing) → 4507 정지 시 `0x03` 복귀로 진행하며, 4506/4507 ACK는 용량을 float32로 echo |

두 개의 id는 문맥에 따라 방향과 의미가 다르며 **동일 명령이 아닙니다**:
`4508`은 순수 아웃바운드 급수원 setter(위 표 참고)이고, `8103`은 아웃바운드
밝기 setter로 쓰이는 동시에 벤더 enum에도 `RD_LedType`으로 존재합니다 —
응답으로서의 별도 인바운드 핸들러는 없으며 아웃바운드 명령 id로만 사용됩니다.

## 알려진 전송 계층 특이사항 (요약 — 각 항목의 전체 조사 이력은
`AGENTS.md` / 프로젝트 메모리 참고)

- `RD_MachineInfo`나 다른 어떤 request/response 명령이든 성공하려면 `8100`
  핸드셰이크가 (재)전송되어 있어야 합니다 — pour-radius/vibration-amplitude
  GET도 포함: 이 통합의 초기 버전에서는 재시도된 *두 번째* 핸드셰이크가
  완료되기 전에 전송되어 조용히 드롭된 적이 있습니다.
- Type-2 명령(`115xx` 계열)은 요청에 `type_code=2`가 필요하고, 응답에서
  `0xC1`이 아닌 `0xC2`를 받아들여야 하며, 연속된 type-2 전송 사이에 0.8초
  이상 간격이 필요합니다.
- `MachineInfo`의 문자열 필드(모델명 등)는 NUL이 아닌 `0xFF`로 패딩됩니다 —
  항상 `strict_ascii()`(0x20–0x7E 출력 가능 문자만)를 통해 디코딩해야 하며,
  단순 UTF-8 디코딩은 절대 사용하지 마세요.
- Easy Mode 슬롯 쓰기(`11510`)는 커밋 프레임 없이 A/B/C 전체를 배치로,
  PRO 모드에서 전송해야 합니다 — 단일 슬롯만 쓰면 머신이 "saving" 상태에서
  멈춥니다.
- 그라인딩 없는(바이패스) 커피 레시피는 `8102` 페이로드에 실제 0이 아닌
  `dose` 값이 필요합니다 — `dose=0`이면 에러 알림 없이 조용히 arm 단계에서
  멈춥니다.
