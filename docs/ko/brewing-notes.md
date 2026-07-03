# 추출 동작 노트 — 펌웨어 거동 / 알려진 제약

> 이 페이지는 [`en/brewing-notes.md`](../en/brewing-notes.md)의 번역본입니다. 영문판이 source of truth이며, 한글본은 뒤늦게 동기화될 수 있습니다.

이 문서는 `brewing.py`가 실제로 머신에 보내는 BLE 시퀀스, 두 upstream(`PyBloom` / `xbloom-ble`)이 다루지 않는 펌웨어 거동, 그리고 현재까지 풀지 못한 제약을 기록합니다. 사용자용 빠른 시작은 [`index.md`](./index.md)를 보세요.

마지막 업데이트: 2026-05-29

## 현재 추출 시퀀스

### 커피 (`grind_size > 0 + bean_weight > 0`)

`brewing._async_brew_coffee`. 모든 패킷 사이 1.0초 spacing. vendored `XBloomClient.brew()`를 호출하지 않고 인라인 처리 — bypass 인자를 실제로 8102에 실어 보내야 하기 때문 (vendored는 `set_bypass(0.0, 0.0, dose)`로 하드코딩됨).

```
─ Prelude ─
8022  RD_BackToHome   (티 brew 이후 푸어 패턴 해석 복원)
─ 표준 brew ─
8102  APP_SET_BYPASS  [bypass_volume_f32, bypass_temperature*10_f32, dose_i32]
8104  APP_SET_CUP     [cup_max_f32, cup_min_f32]
8001  APP_RECIPE_SEND_AUTO    (grind 있을 때) / 8004 SEND_MANUAL (없을 때)
8002  APP_RECIPE_EXECUTE
```

Cup bounds (vendored `XBloomClient` 값 그대로):
- omni_dripper (2): grind → (90, 40), no-grind → (90, 0)
- xpod (1): grind → (80, 40), no-grind → (80, 0)
- other (3): grind → (90, 40), no-grind → (90, 0)

brAzzi64 HCI 캡처는 omni_dripper에 대해 (110, 90)을 실측했으나, vendored 값으로도 동작하므로 그대로 유지. 추출 동작 자체에 영향은 없는 것으로 보이며 무게 표시 기준만 다를 가능성.

### 티 (`cup_type: tea`)

`brewing._async_brew_tea`. 패킷 간 2.0초 spacing (이보다 짧으면 펌웨어가 ACK만 하고 silent drop, 2026-05-13 로그에서 확인).

```
8022  RD_BackToHome
8102  APP_SET_BYPASS  [0, 0, 0]
8104  APP_SET_CUP     [200, 0]    ← 티 bounds
4513  APP_TEA_RECIP_CODE  (build_tea_payload)
4512  APP_TEA_RECIP_MAKE  (페이로드 재송신, vendored execute_recipe 미러)
```

`_build_tea_payload`는 각 스팁의 wire 볼륨을 `_TEA_SIPHON_CAP`(90ml, 펌웨어가 소크 후 자동 탑업해 배수하도록)으로 캡하고, substep pattern=1(circular — 커피와 동일)을 쓰며, 소크 시간을 timing 블록의 byte[1]에 기록함. 이 구조가 어떻게 발견됐는지는 [해결됨 — 티 다중 스팁 flatten](#해결됨--티-다중-스팁-flatten) 참고 — 과거 pattern=3 hack(AML225 cloud-API JSON 차용)은 동작하지 않아 교체됨.

## 해결됨 — 티 brew 이후 그라인딩 (2026-05-29)

**상태: 수정됨.** 이전에는 티 레시피(4513/4512) 직후 첫 커피 brew에서 그라인더 단계를 건너뛰었음 — 푸어는 정상이지만 원두를 갈지 않아 빈 필터로 뜨거운 물만 통과, 복구는 전원 재시작뿐이었음.

### 근본 원인

**공식 iOS 앱**이 티→커피로 넘어가는 PacketLogger HCI 캡처(2026-05-28, `Untitled - (null).pklg`)로 확정: 공식 앱은 티 brew와 커피 brew 사이에 **mode-exit 명령을 하나도 보내지 않음** — 표준 `8102 → 8104 → 8001 → 8002`뿐 — 그런데도 티 직후 첫 커피에서 그라인더가 정상 작동. 펌웨어에 tea-mode 잠금 같은 건 없음.

이 버그는 **자초한 것**이었음: `_async_brew_coffee`에 공식 앱이 절대 안 보내는 QUIT 프렐류드(`APP_RECIPE_STOP` 40519 + `APP_BREWER_QUIT` 8013 + `APP_GRINDER_QUIT` 8012 + `APP_RECIPE_START_QUIT` 8017)가 붙어 있었고, 그 중 하나가 그라인더를 죽였음. "미지의 tea-exit 명령이 필요하다"는 기존 가설은 정반대였음 — 우리는 *너무 적게*가 아니라 *너무 많이* 보내고 있었음.

### 수정

`_async_brew_coffee`에서 QUIT 4개를 제거하고 `8022 RD_BackToHome`만 유지(8022는 푸어 패턴 해석을 독립적으로 복원 — 없으면 커피 푸어가 레시피의 spiral 대신 center로 떨어짐). 2026-05-29 실기 확인: 티 → 커피가 그라인딩 + spiral 푸어 + 온도 + 진동 모두 정상. 전원 재시작 워크어라운드는 더 이상 필요 없음.

> 참고: 이 문서는 과거 QUIT 프렐류드가 "티 다중 스팁 분리를 복원했다"고 적었으나, 그건 우연한 상관관계였음 — 공식 캡처상 티 스팁 분리는 커피 측 프렐류드가 아니라 **티 레시피 페이로드(pattern 바이트 + 스팁별 timing)**로만 결정됨. 아래 참고.

## 해결됨 — 티 다중 스팁 flatten

**상태: 수정됨 (2026-05-29, 실기 확정).** 다중 스팁 티 레시피(예: 홍차 — 120ml @95°C 소크 180s + 120ml @95°C 소크 120s)가 2개 스팁이 아니라 **단일 ~316ml 푸어**로 추출되던 문제. 공식 앱 캡처로 4513 페이로드를 바이트 비교해 원인을 특정함:

```
ha-xbloom: 10 | 78 5f 03 00 | 4c 00 00 1e | 78 5f 03 00 | 88 00 00 1e | 00 60
official:  10 | 5a 63 01 00 | 00 60 00 23 | 46 63 01 00 | ce 20 00 23 | 32 00
                  +-substep-+   +-timing--+
```

`316 = 120 + 76 + 120`: 스팁 경계를 인식하지 못한 펌웨어가 timing 블록의 pause 바이트(`0x4c = 76`)를 또 하나의 볼륨으로 오독함. `_build_tea_payload`는 공식 인코딩과 3개 필드에서 어긋남:

1. **substep pattern 바이트: 3 vs 1.** `_TEA_PATTERN_BYTE = 3` hack(AML225 cloud-API JSON 차용)은 공식 앱과 다름 — 공식은 커피와 동일한 pattern 1(circular)을 씀. 스팁 분리는 pattern=3에서 오는 게 아님.
2. **timing 바이트[1]: 0 vs nonzero**(0x60 / 0x20) — 진짜 스팁 분리/소크 마커로 추정. `_build_tea_payload`는 이 바이트를 0으로 하드코딩함.
3. **footer: `[0, water×10]` vs `[grind, ratio]`** — `_build_tea_payload`가 `total_water*10`을 ratio 자리에 잘못 넣음. `encode_recipe`의 `[grinder_size, ratio×10]`를 따라야 함.

**분리 수정 2026-05-29 (실기 확정).** `_build_tea_payload`가 이제 pattern=1, footer `[grind, ratio×10]`, 소크를 timing 바이트[1]에 넣고 byte[0]=0으로 생성. 홍차 브루 시 **2개의 분리된 스팁**으로 나옴 — **pattern 3→1이 해결책이었음.** 후속: byte[1]을 처음엔 negate했더니 실기에서 스팁 순서가 뒤집힘(steep1이 steep2보다 짧음, 레시피와 반대) → 이제 **양수** `pausing & 0xFF`로 수정(펌웨어가 양수로 읽음).

**소크 스케일 보정(근사) 2026-05-29.** 홍차 브루 측정 결과 펌웨어가 idle 대기를 byte[1]의 약 **1.67배**로 돌림(byte 180→~300s, 120→~180s). 이제 `_build_tea_payload`가 `byte[1] = clamp(round(pausing × 0.6), 1, 255)`로 써서 실제 대기 ≈ 레시피의 `pausing` 초가 되게 함(steep 마커 유지 위해 ≥1). 0.6은 거친 스톱워치 2점 기반 — 더 정밀히 원하면 한 번 더 재면 됨.

**진짜 소크 / 사이펀 수정 2026-05-29 (실기 확정).** ha-xbloom은 이전에 레시피 풀 볼륨(120ml)을 부어 ~120ml 사이펀 임계에 닿아 *즉시 배수* → 소크 없음. 공식 앱은 임계 이하로 붓고 펌웨어가 소크 후 자동 탑업해 배수합니다. 이제 `_build_tea_payload`가 각 wire pour를 `_TEA_SIPHON_CAP = 90 ml`로 캡(레시피는 authored 볼륨 유지 — 홍차는 120/120 그대로). 홍차 실기 확인: steep1 = 90ml 붓고 → **물 머금은 채 3분 소크** → 펌웨어 자동 탑업 ~38ml → 사이펀 배수 → 진동; steep2 = ~90ml → 2분 소크 → +38ml → 배수. 소크 시간이 레시피(180s/120s)와 일치, 총 ~255ml ≈ authored 240. 즉 ha-xbloom의 4513도 공식 앱과 동일하게 펌웨어 소크+탑업을 트리거 — **탑업을 흉내 낼 필요 없이 임계 아래로만 보내면 됨.** 결과적으로 진짜 다분 소크가 가능(아래 "flash steep" 서술은 정정됨).

## xBloom Omni Tea Brewer — 사이펀 동작

이 섹션은 펌웨어가 아니라 **하드웨어(피타고라스 컵) 거동** 정리. 레시피를 설계할 때 알아야 하는 내용.

### 공식 스펙

- **총 용량**: 160ml per steep
- **컵으로 내려가는 양**: 약 120ml per steep
- **Auto Steep System**: 수위가 브루어 내부 사이펀 암 꼭대기에 도달하면 밸브 자동 개방, 전 수량 배수

(출처: xBloom 공식 가이드, Basic Barista 제품 페이지)

### 실제 동작

- 찻잎(3-5g 잎차)이 브루어 내부에서 약 30-40ml 부피 차지
- **실효 임계점: 물 ~120ml 부으면 즉시 사이펀 트리거**
- **임계 이상** 부으면 → 즉시 배수, 소크 없음 (ha-xbloom의 옛 버그)
- **임계 이하** 부으면 → 물이 브루어에 **머금어진 채 프로그램된 시간만큼 진짜 소크** → 이후 펌웨어가 자동 탑업해 임계를 넘겨 배수 (2026-05-29 확인: 90ml → 3분 소크 → +38ml → 배수). 공식 앱과, 이제 ha-xbloom(`_TEA_SIPHON_CAP` 경유)이 이렇게 동작

### 레시피 설계 시사점

- YAML의 `pausing` 필드는 **진짜 우림/소크 시간**임 (그 동안 물이 브루어에 머금어짐) — 단 스팁당 pour가 사이펀 임계 이하여야 하며, `_build_tea_payload`가 `_TEA_SIPHON_CAP`(90ml)로 강제함
- 진짜 다분 소크가 **가능** (여기 있던 "flash steep만 가능 / long-soak 구조상 불가" 서술은 틀렸고 2026-05-29 실기로 반증됨)
- 진한 차를 원하면:
  - 찻잎 양 증가 (3g → 5g)
  - `pausing` 증가(더 긴 실소크) 및/또는 다단 스팁
- 우롱·홍차처럼 다회 우림에 적합한 잎차 / 매트차·고급차는 펌웨어가 매 스팁 자동 배수함(무한 침지는 아님)에 유의

### 사이펀 트리거 계산

`임계 물양 = 160 - 찻잎 부피`. 잎 부피는 잎 양 + 잎 종류(말린 정도, 잎 크기)에 따라 다름. 3g 녹차 → 약 30ml 부피 → 임계 약 130ml. 5g 보이차 → 더 큰 부피 → 임계 약 100-110ml.

## 2026-05-29 세션 변경 이력

1. 공식 iOS 앱의 PacketLogger HCI 캡처(티→커피→커피) 디코드. 레시피 패킷 4개 전부 CRC 검증. 프레이밍 + 청크 재조립 규칙(len 필드까지 raw 연결) 확립.
2. **티 이후 그라인딩 수정:** `_async_brew_coffee`에서 QUIT 프렐류드(RECIPE_STOP + BREWER_QUIT + GRINDER_QUIT + RECIPE_START_QUIT) 제거 — 원인이 그것이었음. 8022만 유지. 실기 확인: 티 → 커피 그라인딩 + spiral/온도/진동 정상. 전원 재시작 워크어라운드 삭제.
3. 이제 안 쓰는 `_CMD_BREWER_QUIT` / `_CMD_GRINDER_QUIT` / `_CMD_RECIPE_START_QUIT` 상수 제거.
4. 위 2026-05-28 변경 #3("QUIT 프렐류드가 티 분리 복원")은 우연이었음을 무효화 — 분리는 페이로드로 결정됨.
5. **티 flatten 수정:** 원인은 pattern=3(펌웨어 오파싱 → 316ml = 120 + 76 + 120). `_build_tea_payload`가 이제 pattern=1, `[grind, ratio]` footer, 소크를 timing 바이트[1]에 사용. 실기로 2 스팁 분리 확인.
6. **티 소크 수정:** byte[1] = `round(pausing × 0.6)`(펌웨어가 대기를 ~1.67배로 돌림; 실기 소크가 레시피 초와 일치). 처음 negate했더니 스팁 순서가 뒤집혀 양수로 정정.
7. **티 진짜 소크/사이펀 수정:** `_TEA_SIPHON_CAP = 90` 추가 — wire pour를 사이펀 임계 이하로 캡해서 펌웨어가 소크 후 자동 탑업으로 배수(레시피는 authored 볼륨 유지). 실기 확인: 90ml → 3분 머금은 소크 → +38ml → 배수, 스팁별. "flash steep만 가능 / long-soak 불가" 서술 반증.
8. 공식 앱이 authored 티 볼륨을 **자동 변환**함을 확인(프리셋 120/120 → wire 90/70, 160ml 용량에 맞춤). ha-xbloom은 변환기를 복제하지 않지만 임계 이하 캡 + 펌웨어 탑업으로 동일한 진짜-소크 결과 달성.
9. BP 온도 관찰: 사용자가 BP로 지정한 티 푸어가 바이트 99로 인코딩됨(upstream 추측인 98/100이 아님) — 고정 sentinel이 아니라 계산된 끓는점 근사값으로 추정.

## 2026-05-28 세션 변경 이력

1. `_async_brew_coffee` 신설 — vendored `XBloomClient.brew()` 우회, 인라인 시퀀스로 처리
2. 커피 prelude에 8022 추가 → 푸어 패턴 정상화 (이전엔 spiral이 center로 깨졌음)
3. 커피 prelude에 RECIPE_STOP + BREWER_QUIT + GRINDER_QUIT 추가 → 티 다단 우림 분리 정상화 (이전엔 모든 steep이 한 푸어로 flatten)
4. 8017 추가 (그라인딩 회복 효과 없으나 부작용 없어 유지)
5. 8006 추가 시도 → 효과 없음 → 롤백
6. 티 경로 8004 path 실험 → tea mode 진입 안 함 → 4513/4512로 복구
7. `bypass_volume` / `bypass_temperature` 실제 8102 페이로드에 실어 송신 — YAML의 bypass 필드가 처음으로 동작
8. AGENTS.md의 "8004 tea path" 주장이 실측이 아닌 추론임을 확인, 코드 코멘트로 명시
