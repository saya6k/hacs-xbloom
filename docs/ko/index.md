# XBloom Coffee Machine — Home Assistant 통합

> 이 페이지는 [`en/index.md`](../en/index.md)의 번역본입니다. 영문판이 source of truth이며, 한글본은 뒤늦게 동기화될 수 있습니다.

[XBloom Studio](https://xbloom.com/) 커피머신을 Home Assistant에서 로컬 블루투스로 제어. 추출, 그라인딩, 저장된 레시피 실행, Assist(LLM) 노출 — 모두 클라우드 없이.

리버스 엔지니어링된 두 개의 BLE upstream을 vendor한 위에서 구축:

- [`fhenwood/PyBloom`](https://github.com/fhenwood/PyBloom) — `custom_components/xbloom/src/xbloom/`. 연결·상태·그라인더/브루어/저울 컴포넌트와 커피 추출 플로를 구동하는 클래스 기반 클라이언트 라이브러리.
- [`brAzzi64/xbloom-ble`](https://github.com/brAzzi64/xbloom-ble) — `custom_components/xbloom/src/xbloom-ble/`. `brewing.py`의 차(tea) 레시피 플로가 가져다 쓰는 HCI 스눕 검증 프로토콜 디코딩(`PROTOCOL.md`).

이 통합을 가능하게 한 프로토콜 작업에 Frederic, PyBloom 기여자들, Bruno Azzinnari에게 큰 감사를.

## 기능

- **수동 제어** — 커스텀 온도/용량으로 추출, 커스텀 크기/RPM으로 그라인딩, 저울 **영점(tare)**, 트레이 진동.
- **레시피 — 3계층 구조**:
  1. **번들 기본 레시피 10개** (`default_recipes.py`) — 약/중약 워시드/강배전 핫·아이스, 히비스커스/홍차/녹차/히비스커스 아이스티. 설치 즉시 노출.
  2. **`configuration.yaml`** 레시피(레거시 경로). 이름으로 default를 덮어씀.
  3. **OptionsFlow CRUD** — UI에서 추가/수정/삭제, HA 재시작 불필요. 이름으로 모든 계층을 덮어씀. 설정 → 기기 및 서비스 → XBloom → ⋯ → **구성**.
- **차 레시피** (`cup_type: tea`) — 각 우려내기를 한 번의 pour로 표현, `pausing`은 다음 steep까지의 *대기* 시간(실제 침지 시간 아님). 펌웨어가 추출 → 사이펀 배수를 내부적으로 처리.
- **선택된 레시피 조회** — recipe select 엔티티의 `recipe` 속성에 pours / bypass / 온도 등 전체 파라미터가 노출됨. 개발자 도구 → 상태 → `select.xbloom_recipe`, 또는 템플릿에서 `{{ state_attr('select.xbloom_recipe', 'recipe').pours }}`.
- **Easy Mode 슬롯 쓰기** — 현재 선택된 레시피를 머신의 온보드 슬롯 A / B / C에 푸시 (장치의 Auto/Easy Mode 버튼).
- **선택적 클라우드 레시피 동기화** — XBloom 계정을 연결하면 위의 로컬 계층과 별개로 XBloom 클라우드 계정의 레시피를 검색·가져오기·생성·수정·삭제할 수 있습니다. 완전히 선택 사항이며, 계정 없이도 다른 모든 기능은 그대로 동작합니다. 아래 [클라우드 레시피 동기화](#클라우드-레시피-동기화-선택) 참조.
- **실시간 텔레메트리** — 브루어 온도, 저울 무게, 수위 상태, 현재 추출 단계.
- **이벤트 엔티티** — 에러 이벤트(물 부족, 원두 없음, 비정상 dose, 비정상 기어)와 알림(그라인딩 시작/완료, 추출 시작, 추출 완료, bloom, paused, 레시피 완료, 차 침지).
- **LLM API** — 추출, 레시피 실행, 레시피 목록, 상태를 Home Assistant Assist에 노출 (안전 확인: 원두, 필터, 저울 위 컵).
- **한국어·영어** UI 번역.

## 설치 (HACS)

1. HACS → Integrations → ⋮ → **Custom repositories**에서 이 repo URL을 카테고리 **Integration**으로 추가.
2. **XBloom Coffee Machine** 설치.
3. Home Assistant 재시작.
4. 설정 → 기기 및 서비스 → **통합 추가** → "XBloom" 검색.
5. 장치의 BLE MAC 주소 입력 (터미널에서 `xbloom scan` 실행 또는 XBloom Studio 확인).

## 수동 설치

`custom_components/xbloom/`을 HA config의 `custom_components/`에 복사 후 재시작.

## 구성

초기 config flow가 MAC 주소 + 텔레메트리 주기 + idle 연결 해제 타임아웃을 처리합니다. 그 외는 Options flow에서 (설정 → 기기 및 서비스 → XBloom → ⋯ → **구성**).

### 레시피

우선순위 낮음 → 높음 3계층:

| 계층 | 위치 | 변경 방법 | 비고 |
| --- | --- | --- | --- |
| Default | `custom_components/xbloom/default_recipes.py` | 코드 수정만 | 번들 10개. 런타임에서는 읽기 전용. |
| YAML | `configuration.yaml`의 `xbloom: recipes:` | 편집 후 HA 재시작 | 아래 스키마 따름. 이름으로 default 덮어씀. |
| OptionsFlow | `entry.options[CONF_RECIPES]` | HA UI | 추가 / 수정 / 삭제. 이름으로 모든 것 덮어씀. |

번들 default를 덮어쓰고 싶으면 YAML이나 OptionsFlow에서 같은 이름으로 추가하면 됩니다.

### YAML 레시피 형식

```yaml
xbloom:
  recipes:
    - name: Morning V60
      cup_type: omni_dripper      # x_pod | omni_dripper | other | tea
      grind_size: 35
      dose_g: 18
      ratio: 13.9                 # 총 물량 = dose_g * ratio
      bypass_volume: 0            # 0이면 bypass 비활성
      bypass_temperature: 0
      pours:
        - volume_ml: 50
          temperature_c: 93
          flow_rate: 3.0
          pause_seconds: 30
          pattern: spiral         # center | circular | spiral
          vibration: after        # none | before | after | both
        - volume_ml: 200
          temperature_c: 92
          flow_rate: 3.0
          pause_seconds: 0
          pattern: spiral
    - name: Sencha
      cup_type: tea               # dose_g는 0이어야 하며, 차 레시피에서 ratio는 의미 없음
      grind_size: 0
      dose_g: 0
      pours:
        - volume_ml: 120
          temperature_c: 80
          pause_seconds: 60       # 다음 steep까지의 대기 시간 (초)
        - volume_ml: 120
          temperature_c: 80
          pause_seconds: 0
```

차 레시피는 각 pour가 한 번의 steep. xBloom Omni Tea Brewer의 사이펀은 약 ~120ml에서 트리거(찻잎 부피에 따라 변동) — `pause_seconds`는 *steep 사이의 대기 시간*이지 실제 침지 시간이 아닙니다. 사이펀 메커니즘 상세는 [`brewing-notes.md`](./brewing-notes.md) 참조.

필드별 스키마는 위의 **YAML 레시피 형태**를 참고하세요.

### UI(OptionsFlow)로 레시피 관리

설정 → 기기 및 서비스 → XBloom → ⋯ → **구성** → 메뉴:

- **설정** — 텔레메트리 간격, idle 해제 타임아웃.
- **레시피 추가** — YAML 블록 붙여넣기 → 스키마 검증 → 옵션에 저장 → 통합 자동 reload.
- **레시피 수정** — UI로 추가한 레시피 중에서 선택(defaults / YAML은 여기서 읽기 전용). YAML이 미리 채워진 채로 편집 가능. `name:` 변경(이름 변경)도 허용.
- **레시피 삭제** — UI로 추가한 레시피 중에서 선택 후 확정.

번들 default와 YAML 레시피는 의도적으로 Edit/Delete 드롭다운에 나타나지 않습니다(소스가 코드/파일이라 UI 소유가 아님). Default를 제거하고 싶으면 OptionsFlow에서 같은 이름으로 추가해 덮어쓰세요.

## 클라우드 레시피 동기화 (선택)

XBloom 앱 계정을 연결하면 공식 앱에서 보이는 것과 동일한 XBloom 클라우드 계정의
레시피를 검색·가져오기·생성·수정·삭제할 수 있습니다 — 위의 3계층 로컬 레시피 관리와
완전히 독립적입니다. 로컬 레시피 관리는 계정 없이도 아무 제약 없이 동작하므로,
필요 없으면 이 단계를 건너뛰어도 됩니다.

**설정**: 초기 설정의 config flow에서 "XBloom Cloud Account" 단계에 XBloom 앱
이메일/비밀번호를 입력(두 필드 모두 선택 사항이며 건너뛰기 가능)하거나, 나중에 설정
→ 기기 및 서비스 → XBloom → ⋯ → **구성** → **클라우드 계정**에서 추가/변경/삭제할 수
있습니다. Apple로 로그인해서 XBloom 비밀번호가 없다면, XBloom 자체의 "비밀번호 찾기"
플로우(Apple이 릴레이하는 이메일 사용, 앱의 계정 설정에서 확인 가능)로 비밀번호를
먼저 설정한 뒤 입력하세요.

계정을 설정하면 6개 서비스를 사용할 수 있습니다 (개발자 도구 → 액션, 또는
`xbloom.cloud_*`):

| 서비스 | 기능 |
| --- | --- |
| `cloud_search_recipes` | 계정의 모든 레시피 목록 조회, 이름으로 필터링 가능. |
| `cloud_import_recipe` | `share-h5.xbloom.com` 링크, `collective.xbloom.com/recipe/<id>` 커뮤니티 허브 링크, 또는 share id로 레시피를 가져와 로컬 레시피로 저장. 계정 불필요 — 클라우드 계정 설정 없이도 동작. |
| `cloud_create_recipe` | 인라인 `recipe_yaml`(위 "레시피 추가"와 동일한 형식) 또는 `recipe_name`으로 기존 로컬 레시피를 지정해 클라우드에 새 레시피 생성. 새 `table_id`와 `share_url` 반환. |
| `cloud_edit_recipe` | `table_id`로 기존 클라우드 레시피의 필드 일부 변경; 생략한 필드는 그대로 유지(먼저 현재 레시피를 가져온 뒤 patch). |
| `cloud_delete_recipe` | `table_id`로 클라우드 레시피 영구 삭제. 되돌릴 수 없음. |

```yaml
service: xbloom.cloud_import_recipe
data:
  share_url: "https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D"
```

Assist(LLM)에서는 6개 작업 모두 도구로 노출되어 있습니다: `import_xbloom_cloud_recipe`,
`search_xbloom_cloud_recipes`, `create_xbloom_cloud_recipe`,
`export_xbloom_recipe_to_cloud`, `edit_xbloom_cloud_recipe`,
`delete_xbloom_cloud_recipe`(마지막 도구는 브루잉 도구의 원두/필터 확인과 동일하게
삭제 전 명시적 확인이 필요합니다).

## 그라인드 사이즈 참고 (XBloom Studio 스케일, 0–80)

| 추출 방법 | 범위 |
| --- | --- |
| Turkish | 0–3 |
| Espresso | 0–18 |
| Moka Pot | 17–44 |
| Filter Coffee Machine | 12–66 |
| Aeropress | 13–71 |
| Siphon | 18–57 |
| V60 | 21–47 |
| Pour Over | 22–68 |
| Steep-and-release | 25–59 |
| Cupping | 26–61 |
| French Press | 47–80 |
| Cold Brew | 58–80 |
| Cold Drip | 59–80 |

## 알려진 제한사항

- **티 → 커피 그라인딩 실패**: 티 brew 후 다음 커피 brew에서 그라인더 단계를 건너뜀(추출은 동작하지만 원두를 갈지 않음). 펌웨어가 진입한 티 상태를 빠져나오는 BLE 명령이 문서화되어 있지 않음 — [`brewing-notes.md`](./brewing-notes.md#known-limitation--grinding-fails-after-a-tea-brew). **워크어라운드:** 티 brew와 다음 커피 brew 사이에 머신 전원 재시작.
- **티 사이펀은 flash-extract 방식**: xBloom Omni Tea Brewer는 `pausing` 값과 무관하게 ~120ml에 사이펀 배수. 장시간 침지를 전제로 한 레시피(말차, 분 미만의 짧은 steep을 여러 번 하는 gong-fu 스타일 등)는 의도대로 동작하지 않음. 상세는 [`brewing-notes.md`](./brewing-notes.md#xbloom-omni-tea-brewer--siphon-mechanics).
- **일부 펌웨어의 MachineInfo**: 특정 XBloom 펌웨어 리비전은 `RD_MachineInfo` BLE 알림을 푸시하지 않아 Model / Serial / Firmware 센서가 `unknown`으로 남을 수 있음. 이런 펌웨어에서 수위 binary sensor는 이벤트 기반(RD_ErrorLackOfWater) 감지로 fallback.
- **수동 컵 감지**: 저울은 전원 인가 시 존재하는 모든 무게를 자동 영점화하므로, 부팅 전에 놓인 컵은 0 g으로 읽힘. 이 경우 LLM `execute_xbloom_recipe` 도구가 명시적 확인을 요청.
- **레시피 물 출처**: 수동 pour 엔티티는 water-source select(탱크 vs. 직수)를 따르지만, 레시피 실행은 그렇지 않음 — 펌웨어가 자체 추출 시퀀스를 내부적으로 제어.

## 개발

이 repo의 아키텍처와 코딩 컨벤션은 `AGENTS.md` 참조. 추출 시퀀스의 BLE 세부 사항·펌웨어 거동·알려진 제약(티 → 커피 그라인딩 등)·Tea Brewer 사이펀 동작은 [`brewing-notes.md`](./brewing-notes.md) 참조.

실제 Home Assistant 설치에 대해 통합을 테스트하기 위한 devcontainer가 제공됩니다. VS Code에서 Dev Containers 확장으로 폴더를 열고 실행:

```bash
scripts/develop
```

컨테이너 내부에서 HA가 표준 포트 8123을 바인딩. 호스트 네트워크의 프로덕션 HA 인스턴스와 구분되도록 컨테이너 호스트명은 `ha-xbloom-dev`로 설정. VS Code가 8123을 호스트로 포워딩 (호스트에 이미 8123이 사용 중이면 자동으로 다른 포트 선택).

## 라이선스

[MIT](LICENSE) — vendored upstream 양쪽의 저작권(`fhenwood/PyBloom` at `src/xbloom/`, `brAzzi64/xbloom-ble` at `src/xbloom-ble/`, 각자 MIT `LICENSE` 파일 보유)을 보존하고 통합 자체의 저작권 행을 추가.
