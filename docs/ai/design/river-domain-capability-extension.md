# 하천 도메인(SAR·UAV·수중센서) capability 확장 설계 — 구현 아님, 병합 대비 설계

상태: 설계 제안(코드 미구현). SAR/UAV/수중센서 자체는 이 파트(진나영 AI)의
구현 책임이 아니지만, 병합 시점에 핵심 코드를 고치지 않아도 되게 지금
확장점을 정의해 둔다.
근거: ChatGPT 대화 요약(하천 호안 이상관리 시스템 기획), LOTUSim-Energy
논문([[lotusim-energy]]) 분석, `docs/ai/design/hw-vz-integration-boundary.md`.

## 0. 이미 있는 것으로 충분하다

사용자가 요구한 "모든 시스템은 없어도 동작 가능하고 있으면 기능이 추가될 수
있도록"은 새 메커니즘이 아니라 **이미 구현된 AI-C-05(핵심·선택 기능 분리) +
AI-B-04(등록 기반 확장)**를 하천 도메인에 그대로 적용하는 문제다. 새 코드가
필요한 지점은 없고, 아래는 **어떤 이름으로 등록할지**에 대한 제안이다(AI-C-01:
이름은 미리 정하고 데이터 사전에 등록해야 즉흥적으로 갈라지지 않는다).

## 1. 하천 도메인 시나리오 → capability 매핑 제안

ChatGPT 대화가 정의한 흐름: 고정카메라가 호안 이상 후보를 1차 검출 →
좌표화 → 불확실성이 크면 UAV(SAR)를 보내 위험물 확인 → 고정카메라 사각지대는
지상로봇이 근접 관측. LOTUSim-Energy의 "Task → Agent Type → Autonomy →
Primary Sensors" 표(표 II)와 같은 방식으로, 장비 이름이 아니라 **필요
capability**로 표를 만든다:

| 하천 임무 | capability_kind(제안) | 필요 provider 종류(예시, 미구현) | required_hw_tags(예시) |
|---|---|---|---|
| 고정카메라 호안 표면 이상 1차 검출 | `perception.detect`(기존 이름 재사용) | 균열/박리/백태 세그멘테이션 모델 | `compute.gpu` 또는 `compute.cpu` |
| 이상 후보의 불확실성·근거충분도 평가 | `perception.evidence_sufficiency`(신규 제안, AI-S-03과 동일 개념) | — (판단 로직, 모델 아님) | 없음 |
| UAV SAR 위험물 탐지 | `perception.sar_detect`(신규 제안) | UAV 탑재 SAR 신호처리 provider | `sensor.sar`, `platform.uav` |
| 수중 세굴·기초부 조사 | `perception.scour_survey`(신규 제안) | MBES/SSS(사이드스캔소나) 신호처리 provider | `sensor.sonar`, `platform.usv` 또는 `platform.auv` |
| 지상로봇 사각지대 근접 관측 | `perception.detect`(기존 이름, `platform.ground_robot` 태그로 구분) | 근접 RGB/LiDAR | `platform.ground_robot` |
| 배터리/자원 기반 이동체 선정 | 새 capability 아님 — 기존 `ResourceBudget`/`ResourceCost`에 배터리 잔량을 `compute_units`가 아닌 **새 자원 축**으로 추가할지는 별도 결정 필요(§3) | — | — |

**주의**: `perception.sar_detect`/`perception.scour_survey`는 이 문서의 **제안**일
뿐 아직 `contracts/data_dictionary.py`에 등록되지 않았다 — 실제로 이 기능을
담당할 파트(하천 도메인 구현 담당)가 확정되면 그 시점에 등록한다(AI-C-01 규약:
즉흥적으로 이름을 확정하지 않는다). 지금 표는 "이런 이름을 쓰면 기존 구조에
그대로 얹힌다"는 것을 보이는 것이 목적이다.

## 2. LOTUSim-Energy에서 가져올 만한 것 / 안 가져올 것

- **가져올 만한 것**: "Task → 필요 capability → 가능 Agent Type" 순서로 임무를
  정의하는 방식(표 II와 동일 철학) — 이미 우리 Capability Registry가 이 순서를
  강제한다. ENU 로컬 좌표계 채택(AI-C-02와 일치, GLOBAL 승격은 백엔드 소관).
  배터리를 "일정 전력 소모 가정"이 아니라 실시간 추진 노력에 결합해 추정하는
  방식은, 나중에 이동형 에이전트의 `ResourceBudget`에 "남은 임무 가능 시간"
  같은 축을 추가할 때 참고할 모델이다(지금은 미구현, §3).
- **안 가져올 것**: LOTUSim-Energy는 Gazebo+ROS 2+Unity를 핵심 의존성으로
  쓴다. 우리는 이미 MQTT(말단↔엣지)/Kafka(엣지↔서버) 전송을 확정했고(CLAUDE.md
  §2-10), ROS 2 DDS를 새로 들이지 않는다 — "기능 분리(물리/에이전트상호작용/
  렌더링을 독립 프로세스로)"라는 **설계 패턴**만 참고하고 구체 기술은 가져오지
  않는다(절대 준수 원칙 #1).

## 3. 미정으로 남기는 것 (여기서 결정하지 않음)

- 배터리/체공시간을 `ResourceBudget`의 새 축으로 넣을지, 아니면 완전히 별도의
  "임무 지속가능성" 판단으로 분리할지는 실제 하천 도메인 구현 담당이 결정할
  문제다 — 지금 `ResourceCost`(compute_units, memory_mb, max_latency_ms)에
  임의로 필드를 추가하면 로봇/카메라 도메인에도 영향을 준다.
- SAR 신호처리·세굴 탐지 모델 자체는 이 파트가 만들지 않는다(사용자 지시:
  "우리의 구현 담당이 아니다"). provider 인터페이스(`PerceptionProvider` 등
  기존 Protocol)만 맞추면 등록될 수 있다는 것만 확인해 둔다.

## 4. Capability/Provider 상태 가시화 UI — 우리는 데이터만, 화면은 가시화 몫

사용자 요청("어떤 provider가 필요한지, 현재 보유 provider/capability와 상태를
K3s로 조율하고 UI로 가시화")은 `docs/ai/design/hw-vz-integration-boundary.md`
§2-3의 경계 원칙을 그대로 따른다 — **화면은 가시화 파트가 만들고, 우리는 이미
존재하는 데이터만 내보낸다.** 새로 만들 필요가 없는 이유:

- "현재 보유 provider/capability" = `CapabilityRegistry.known_capability_kinds()` +
  `available_providers(kind)` — 이미 있음.
- "상태" = `CapabilityState`(ACTIVE/DEGRADED/DISABLED) — 이미 있음, 이미
  `contracts/data_dictionary.py::CAPABILITY_STATE_BEFORE/AFTER/STATE_CHANGE_REASON`
  이름까지 등록돼 있음.
- "K3s로 조율" — `providers/k3s.py::K3sControlProvider` +
  `runtime/clusters.py::MultiClusterControlProvider` — 이미 있고 실제 K3s
  클러스터 대상 통합테스트도 있음(`tests/test_k3s_control.py`).

가시화가 이 정보를 폴링/구독할 수 있는 **읽기 전용 엔드포인트 하나**만
있으면 된다 — `ResourceAdaptiveReconfigurer`가 이미 `capability_state_changed`
이벤트를 관측 경로(AI-O-02)로 발행하므로, 그 이벤트 스트림을 가시화 쪽
`ObservabilityProvider` 구현체가 구독하게 하면 새 코드 없이 끝난다. **이번
정리에서 코드를 추가하지 않는다** — 이미 있는 조각들의 조합만으로 충족되는지
확인하는 것이 이 섹션의 목적이었고, 확인됐다.
