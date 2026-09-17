# LOTUSim-Energy 기법의 프레임워크 반영 계획

상태: **계획(미구현) — 승인 후 착수**.
근거: [[lotusim-energy]](`docs/obsidian/papers/lotusim-energy.md`, arXiv 2609.17124 원문 7p 전체 확인),
`docs/ai/design/river-domain-capability-extension.md`.

## 0. 먼저 — 이미 있는 것 (다시 만들지 않는다)

논문을 읽고 우리 저장소를 대조한 결과, LOTUSim이 제공하는 것의 상당 부분은 **이미
구현돼 있다**. 반영 계획의 절반은 "새로 만들 것"이 아니라 "이미 있으니 건드리지
말 것"을 명시하는 일이다.

| LOTUSim의 것 | 우리 쪽 이미 있는 것 |
|---|---|
| 물리/에이전트상호작용/렌더링 3-클라이언트 분리 | `providers/adapters.py`의 Protocol 분리 (더 일반적) |
| Task별 필요 센서·정보 정의(Table II) | `perception/purpose_requirements.py` — `PurposeRequirement`(required/preferred fields), `evaluate_gap()` |
| 환경 데이터(MetOcean) 흡수 후 예측장 생성 | `perception/environment_prior.py` — `PriorInfoRecord`/`PriorInfoStore`(출처·버전·유효범위 관리, 관측과 분리) |
| 관측 결과 기반 동적 임무 재계획 | `perception/reobservation_policy.py`(이득>비용 게이트) + `perception/viewpoint_selection.py`(이득/비용 비율 순위) + `decision/info_request.py`(`EvidenceNeed` → 어떤 capability로 채울지 선택) |
| 자원 조건에 따른 실행 선택 | `selection/selector.py` + `CompatibilityProfile`(required/preferred 태그, 예산) |
| 사람 개입 지점 | `contracts/physical_command.py` + AI-C-19 경계(AI는 명령 발급 안 함) |
| 다중 실행영역 배치 | `providers/k3s.py`, `runtime/clusters.py` |

## 1. Gazebo / ROS 2 / Unity — provider로 다루기 (2026-09-17 수정)

**초안에서는 "채택하지 않음"으로 적었으나 그 판단이 좁았다.** 근거로 든
CLAUDE.md §2-10은 "**현재 배포에서** MQTT·Kafka를 쓴다"는 배포 선택의 서술이지
다른 기술을 금지하는 조항이 아니다. 오히려 절대 준수 원칙 #7은 "새 센서·하드웨어·
런타임·외부 서비스는 핵심 코드 수정이 아니라 adapter/provider/capability 등록으로
확장할 수 있어야 한다"고 요구한다 — 그렇다면 이 셋도 **provider 뒤에 두면 되는
후보**이지 배제 대상이 아니다. 셋의 성격이 서로 달라 따로 적는다.

### ROS 2 — 가장 자연스럽다 (기존 계약이 이미 이 모양)

`contracts/physical_command.py`의 lifecycle(ACCEPTED/EXECUTING/CANCELING/
SUCCEEDED/ABORTED/CANCELED + 거부는 별도 필드)은 **ROS 2 Action 의미론을 설계
근거로 삼아 만든 것**이다(그 파일 docstring에 명시). 즉 우리는 이미 ROS 2의 모양에
맞춰 계약을 그려놓고 그 구현체만 안 만든 상태다. 붙일 자리:

| ROS 2의 것 | 우리 쪽 Protocol |
|---|---|
| topic pub/sub | `providers/adapters.py::TransportProvider` |
| action(goal lifecycle) | `HardwareCommandProvider` + `contracts/physical_command.py` |
| service(요청/응답) | `ControlProvider` |

**조건**: `rclpy`/DDS는 무거우므로 **선택 의존성**이어야 하고, 모듈 최상단이 아니라
생성자 안에서 지연 import한다(AI-C-11, `perception/open_vocabulary.py` 패턴). 말단이
ROS 2 설치를 강제당하면 안 된다(AI-B-10).

### Gazebo — 새 capability kind가 필요하다 (지금은 소비자가 없다)

우리 `simulator/`(pyjevsim DEVS)와 **경쟁 관계가 아니라 층이 다르다**:
- DEVS 시뮬레이터: "GPU가 사라지면 어떤 capability가 어떤 순서로 축소되는가"
- Gazebo: "그 바람·유속에서 UAV가 정위치를 유지할 수 있는가"

후자는 지금 어떤 Protocol에도 안 맞으므로 새 capability kind(`simulation.physics`
등)와 Protocol이 필요하다. **다만 지금 이걸 쓸 소비자가 없다** — 문/단상 탐지와
회전각 산출에 물리 시뮬레이션이 필요하지 않다. 하천 도메인에서 이동체 배치 판단
(강풍 시 UAV 불가 등)이 실제 요구가 됐을 때 착수하는 것이 맞다.

### Unity — 이미 경계 반대편에 있다

khw_VZ 브랜치 조사에서 **가시화 파트가 이미 Unity를 쓰고 있음**을 확인했다
(`Unity_Map/`, `unity-twin/`). 렌더링·HITL 화면은 그쪽 역할이라고 방금 정리했으므로
(`hw-vz-integration-boundary.md` §2-3), Unity를 "우리 provider"로 끌어오면 그 경계를
우리가 먼저 침범하는 셈이 된다. 우리가 제공할 것은 Unity가 소비할 **데이터 계약**이고,
그건 이미 정의돼 있다.

예외는 HITL **입력**(운영자 조작이 돌아오는 방향)인데, 그것도 물리 명령 경로를
타야 하므로 백엔드를 거친다 — 우리가 Unity와 직접 말하는 구조가 아니다.

### 이 절의 의미

세 기술 모두 "어디에 꽂히는가"를 **핵심 코드 수정 없이** 답할 수 있다는 것 자체가
provider 추상화가 실제로 작동한다는 증거다. 만약 ROS 2를 붙이는 데 `contracts/`나
`selection/`을 고쳐야 했다면 그건 우리 추상화가 깨졌다는 뜻이었을 것이다.
- **Ekman 3계층 해류 모델·Airy 파동·AIS 궤적 추종**: 해양·선박 전용이라 하천/실내
  로봇 도메인에 그대로 옮길 근거가 없다. 다만 "환경 외란이 임무 가능성을 바꾼다"는
  구조만 아래 §2-4로 일반화한다.
- **논문의 YOLO 균열 탐지 파이프라인**: 정량 평가(mAP 등)가 논문에 없고 모델 출처도
  단축 URL로만 표기돼 있어 근거로 쓸 수 없다(`lotusim-energy.md` §6).

## 2. 실제로 비어 있는 자리 — 제안 4건

### 제안 1. 플랫폼·센서 태그 어휘 등록 (가장 작음, 새 필드 없음)

**빈 자리**: `PurposeRequirement`는 "이 목적에 어떤 *정보*가 필요한가"를 말하지만,
LOTUSim Table II의 나머지 두 축인 **"어떤 종류의 이동체가"**와 **"어떤 센서로"**를
표현할 자리가 없다. `CompatibilityProfile.required_hw_tags`가 자유 문자열이라 담을
수는 있는데, 어휘가 정해져 있지 않아 즉흥적으로 갈라질 위험이 있다(AI-C-01 위반).

**변경**: `contracts/data_dictionary.py`에 태그 어휘의 *의미*만 등록한다.
- `PLATFORM_KIND = "platform_kind"` — 이동체 종류(`platform.uav`/`platform.usv`/
  `platform.ground_robot`/`platform.fixed_camera`). enum이 아니라 자유 문자열(원칙 #1).
- `SENSOR_KIND = "sensor_kind"` — 센서 종류(`sensor.rgb`/`sensor.sonar`/`sensor.sar`/
  `sensor.lidar`/`sensor.thermal`).

**새 코드 없음** — 이 태그들은 기존 `required_hw_tags`/`preferred_hw_tags`에 그대로
들어가고, `discover_node_tags()`가 노드에서 보고하면 selector가 알아서 거른다.
영향 파일: `contracts/data_dictionary.py` 1개(+ 사전 테스트).

### 제안 2. purpose 갭 → 관측 요청 연결 — **착수 후 축소됨(코드 불필요)**

> **2026-09-17 실제 착수 결과**: 새 어댑터 함수를 만들려고 `decision/info_request.py`를
> 열어보니 **이미 연결 가능한 상태였다.** `plan_for_validation_gaps(missing_evidence,
> sources_by_evidence, ...)`가 `EvidenceGap.missing_required`(둘 다 `tuple[str, ...]`)를
> 그대로 받고, 모듈 docstring도 이 사용법을 이미 안내하고 있었다("A caller that has an
> `EvidenceGap` ... can turn its `missing_required` fields into `EvidenceNeed`s here").
> 새 코드를 넣었다면 중복이었다.
>
> 실제 빈 자리는 **"그 고리가 닫힌다는 것을 증명하는 테스트가 없다"**는 것뿐이었고,
> `tests/test_purpose_to_request_loop.py`로 그것만 채웠다(목적 요구 → 부족분 → 요청 →
> 자율 수준까지 4단계). 아래 원래 제안 내용은 기록으로 남긴다.

(원안)

**빈 자리**: `purpose_requirements.evaluate_gap()`은 `EvidenceGap`(무엇이 부족한가)을
내고, `decision/info_request.py`의 `DecisionSupportRequester.plan()`은
`EvidenceNeed`(이 근거를 어떤 capability 후보로 채울까)를 받는다. **두 모듈이 서로
연결돼 있지 않다** — 지금은 호출부가 손으로 이어야 한다.

LOTUSim에 대해 우리가 지적한 한계가 정확히 이 지점이다: 논문은 "이상 발견 → 다른
로봇 자동 출동"이라는 **폐루프를 실험으로 검증하지 않았고**(사전 정의된 waypoint
추종이 실험의 중심), 우리의 차별점을 거기 두기로 했다. 그렇다면 그 폐루프가 우리
코드에서는 실제로 이어져 있어야 한다.

**변경**: `decision/`에 갭→요청 변환 함수 하나.
```
gap_to_needs(gap: EvidenceGap, candidates_by_field: dict[str, tuple[str, ...]]) -> list[EvidenceNeed]
```
`candidates_by_field`는 "이 정보 종류는 이 capability_kind들로 채울 수 있다"는 배포
설정(데이터)이며 코드에 도메인 분기를 넣지 않는다. 영향 파일: `decision/info_request.py`
1개 + 테스트.

### 제안 3. 자율 수준(autonomy level)을 권고에 명시

**빈 자리**: LOTUSim은 모든 태스크에 Teleoperation / Shared / Autonomous 3모드를
1급 속성으로 붙인다. 우리는 `grep` 결과 **autonomy/teleop 개념이 코드에 전혀 없다**.
AI-C-19가 "AI는 물리 명령을 직접 발급하지 않는다"까지만 정하고, "이 조치는 사람
승인이 필요한가"를 표현할 자리는 없다 — 그래서 지금은 위험도와 무관하게 전부 같은
모양의 권고가 나간다.

**변경**: `decision/`에 자율 수준을 표현만 한다(게이트는 구현하지 않는다).
- `AutonomyLevel(str, Enum)`: `TELEOPERATED` / `SHARED` / `AUTONOMOUS`
- 권고(`RECOMMENDATION`)에 이 값을 동반해 내보낸다.
- `contracts/data_dictionary.py`에 `AUTONOMY_LEVEL` 등록.

**경계 유지**: 실제 승인 절차·버튼은 가시화/백엔드 몫이다(AI-C-19,
`hw-vz-integration-boundary.md` §2-3). 우리는 "이건 승인이 필요한 등급"이라는
판단 정보만 제공한다. 영향 파일: `decision/` 1개 + 데이터 사전 + 테스트.

### 제안 4. 이동 예산(endurance) — **지금 하지 않고 조건부로 미룸**

**빈 자리**: `ResourceCost`는 compute/memory/latency뿐이라, "이 이동체가 거기까지
갔다 돌아올 수 있는가"를 표현할 수 없다. LOTUSim은 배터리 SOC를 추진 노력에 결합해
임무 계획에 넣는다(고정 전력 가정 아님).

**왜 지금 안 하나**:
1. `ResourceCost`/`ResourceBudget`에 필드를 추가하면 고정 카메라·엣지 서버 등
   이동하지 않는 모든 배포에도 영향이 간다 — 별도 `MobilityBudget` 개념으로 분리하는
   편이 맞아 보이지만, 그 판단을 뒷받침할 실측이 아직 없다.
2. 무엇보다 **숫자를 지어낼 수 없다**. 이 프로젝트는 측정하지 않은 값을 프로파일에
   넣지 않는다(AI-B-01: "미측정 항목은 구분해야 한다").

**착수 조건**: pi6 등 실제 이동체에서 주행·추론 소비 전력을 한 번이라도 측정한 뒤.
그전까지는 이 문서에 자리만 남긴다.

## 3. 착수 결과 (2026-09-17 완료)

| 제안 | 결과 | 실제 변경 |
|---|---|---|
| 1. 플랫폼·센서 태그 어휘 | 완료 | `contracts/data_dictionary.py`에 `PLATFORM_KIND`/`SENSOR_KIND` 등록(값은 자유 문자열, enum 아님) |
| 2. purpose 갭 → 관측 요청 | **코드 불필요로 축소** | 이미 `plan_for_validation_gaps()`로 연결 가능 → `tests/test_purpose_to_request_loop.py` 4건만 추가 |
| 3. 자율 수준 표현 | 완료 | `decision/autonomy_level.py` 신규(`AutonomyLevel`, 교체 가능한 `AutonomyPolicy`, `grade()`) + 데이터 사전 `AUTONOMY_LEVEL` + 테스트 9건 |
| 4. 이동 예산 | **보류 유지** | 실측 근거 없음 — pi6 소비전력 측정 후 재검토 |

전체 스위트: **729 passed / 23 skipped / 0 failed**(착수 전 714 → +15). 기존 구조를
바꾼 곳은 없고, 새 provider·새 의존성·도메인 분기를 만들지 않았다.

세 건 모두 기존 구조를 바꾸지 않고 얹는 변경이며, 새 provider·새 의존성·도메인
분기를 만들지 않는다. 각 건마다 기존 테스트 패턴(실제 `CapabilityRegistry` + 합성
입력, 모델 모킹 없음)으로 테스트를 추가하고 전체 스위트 무회귀를 확인한다.

## 4. 이 계획이 하지 않는 것

- 하천 도메인 전용 capability(`perception.sar_detect` 등) 구현 — 그건 우리 담당이
  아니고, 등록만으로 얹히도록 자리는 이미 마련돼 있다(`river-domain-capability-extension.md`).
- 시뮬레이터에 환경 외란(바람·유속) 모델 추가 — 지금 DEVS 시뮬레이터는 capability
  축소/복구를 검증하는 도구이고, 물리 외란은 그 검증 목적과 층위가 다르다. 필요해지면
  별도 제안으로 다룬다.
