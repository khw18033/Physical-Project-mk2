# 확장 다섯 걸음 — 실제로 해 보고 비용을 적은 기록

이 프레임워크는 "새 센서·하드웨어·런타임·외부 서비스·AI 기능은 핵심 코드 수정이 아니라
adapter/provider/capability 등록으로 확장할 수 있어야 한다"(절대 준수 원칙 #7)를 약속한다.
관련 요구사항: AI-B-09(신규 확장 등록·호환성 검증), AI-C-15(도메인·배포 프로파일 분리),
AI-C-18(구성요소 Capability 선언 규약), AI-C-10(기능·자원 등록·탐색), AI-S-06(이종 근거의
점진적 통합), AI-O-06(통합 운영 상태 뷰).

이 문서는 그 약속을 **설명하지 않는다.** 바깥에서 들어온 사람이 할 다섯 가지 확장을 실제로
수행하고, 각각 **파일 몇 개를 만들었고 기존 파일 몇 개를 고쳤으며 그 고침이 데이터였는지
코드였는지**를 적은 기록이다. 다섯 걸음은 모두
`tests/test_extension_walkthrough.py` 가 프로그램으로 다시 수행하므로, 이 문서가 틀리게
되면 그 시험이 먼저 깨진다.

`docs/guides/extending.md` 는 "어떤 Protocol 을 구현하는가" 를 다룬다. 이 문서는 그 다음 —
**구현한 것을 배치에 넣는 데 무엇을 건드려야 하는가** 다.

## 먼저 알아야 할 두 가지

**1. 실행 위치.** 모든 명령은 `mission_runtime/` 에서 돈다. 해석기는 저장소 루트의
`.venv` 다.

```bash
cd <repo>/mission_runtime
PY=../.venv/bin/python
```

**2. 이 문서가 새 파일을 만드는 이유.** 아래 걸음들은 배포된 예시 설정
(`profiles/domains.example.json`, `config/status_ui.fms.example.json`,
`config/providers.hardware.example.json`, `config/status_ui.labels.json`)을 고치지 않고
**사본에** 변경을 담는다. 실제 현장이라면 그 파일들을 직접 고치는 것이 정상 경로이고
파일 수는 더 줄어든다. 이 문서가 사본을 쓰는 것은 배포된 예시를 건드리지 않고도 다섯
걸음이 스스로 검증되게 하기 위한 것뿐이다. 그래서 아래 "비용" 줄은 두 숫자를 같이 적는다 —
이 기록이 만든 파일 수와, **현장에서 실제로 치를 비용**.

---

## 1. 새 도메인과 그 구역들

**목표**: 다섯째 도메인을 두 층·두 구역·자기 RF 모델로 더하고, 콘솔에서 메인 맵·구역
상세·로봇 패널이 도는지 확인한다.

### 1-1. 선언 파일 하나를 쓴다

새 현장은 `tools/profiles/author_zones.py` 가 읽는 작은 선언 하나다. 예시는
`profiles/walkthrough_domain.declaration.json` 이고, 들어가는 것은 이것뿐이다:

* `domain.domain_id` · `label` · `domain_profile` — `domain_profile` 은 자유 문자열이다.
  핵심 코드에 그 이름으로 가는 분기가 없다(원칙 #3).
* `domain.site` — 출처와 **아직 실측되지 않은 칸**(`unverified_fields`). 실존하지 않는
  현장이면 `example: true`.
* `domain.rect` — 메인 맵 index 공간에서 이 도메인이 차지하는 타일.
* `domain.space` — 현장 로컬 **미터** 좌표의 크기. 전역 좌표가 아니다(AI-C-02).
* `domain.levels[]` — 층. 각 층은 `verified` 와 `y_offset` 을 갖는다.
* `domain.rf.<band>` — log-distance 파라미터(`tx_eirp_dbm`,
  `reference_loss_db_at_1m`, `path_loss_exponent`)와 `thresholds_dbm`.
  **`radius_m` 는 적지 않는다** — 적으면 모델과 따로 움직이고, 도구가 그것을 거절한다.
* `zones[]` — `zone_id`(도메인을 가로질러 유일해야 한다) · `level_id` · `rect` ·
  `wifi`(AP 자리와 쓸 밴드) · `edge_node` · `infrastructure[]` · `declared_nodes[]`.

### 1-2. 검증하고 조각을 받는다

```bash
$PY tools/profiles/author_zones.py \
    --declare profiles/walkthrough_domain.declaration.json \
    --out /tmp/fragment.json
```

도구는 두 가지를 한다 — RF 반경을 모델에서 **계산해 채우고**, 파일만 봐도 아는 잘못을
지금 말한다(구역이 도메인 공간을 벗어남, 없는 층을 가리킴, 구역 id 중복, AP 가 구역의
가장 먼 구석을 덮지 못함, 선언되지 않은 엣지 노드 참조). 통과하면 종료 코드 0 과 함께
붙여 넣을 도메인 조각이 나온다.

이 걸음에서 실제로 받은 값: `station_indoor` 밴드(n=2.8)에서
`excellent 4.8 m / handover 56.2 m / floor 128.0 m`. 두 구역의 가장 먼 구석이 AP 에서
33.1 m 이므로 핸드오버 반경 안이고, 경고가 하나도 나오지 않았다.

### 1-3. 프로파일에 붙인다

조각을 `profiles/domains.example.json` 의 `domains[]` 끝에 붙이면 끝이다. 이 기록은
그 대신 사본 `profiles/domains.walkthrough.example.json` 을 만들었다. 배포된 프로파일
전체를 다시 검사한다:

```bash
$PY tools/profiles/author_zones.py --check \
    --profile profiles/domains.walkthrough.example.json
```

`0 error(s)` 가 나와야 한다. 남는 경고 5건은 **원래 있던** 것이다(옥외 구역이 한 AP 의
핸드오버 반경보다 넓은 자리 등) — 경고는 "틀렸다" 가 아니라 "확인되지 않았다" 다.

### 1-4. 콘솔에서 연다

```bash
$PY tools/fms_console/serve.py \
    --domains profiles/domains.walkthrough.example.json \
    --config  config/status_ui.walkthrough.example.json
```

기본 포트는 8800 이다(`--port` 로 바꾼다). 열어서 확인한 것: 메인 맵에 다섯째 타일이
나오고(상태 `idle`, `example` 표시), 도메인을 열면 두 구역이 두 층으로 나오고, 구역
상세에 AP·엣지 노드·고정 인프라가 나오고, 선언한 로봇의 패널에 자원·태그·기능 목록이
나온다. 화면을 띄우지 않고 같은 것을 보려면:

```bash
curl -s 'http://127.0.0.1:8800/api/scene' \
  | $PY -c 'import json,sys; print([d["domain_id"] for d in json.load(sys.stdin)["domains"]])'
# -> ['college', 'river', 'facility', 'defense', 'transit']
```

> **이 확장의 비용**: 만든 파일 2개(선언 1 + 프로파일 사본 1), 고친 기존 파일 0개.
> 현장에서의 실제 비용은 **새 파일 1개(선언) + 기존 데이터 파일 1개에 조각 붙여넣기**이고
> 파이썬은 한 줄도 고치지 않는다. 약속대로다.
>
> 걸림돌 하나만 적어 둔다: 배포된 메인 맵 index 공간은 116×72 이고 기존 네 도메인이
> y=66 까지 쓰고 있어서 남은 자리는 아래쪽 6칸 띠뿐이었다. 다섯째 도메인은 그중 5칸에
> 들어갔다(`rect: {x:4, y:66, w:58, h:5}`). 여섯째를 더하려면 `map.height` 를 키워야
> 하는데, 그것도 같은 파일의 데이터 한 칸이다.

---

## 2. 새 로봇 — 그 주인이 하는 네 걸음

`registry/onboarding.py` 의 docstring 은 로봇을 들고 오는 쪽이 네 가지만 하면 된다고
적는다 — (1) 오버레이에 들어온다, (2) 조인 선언을 한 번 올린다, (3) 명령 어휘를 알린다,
(4) `RobotControlBackend` 어댑터를 구현한다. 그 네 걸음을 가상의 로봇
`railcrawler`(궤도 주행 점검차, 역할 `rail_crawler`)로 그대로 해 봤다. 이 로봇은
기존 어느 역할에도 없는 action `probe_rail_gauge` 를 알린다.

### 2-1. 오버레이에 들어온다

제품은 `providers/overlay.py` 뒤에 숨는다. 계약이 요구하는 것은 "피어 이름으로 닿는다"
하나이고, 오버레이 제품이 없는 배치는 `StaticOverlayProvider` 로 표현한다 — 그것도
정상 구성이다.

```python
from mission_runtime.providers.overlay import StaticOverlayProvider
overlay = StaticOverlayProvider(peers={"railcrawler": True})
```

### 2-2. 조인 선언을 한 번 올린다

```python
from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.registry.onboarding import NodeJoinManifest, NodeOnboarding

manifest = NodeJoinManifest(
    device_id="railcrawler",
    role="rail_crawler",
    node_tags=frozenset({"compute.cpu", "tier.mobile", "sensor.gauge_probe",
                         "sensor.camera.railcrawler", "actuator.rail_drive",
                         "power.battery"}),
    budget=ResourceBudget(compute_units=2.0, memory_mb=1800.0),
    has_camera=True,
    overlay_peer="railcrawler",
    declared_actions=("crawl_to_marker", "probe_rail_gauge", "return_home", "stop"),
    extra={"label": "궤도 점검차 · railcrawler (가상 장비 — 제원 미확인)"},
)
outcome = NodeOnboarding(overlay=overlay).submit(
    manifest, announced_actions=manifest.declared_actions)
```

받은 결과: `accepted=True`, 거절 0건. 처음 보는 action 이름은 거절 사유가 **아니다**.
남은 할 일로 `calibrate_camera`(카메라를 달고 왔고 보정 버전이 없다)와
`learn_appearance`(외형 이미지를 아직 올리지 않았다)가 나온다 — 빠진 칸을 기본값으로
메우지 않는다는 뜻이고, 그래서 "다 갖춘 것처럼 보이는 장치" 가 생기지 않는다.
`accepted` 는 "쓸 수 있다" 가 아니라 "선언이 계약에 맞는다" 다. 장치의 최종 가용성은
백엔드가 판정한다(원칙 #15).

### 2-3. 선언이 그대로 설정 한 줄이 된다

```python
from mission_runtime.registry.onboarding import node_config_entry
row = node_config_entry(manifest)   # -> config/status_ui*.json 의 nodes[] 한 줄
```

이 줄을 `config/status_ui.fms.example.json` 의 `nodes[]` 에 붙인다(이 기록은 사본
`config/status_ui.walkthrough.example.json` 에 붙였다). 손으로 적지 않는 것이 중요하다 —
손으로 적은 줄이 선언과 어긋나면 화면에는 보이고 배치 계산에는 들어가지 않는 노드가 된다.

### 2-4. 어댑터를 구현한다

구현할 것은 `providers/adapters.py::RobotControlBackend` 네 메서드다 —
`declared_actions()` · `readiness()` · `execute()` · `request_stop()` 과
`emergency_stop()`. 수락/거부 분리, 같은 `command_id` 의 멱등 재전달, 취소 우선,
유효기한은 **그 위**에서 `execution/robot_adapter.py::TerminalRobotAdapter` 가 지키므로
어댑터 작성자가 계약을 틀릴 자리가 없다. 베껴 쓸 본보기는
`providers/fakes.py::FakeRobotBackend` 다.

### 2-5. 세우고 확인한다 — **여기서 약속이 한 번 꺾인다**

`tools/fms_console/fleet_runtime.py` 가 장치를 정본 물리 명령 wire 위에 세운다. 그
파일의 `build_runtime()` 은 장치의 명령 어휘를 **역할로** 찾는다:

```python
ROLE_ACTIONS: dict[str, tuple[str, ...]] = {
    "ugv": ("move_forward", "turn", "stop", "scan_mission", "return_home"),
    "uav": ("takeoff", "goto_waypoint", "land", "stop", "return_home"),
    ...
}
```

이 표에 `rail_crawler` 가 없으므로 콘솔은 새 로봇을 **아예 세우지 않는다.** 확인된 결과:

| 확인한 것 | 결과 |
|---|---|
| 자원·태그가 로봇 패널에 나오는가 | 나온다 |
| 기능 목록에 새 기능이 ACTIVE 로 나오는가 | 나온다 |
| 탐지되는가(`discovery.ids()`) | **되지 않는다** — `presence: "declared"` |
| 알린 action 이 명령 가능해지는가 | **아니다** — `{"error": "device_not_attached"}` |

계약 자체는 멀쩡하다. 같은 런타임에 한 줄로 세우면 네 걸음 전부가 성립한다:

```python
runtime = service.commander
runtime.add("railcrawler", ("crawl_to_marker", "probe_rail_gauge", "return_home", "stop"))
runtime.announce_all()
```

그 뒤 확인된 것: 게이트웨이가 공지로 알게 된 어휘가 네 개, `presence` 가
`discovered` 로 바뀌고, `probe_rail_gauge` 명령이 전달·수락·`SUCCEEDED` 로 끝나고,
물리 실행 행이 정확히 한 줄(멱등), 알리지 않은 `takeoff` 는
`{"error": "action_not_announced"}` 로 거절된다.

> **이 확장의 비용**: 만든 파일 0개(설정 줄은 3번 걸음의 사본들에 들어갔다),
> 고친 기존 파일 0개 — **단, 콘솔이 이 로봇을 세우게 하려면
> `tools/fms_console/fleet_runtime.py` 를 고쳐야 한다.** 그 파일은 역할→어휘 표를
> 파이썬으로 들고 있고, 주석은 그것을 "데이터다" 라고 적지만 데이터 파일에 있지 않다.
> 같은 자리에 이미 걸려 있는 장치가 하나 더 있다 — 배포된 설정의 `mt4`(역할
> `fixed_manipulator`)도 표에 없어 세워지지 않는다.
>
> **데이터로 바꾸는 작은 변경 두 줄.** 선언은 이미 어휘를 들고 있다
> (`NodeJoinManifest.declared_actions`). 그것이 읽는 쪽까지 이어져 있지 않을 뿐이다.
> (가) `registry/onboarding.py::node_config_entry()` 가 `declared_actions` 를 설정
> 줄에 같이 싣는다. (나) `build_runtime()` 이
> `actions = node_actions or ROLE_ACTIONS.get(role, ())` 로 그 값을 먼저 쓴다.
> 설정 로더는 노드 줄의 모르는 칸을 이미 통과시키므로 스키마 변경은 필요 없다 —
> `tests/test_extension_walkthrough.py::test_the_config_row_can_already_carry_the_declared_vocabulary`
> 가 그 사실을 고정해 둔다.

---

## 3. 새 capability kind 와 그 provider

**목표**: 지금 아무도 제공하지 않는 kind 를 만들고, 그것을 제공하는 provider 를 등록해,
그 kind 를 필수로 요구하는 기능이 태그를 가진 노드에서 ACTIVE 가 되고 태그가 없는
노드에서는 DISABLED 로 남는 것을 확인한다.

이 걸음에서 쓴 이름: kind `inspection.rail_gauge`, provider `railcrawler-gauge-probe`,
요구 태그 `sensor.gauge_probe`, 기능 `rail_gauge_inspection`.

### 3-1. provider manifest 에 한 줄

`config/providers.hardware.example.json`(이 기록은 사본
`config/providers.walkthrough.example.json`)의 `providers[]` 에 더한다:

```json
{
  "capability_kind": "inspection.rail_gauge",
  "provider_id": "railcrawler-gauge-probe",
  "version": "0-unverified",
  "verified": false,
  "compatibility": {
    "required_hw_tags": ["sensor.gauge_probe"],
    "preferred_hw_tags": [],
    "cost": {"compute_units": 0.3, "memory_mb": 64},
    "priority": 50
  },
  "requirement": {"required": [], "optional": []},
  "supported_inputs": [],
  "supported_outputs": ["rail_gauge_mm"]
}
```

`registry/manifest.py` 는 kind 이름을 **알지 못한다** — 그래서 새 kind 를 더하는 데
로더도 레지스트리도 고치지 않는다. `verified: false` 는 로더가 무시하는 문서용 칸이고
실측 전 추정값이라는 표시다(AI-B-01: 미측정 항목은 구분한다).

### 3-2. 배치 프로파일과 기능 선언에 더한다

같은 배치 설정 파일 안에서 세 칸:

```json
"deployment": { "active_capability_kinds": [ "...", "inspection.rail_gauge" ] },
"capabilities": [ { "kind": "inspection.rail_gauge", "is_core": false,
                    "degrade_rank": 0, "requirement": {} } ],
"functions":    [ { "function_id": "rail_gauge_inspection",
                    "required_capabilities": ["inspection.rail_gauge"],
                    "optional_capabilities": ["observation.mobile"] } ]
```

### 3-3. 라벨 파일에 사람이 읽을 이름을 더한다

화면은 id 를 그대로 쓰지 않는다. 라벨 파일 자리는 설정의 `labels` 키가 정하므로 이것도
데이터다 — `config/status_ui.labels.json`(사본
`config/status_ui.labels.walkthrough.json`)의 `capability_kinds` · `functions` ·
`roles` 에 각각 한 줄. 빠지면 `labels_missing()` 이 그 자리를 이름으로 말해 준다.

### 3-4. 확인한다

```bash
$PY - <<'PY'
import sys; sys.path.insert(0, "tools/status_ui")
import serve
view = serve.StatusService(serve.load_ui_config("config/status_ui.walkthrough.example.json"))
for node in ("railcrawler", "pi6"):
    row = {r["kind"]: r for r in view.resolve(node)["rows"]}["inspection.rail_gauge"]
    print(node, row["state"], row["provider_id"], row["reason"], row["alternatives"])
PY
```

받은 결과:

```text
railcrawler ACTIVE   railcrawler-gauge-probe  selected
pi6         DISABLED None                     no_compatible_provider_within_budget
            alternatives: [{"provider_id": "railcrawler-gauge-probe",
                            "reason": "required_hw_tag_missing:sensor.gauge_probe"}]
```

태그가 없는 노드는 그냥 "안 된다" 가 아니라 **빠진 태그 이름**과 함께 남는다. 기능 축도
같이 움직인다 — `rail_gauge_inspection` 이 ACTIVE 이고 `solo_roles` 가
`["rail_crawler"]` 다(그 기능을 혼자 수행할 수 있는 계층). provider 하나를
`exclude_providers` 로 빼면 그 기능만 DISABLED 가 되고 나머지 기능 15개의 상태는 하나도
바뀌지 않는다(AI-C-05).

> **이 확장의 비용**: 만든 파일 3개(provider manifest · 라벨 · 배치 설정의 사본),
> 고친 기존 파일 0개, 코드 0줄. 현장에서의 실제 비용은 **기존 데이터 파일 3개에 각각
> 한두 줄**이다. 약속대로다.

---

## 4. 새 공간 근거 종류

`perception/spatial_evidence.py` 는 "종류가 늘어나도 `if` 가 늘지 않는다" 고 적는다.
확인해 본 것은 측량 토털스테이션 고정점(정확도를 스스로 선언하는 장비 실측)이다.

### 4-1. 등록은 선언 하나다

```python
from mission_runtime.perception import spatial_evidence as se

kinds = se.DEFAULT_KIND_REGISTRY.copy()      # 배치별로 아는 종류가 다르다
kinds.register(se.EvidenceKindSpec(
    "total_station_fix", se.TIER_MEASURED,
    note="측량 토털스테이션으로 잡은 고정점. 정확도를 스스로 선언한다."))
```

`copy()` 를 거치는 이유: 모듈 기본 레지스트리를 늘리면 이 장비가 없는 배치에서도 그
종류가 등록된 것으로 보이고, 그러면 "장비가 없다" 가 "관측이 없을 뿐" 으로 읽힌다.

종류가 주장할 수 있는 성질은 네 가지뿐이다 — 어떤 격(`measured`/`declared`/`estimated`)
인가, 로컬 환산 기준이 필요한가(`needs_local_reduction`, 절대 측위용), 서명이 필요한가
(`requires_author`, 사람 입력용), 현재 값을 덮는가(`overrides`). 토털스테이션은 격은
`measured` 이지만 `overrides=False` 로 두었다 — **덮기는 사람 실측만의 격**이고, 장비
실측은 선언한 정확도만큼의 가중으로 융합에 들어가는 쪽이 맞다.

### 4-2. 융합에 넣고 확인한다

같은 양(`infrastructure.transit-gate-cam.at`)에 세 근거를 넣었다 — 프로파일 선언
(정확도 없음), 깊이맵(0.4 m), 토털스테이션(0.005 m). `fuse_zone(..., kinds=kinds)` 가
낸 것:

```text
value   (8.0501, 6.0201)   accuracy 0.005   decided_by inverse_variance_fusion
tier    measured           contributing_kinds ('depth', 'total_station_fix')
leave-one-out (unit=kind)
  depth                        influence 0.0001
  infrastructure_declaration   influence 0.0
  total_station_fix            influence 0.6684
```

5 mm 실측이 40 cm 추정을 이긴 것은 종류 이름 때문이 아니라 **선언한 숫자** 때문이다.
정확도를 적지 않은 프로파일 선언은 가중에서 보류되고(`accuracy_unknown`, 가중 0) 빼도
값이 움직이지 않는다 — `0` 이 "영향이 없다" 를, `None` 이 "모른다" 를 말한다.

### 4-3. 등록하지 않은 종류는 어떻게 되는가

같은 묶음에 `"lidar_sweep"` 이라는 등록되지 않은 종류를 하나 섞었다. 결과:

```text
rejected: lidar:gate-cam  lidar_sweep  unregistered_kind
          "register an EvidenceKindSpec for 'lidar_sweep' first"
```

값에는 들어가지 않고, **사유와 고칠 방법이 같이** 남는다. 조용히 버리지 않는 이유는
종류 이름 오타가 값을 바꾸지 않은 채 근거를 사라지게 하는 것이 가장 찾기 어려운 버그이기
때문이다.

> **이 확장의 비용**: 만든 파일 0개, 고친 기존 파일 0개, 코드 0줄 — 배치의 레지스트리를
> 조립하는 자리에 `register()` 호출 한 줄. 약속대로다.

---

## 5. 콘솔의 새 언어

`docs/view-contract.md` §8 은 뷰어가 **파이썬을 고치지 않고** 언어를 늘릴 수 있다고
적는다. 권하는 길은 이렇다 — 서버에는 서버가 아는 언어로 물어 키 집합을 받고, 그 키들을
그대로 가진 자기 쪽 표를 만들어 덮고, 빠진 키는 fallback 언어로 떨어뜨린다.

### 5-1. 키 집합을 받는다

```bash
curl -s 'http://127.0.0.1:8800/api/bootstrap?locale=en' \
  | $PY -c 'import json,sys; print("\n".join(sorted(json.load(sys.stdin)["strings"])))'
```

지금 187개다.

### 5-2. 같은 키를 가진 표를 만든다

이 기록이 만든 것은 `config/strings.ja.walkthrough.json` 이다. 모양:

```json
{
  "locale": "ja",
  "fallback_locale": "en",
  "strings": { "app.title": "FMS", "map.state.operable": "運用可能", "...": "..." }
}
```

지켜야 할 규칙 두 개. **키를 새로 만들지 않는다** — 뷰어가 만든 키는 아무 자리에도
쓰이지 않는다. **빈 문자열을 쓰지 않는다** — 빈칸은 fallback 도 받지 못한다. 키 안에
상태 토큰이 들어가 있으므로(`map.state.operable`, `fn.state.ACTIVE`) 뷰어는
`"map.state." + state` 로 문구를 찾고 상태마다 조건문을 쓰지 않는다. 새 언어도 같은
접두어를 그대로 가져야 한다.

### 5-3. 확인한다

```bash
$PY - <<'PY'
import json, sys; sys.path.insert(0, "tools/fms_console")
from strings import STRINGS, LOCALES
ja = json.load(open("config/strings.ja.walkthrough.json"))["strings"]
print("locales on the server:", LOCALES)
print("missing:", sorted(set(STRINGS["en"]) - set(ja)))
print("invented:", sorted(set(ja) - set(STRINGS["en"])))
PY
```

받은 결과: 서버의 언어 목록은 `('en', 'ko')` 로 **그대로**이고, 빠진 키도 새로 만든 키도
없다. `?locale=ja` 로 서버에 물으면 400 `unknown_locale` 인데, 그것이 계약이 말한 대로다 —
모르는 값을 조용히 기본 언어로 바꿔 주면 뷰어는 자기 표가 쓰이고 있다고 착각한다.

서버 표에 직접 더하는 두 번째 길도 있다(`tools/fms_console/strings.py` 의 `STRINGS` 에
locale 키를 더한다). 그쪽은 모든 뷰어가 함께 쓰게 되지만 **저장소 변경**이고, 두 언어의
키 집합이 같아야 한다는 불변조건을 시험이 지킨다.

> **이 확장의 비용**: 만든 파일 1개(뷰어 쪽 문자열표), 고친 기존 파일 0개, 코드 0줄.
> 약속대로다. 비용은 번역 187줄 그 자체이고 그것은 프레임워크가 줄여 줄 수 있는 것이
> 아니다.

---

## 다섯 걸음을 합쳐서

| 확장 | 만든 파일 | 고친 기존 파일 | 핵심 코드 수정 |
|---|---|---|---|
| 1. 새 도메인·구역 | 2 (현장이면 1) | 0 (현장이면 데이터 1) | 없음 |
| 2. 새 로봇 | 0 | 0 | **필요하다** — `tools/fms_console/fleet_runtime.py` |
| 3. 새 capability kind·provider | 3 (현장이면 0) | 0 (현장이면 데이터 3) | 없음 |
| 4. 새 공간 근거 종류 | 0 | 0 | 없음 |
| 5. 새 언어 | 1 | 0 | 없음 |

네 걸음은 약속대로 데이터만으로 끝났다. 꺾인 자리는 하나이고 **원칙 #3 과 #7 이 같이
걸린다** — 역할 이름으로 명령 어휘를 고르는 표가 파이썬 안에 있어서, 새 역할의 로봇은
설정만으로 세워지지 않는다. 고치는 데 필요한 것은 2-5 에 적은 두 줄이고, 그 두 줄이
없는 동안 어떤 일이 벌어지는지는 `tests/test_extension_walkthrough.py` 가 통과하는
시험으로 고정해 두었다. 표가 데이터로 옮겨지면 그 시험이 깨지고, 그때 같이 지우는 것이
맞다.

## 다시 돌려 보기

```bash
cd <repo>/mission_runtime
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OTEL_SDK_DISABLED=true \
  ../.venv/bin/python -m pytest -q tests/test_extension_walkthrough.py
```

이 시험들은 패키지 밖의 자산(모델 가중치·데이터셋·실제 브로커)에 의존하지 않고, 쓰는
것은 모두 `tmp_path` 안에 쓴다.

## 이 걸음들이 만든 파일

| 파일 | 걸음 | 무엇인가 |
|---|---|---|
| `profiles/walkthrough_domain.declaration.json` | 1 | 새 현장 선언(입력) |
| `profiles/domains.walkthrough.example.json` | 1 | 다섯째 도메인이 붙은 도메인 프로파일 |
| `config/providers.walkthrough.example.json` | 2·3 | 새 provider 다섯 줄이 더해진 manifest |
| `config/status_ui.walkthrough.example.json` | 2·3 | 새 kind·기능·노드가 더해진 배치 설정 |
| `config/status_ui.labels.walkthrough.json` | 3 | 새 어휘의 사람이 읽을 이름 |
| `config/strings.ja.walkthrough.json` | 5 | 뷰어가 더한 세 번째 언어 |
| `tests/test_extension_walkthrough.py` | 1~5 | 다섯 걸음을 다시 수행하는 시험 |
