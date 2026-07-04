# XBloom Coffee Machine — Home Assistant 통합

> 이 페이지는 [`en/index.md`](../en/index.md)의 번역본입니다. 영문판이 source of truth이며, 한글본은 뒤늦게 동기화될 수 있습니다.

[XBloom Studio](https://xbloom.com/) 커피머신을 Home Assistant에서 로컬 블루투스로 제어. 추출, 그라인딩, 저장된 레시피 실행, Assist(LLM) 노출 — 모두 클라우드 없이.

리버스 엔지니어링된 두 개의 BLE upstream을 vendor한 위에서 구축:

- [`fhenwood/PyBloom`](https://github.com/fhenwood/PyBloom) — `custom_components/xbloom/src/xbloom/`. 연결·상태·그라인더/브루어/저울 컴포넌트와 커피 추출 플로를 구동하는 클래스 기반 클라이언트 라이브러리.
- [`brAzzi64/xbloom-ble`](https://github.com/brAzzi64/xbloom-ble) — `custom_components/xbloom/src/xbloom-ble/`. `brewing.py`의 차(tea) 레시피 플로가 가져다 쓰는 HCI 스눕 검증 프로토콜 디코딩(`PROTOCOL.md`).

이 통합을 가능하게 한 프로토콜 작업에 Frederic, PyBloom 기여자들, Bruno Azzinnari에게 큰 감사를.

## 기능

- **로컬 레시피가 source of truth** — 모든 레시피는 HA 안에서 고유한 로컬 `uid`를 갖고, Recipe 드롭다운이 보여주고 추출하는 대상도 바로 이것입니다. 설치 시 1회 시드됩니다(계정이 연결돼 있으면 클라우드 계정 레시피, 아니면 XBloom 공식 공개 레시피). 이후로는 백그라운드 동기화가 없습니다 — HA UI, 레시피 서비스, `configuration.yaml`로 직접 관리하세요.
- **교차 식별자 지정** — 레시피를 다루는 모든 서비스/도구는 `recipe` 필드 하나로 로컬 uid, 클라우드 table id, 공유 URL/id, 또는 정확한 이름을 받습니다.
- **수동 제어** — 커스텀 온도/용량/유량/푸어 패턴으로 추출, 커스텀 크기/RPM으로 그라인딩, 저울 **영점(tare)**, 트레이 진동.
- **브루별 오버라이드** — 레시피를 수정하지 않고 그라인드/RPM/도즈/비율/컵 타입/바이패스를 조정해 브루(dose/ratio 오버라이드는 pour 볼륨을 비례 재계산). 레시피를 선택하면 Grind Size / RPM 슬라이더도 그 값으로 동기화됩니다.
- **차 레시피** (`cup_type: tea`) — 각 우려내기를 pour 하나로 표현, `pausing`이 곧 소크(우림) 초. 펌웨어가 추출 → 소크 → 사이펀 배수를 내부적으로 처리. 사이펀 메커니즘은 [`brewing-notes.md`](./brewing-notes.md) 참고.
- **선택된 레시피 조회** — recipe select 엔티티의 `recipe` 속성에 pours / bypass / 온도 등 전체 파라미터가 노출됨. 개발자 도구 → 상태 → `select.xbloom_recipe`, 또는 템플릿에서 `{{ state_attr('select.xbloom_recipe', 'recipe').pours }}`.
- **Easy Mode 슬롯 쓰기** — 슬롯 버튼 또는 `write_recipe_to_easy_slot` 서비스(로컬에 없는 공유 URL은 자동 가져오기)로 어떤 레시피든 온보드 슬롯 A/B/C에 기록. 읽기 전용 센서 엔티티가 각 슬롯에 저장된 내용을 보여줌.
- **클라우드는 가져오기/내보내기 경계** — 공유된 레시피를 가져오거나(`cloud_import_recipe`, 계정 불필요), 로컬 레시피를 내보내 공유 링크를 받거나(`cloud_export_recipe`), XBloom 공개 커뮤니티 허브를 검색(`cloud_search_collective_recipes`). 계정은 선택 사항이며 내보내기에만 필요합니다. 아래 [레시피 서비스](#레시피-서비스) 참고.
- **실시간 텔레메트리** — 브루어 온도, 저울 무게, 수위 상태, 현재 추출 단계.
- **이벤트 엔티티** — 에러(물 부족, 원두 없음, 비정상 dose/기어)와 알림(그라인딩/추출/pour/bloom/일시정지/완료/차 침지).
- **LLM API** — 상태, 레시피 CRUD, 추출, 슬롯 쓰기, 가져오기/내보내기, 허브 검색을 Assist에 노출(안전 확인: 원두, 필터, 저울 위 컵, 삭제).
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

설치 시 레시피 저장소가 **1회** 시드됩니다: 작은 번들 세트가 즉시 기록되고(드롭다운이 절대 비지 않도록), 이후 백그라운드 작업이 XBloom 클라우드 계정 레시피(계정이 연결돼 있으면) 또는 XBloom 공식 공개 레시피(없으면)를 가져옵니다 — 이미 있는 이름은 건너뜁니다. 가져오기가 실패하면(예: 첫 부팅 시 인터넷 없음) 다음 재시작 때 재시도합니다. 계정을 **나중에** 연결하면 그 시점에 계정 레시피가 한 번 더 시드됩니다. 그 이후로는 백그라운드 동기화가 없습니다 — 로컬 저장소는 온전히 사용자의 것입니다.

레시피는 `configuration.yaml`에도 정의할 수 있습니다 — 로컬 저장소보다 우선순위가 낮음(같은 이름의 저장소 레시피가 이김; UI에서 YAML 레시피를 삭제하면 숨겨짐):

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
          pause_seconds: 60       # 다음 steep 전까지의 소크 시간
        - volume_ml: 120
          temperature_c: 80
          pause_seconds: 0
```

차 레시피는 각 pour가 한 번의 steep입니다. `pause_seconds`는 스팁당 pour가 사이펀 임계 이하로 유지되는 한(통합이 자동으로 이를 보장) 진짜 소크 시간(물이 브루어에 머금어짐)입니다. 사이펀 메커니즘 상세는 [`brewing-notes.md`](./brewing-notes.md) 참조.

### UI로 레시피 관리

설정 → 기기 및 서비스 → XBloom → ⋯ → **구성** → **레시피 추가** / **레시피 수정** / **레시피 삭제**. 삭제는 로컬에만 적용되며 즉시 반영됩니다 — 클라우드 계정의 사본은 건드리지 않습니다. YAML 레시피도 Edit/Delete에 나타나며, 수정하면 로컬 오버라이드로 저장됩니다(YAML 파일 자체는 건드리지 않음). 삭제하면 tombstone 처리(같은 이름으로 다시 추가하면 복원).

### 브루별 오버라이드

저장된 레시피를 수정하지 않고 단일 브루에만 적용되는 조정으로 실행할 수 있습니다. **Recipe** select에서 레시피를 선택하면 **Grind Size** / **Grinder RPM** 슬라이더가 그 값으로 동기화되고, 브루 시점에 슬라이더가 들고 있는 값이 사용됩니다. 차·no-grind 레시피는 grind/RPM을 무시합니다.

모든 최상위 스칼라를 브루별로 오버라이드할 수 있습니다: `grind_size`, `rpm`, `dose_g`, `ratio`, `cup_type`, `bypass_volume`, `bypass_temperature`. `dose_g`/`ratio` 오버라이드는 pour 볼륨을 비례 재계산합니다(pours 합 + bypass = dose × ratio). bypass가 없는 레시피에도 추가할 수 있고, 차 레시피는 bypass도 grind도 없습니다.

```yaml
service: xbloom.execute_recipe
target:
  device_id: <your xbloom device>   # 머신이 하나뿐이면 생략 가능
data:
  recipe: Morning V60   # uid / 클라우드 id / 공유 URL / 이름 — 선택, 기본값은 현재 선택된 레시피
  grind_size: 42
  rpm: 90
  dose_g: 20            # 총 물량 = dose × ratio를 유지하도록 pour가 재계산됨
  bypass_volume: 50
  bypass_temperature: 92
```

Assist(LLM)에서는 `get_xbloom_recipe`가 레시피 전체 상세(grind, RPM, bypass, 각 pour의 볼륨/유량/패턴)를 반환하고, `execute_xbloom_recipe`는 같은 스칼라 오버라이드에 더해 pour별 `pour_overrides`(0-based `pour_index`로 지정하는 볼륨/유량/패턴)를 받아, 에이전트가 요청에 따라 개별 pour를 조정할 수 있습니다.

## 레시피 서비스

9개 서비스가 레시피 전체 표면을 커버합니다(개발자 도구 → 액션). 서비스가 `recipe`를 받는 곳이면 어디든 로컬 **uid**, **클라우드 table id**, **공유 URL/id**, 또는 정확한 **이름**을 받습니다 — `list_recipes`가 uid를 반환합니다.

| 서비스 | 기능 |
| --- | --- |
| `list_recipes` | 모든 로컬 레시피 목록(uid, source, 컵 타입, dose, grind, pour 수, 클라우드 id/공유 URL 유무), 이름으로 필터링 가능. |
| `create_recipe` | 인라인 `recipe_yaml`로 새 로컬 레시피 생성. `uid` 반환. 업로드 없음. |
| `edit_recipe` | 로컬 레시피의 필드 일부 변경; 생략한 필드는 유지. 로컬에 없는 공유 URL을 지정하면 먼저 복사본을 가져온 뒤 수정. |
| `delete_recipe` | 로컬 레시피 삭제 — 드롭다운에 즉시 반영. 클라우드 계정 사본은 **건드리지 않음**(클라우드 삭제는 공식 앱에서). |
| `execute_recipe` | 레시피 추출, 선택적 브루별 스칼라 오버라이드(위 참조). |
| `write_recipe_to_easy_slot` | 온보드 Easy Mode 슬롯 A/B/C에 레시피 저장. 로컬에 없는 공유 URL은 먼저 자동 가져오기. |
| `cloud_import_recipe` | `share-h5.xbloom.com` 링크, `collective.xbloom.com/recipe/{id}` 커뮤니티 허브 링크, 또는 share id로 레시피를 가져와 로컬에 저장(새 uid 부여). 계정 불필요. |
| `cloud_export_recipe` | 로컬 레시피를 **본인** XBloom 클라우드 계정에 올리고 클라우드 `id`, 공유 `link`, 레시피를 반환. 같은 레시피를 재-export하면 같은 클라우드 엔트리가 갱신됨(링크 유지). 계정 미설정 시 업로드 없이 레시피만 반환. |
| `cloud_search_collective_recipes` | XBloom의 **공개** 커뮤니티 레시피 허브(collective.xbloom.com) 검색 — 계정 불필요. 검색어, coffee/tea, official/user, 멀티 셀렉트 머신/컵 타입/원산지/품종/가공/로스팅/풍미 필터와 정렬. |

```yaml
service: xbloom.cloud_import_recipe
data:
  share_url: "https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D"
```

collective-search 필터 드롭다운은 허브 분류 코드의 스냅샷입니다. XBloom이 드롭다운이 모르는 새 분류를 추가했다면 숫자 코드를 직접 입력하세요(필드가 custom value를 받습니다) — 그리고 다음 릴리스의 스냅샷·번역에 반영할 수 있도록 [이슈](https://github.com/saya6k/hacs-xbloom/issues)로 코드를 제보해 주세요.

**클라우드 계정(선택)** — `cloud_export_recipe`만 계정이 필요합니다. 초기 설정의 config flow "XBloom Cloud Account" 단계에서 XBloom 앱 이메일/비밀번호를 입력하거나, 나중에 설정 → 기기 및 서비스 → XBloom → ⋯ → **구성** → **클라우드 계정**에서 추가/변경/삭제하세요. Apple로 로그인해서 XBloom 비밀번호가 없다면, XBloom 자체의 "비밀번호 찾기" 플로우(Apple이 릴레이하는 이메일 사용, 앱의 계정 설정에서 확인 가능)로 먼저 설정하세요.

Assist(LLM)에서는 같은 표면이 도구로 노출됩니다: `list_xbloom_recipes`, `get_xbloom_recipe`, `create_xbloom_recipe`, `edit_xbloom_recipe`, `delete_xbloom_recipe`(삭제 전 명시적 확인 요청), `execute_xbloom_recipe`, `write_xbloom_easy_slot`, `import_xbloom_cloud_recipe`, `export_xbloom_recipe`, `search_xbloom_collective_recipes`.

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

- **XBloom Original 미지원**: 이 통합은 XBloom **Studio**와만 블루투스 LE로 통신합니다(`manifest.json`의 `bluetooth` 매처 참조) — Original은 완전히 다른 Wi-Fi 프로토콜을 쓰며, 유지보수자가 Original 기기를 보유하고 있지 않아 테스트할 수 없습니다. 클라우드 API 역시 `adaptedModel: 1`(Studio)이 하드코딩되어 있어, Original 전용 계정에서는 계정 레시피 시드와 `cloud_export_recipe`가 검증되지 않았습니다.
- **일부 펌웨어의 MachineInfo**: 특정 펌웨어 리비전은 `RD_MachineInfo`를 아예 푸시하지 않아 Model / Serial / Firmware 센서가 `unknown`으로 남을 수 있음. 이런 펌웨어에서 수위 binary sensor는 이벤트 기반 감지로 fallback.
- **수동 컵 감지**: 저울은 전원 인가 시 존재하는 모든 무게를 자동 영점화하므로, 부팅 전에 놓인 컵은 0 g으로 읽힘 — 이 경우 LLM `execute_xbloom_recipe` 도구가 명시적 확인을 요청.
- **레시피 물 출처**: 수동 pour 엔티티는 water-source select(탱크 vs. 직수)를 따르지만, 레시피 실행은 그렇지 않음 — 펌웨어가 자체 추출 시퀀스를 내부적으로 제어.
- **차 소크 타이밍은 근사 보정값**: steep 사이 대기 시간은 레시피의 `pausing` 초에서 몇 번의 스톱워치 측정으로 도출한 계수로 스케일링됩니다 — 더 정밀한 타이밍이 필요하면 [`brewing-notes.md`](./brewing-notes.md) 참고.

## 개발

이 repo의 아키텍처와 코딩 컨벤션은 `AGENTS.md` 참조. 추출 시퀀스의 BLE 세부 사항, 펌웨어 거동, Tea Brewer 사이펀 동작은 [`brewing-notes.md`](./brewing-notes.md) 참조.

실제 Home Assistant 설치에 대해 통합을 테스트하기 위한 devcontainer가 제공됩니다. VS Code에서 Dev Containers 확장으로 폴더를 열고 실행:

```bash
scripts/develop
```

컨테이너 내부에서 HA가 표준 포트 8123을 바인딩. 호스트 네트워크의 프로덕션 HA 인스턴스와 구분되도록 컨테이너 호스트명은 `hacs-xbloom-dev`로 설정. VS Code가 8123을 호스트로 포워딩 (호스트에 이미 8123이 사용 중이면 자동으로 다른 포트 선택).

## 라이선스

[MIT](../../LICENSE) — vendored upstream 양쪽의 저작권(`fhenwood/PyBloom` at `src/xbloom/`, `brAzzi64/xbloom-ble` at `src/xbloom-ble/`, 각자 MIT `LICENSE` 파일 보유)을 보존하고 통합 자체의 저작권 행을 추가.
