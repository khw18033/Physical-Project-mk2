# Capability 상태 UI · k3s 폐루프 — 외부 검토 의견 반영 계획

작성 2026-09-17. 대상: ChatGPT 세션 "UI 상태 설계 의견"
(https://chatgpt.com/share/6aab8e88-69bc-83e9-a6ab-a4f8e0896e1c)의 두 답변
(① 상태 가시화 UI 설계 의견, ② k3s/Docker 기반 선택 폐루프와 툴 스택 제안).
각 제안을 `perception-framework/` **현재 코드에 대조**해 "이미 있음 / 우리 경계
밖 / 채택 / 보류 / 반대"로 나눴다. 판정 근거는 전부 파일 경로로 남긴다.

## 0. 한 줄 결론

제안의 골격(Purpose → Requirements → Capability → Provider → Runtime instance,
가용성과 lifecycle 분리, 하드 필터 → 소프트 순위, 의미 판단은 프레임워크·배치는
k3s)은 **이미 우리 코드가 그 모양**이다. 실제로 비어 있는 것은 넷뿐이다 —
(1) 선택에서 **탈락한 후보와 그 사유**를 결과에 싣지 않는다,
(2) 사유 문자열 어휘가 코드 곳곳에 흩어져 있고 데이터 사전에 통제 어휘로
등록돼 있지 않다, (3) 설정 파일 → `ProviderRegistration` 로더가 없다,
(4) `resolve()` 결과를 `ControlProvider`로 실제 배치하는 마디(태그→nodeSelector)가
없다. 이 넷은 전부 **계약 변경 없는 추가**다. 반대로 CRD 저장, 6단계 상태 enum,
장치 heartbeat를 AI가 READY 합성에 넣는 것, 메인 UI를 우리가 React로 만드는 것은
**받지 않는다**(§3).

## 1. 대화 요약

**사용자 질문 ①**: 기능이 요구되면 필요한 provider의 가용 여부를 색으로, 평소엔
가능/불가 기능 목록 → 클릭하면 상세(기기·모델) 또는 불가 사유+보충할 provider.
**답변 ①** 요지:
- 가능/불가 2분법 대신 READY / DEGRADED / BLOCKED / MISSING / STALE(+뒤에 AVAILABLE_COLD).
- 두 모드: 평상시 Capability Catalog / 요청 시 Requirement Resolution
  (Purpose → Capability req → Evidence req → 후보 provider → 실행 가능성).
- provider 상세엔 입출력 계약·자원·성능·health·**목적별 사용 가능 여부**를 분리 표시.
- 불가 화면은 원인 체인 + "최소 보충 집합".
- 실패 사유를 자유 문자열이 아닌 enum으로.
- confidence와 evidence sufficiency를 따로 보여주는 Evidence UI, purpose별 요구 표시.
- Dependency graph는 Capability → Provider 2단으로. 선택 이유와 대안 표시. What-if.
- availability와 FSM(명령/객체/모델 lifecycle)을 한 status로 합치지 말 것. 계약
  위반 배지. AI-C-19 책임 경계 표시.

**사용자 질문 ②**: 이 선택 폐루프와 가시화를 k3s·Docker로 구성하는 방법, 다른 UI·툴.
**답변 ②** 요지:
- k3s를 capability 판단 엔진으로 쓰지 말 것. "무엇을 돌릴지"는 프레임워크,
  "어디서 돌릴지"는 k3s.
- Docker = 이미지 빌드, containerd+k3s = 실행. 1 provider = 1 OCI 단위 + manifest.
- FunctionRequest / ProviderBinding / SelectionPlan 정도만 CRD로. 관측·센서
  데이터는 CRD에 넣지 말 것.
- Pod Ready ≠ provider READY. Infra Ready AND App Ready AND Physical Ready.
- provider 세 종류(Physical/Compute/Software). 물리 장비를 k3s node로 넣지 말 것.
- `orchestration/controller.py` — observe→resolve→filter→rank→bind→deploy→validate→re-select.
- 선택기는 하드 제약 → 소프트 점수 2단계. 대체 provider 있음 ≠ 자동 교체 가능.
- Always-on / On-demand 분리, KEDA(비안전 워커만), Argo CD(기준 상태), React+React
  Flow(메인 UI 직접 제작), Headlamp(k8s 운영), Grafana State Timeline(이력),
  Backstage(지금은 과함), FastAPI/PostgreSQL/Redis.

## 2. 제안별 대조표

판정: **있음** = 이미 코드에 있음 · **경계** = 우리 파트 몫이 아님(데이터만 제공) ·
**채택** = 이번에 반영 · **보류** = 전제가 생기면 · **반대** = 원칙 충돌.

### 2-1. 답변 ① (UI)

| # | 제안 | 판정 | 근거 |
|---|---|---|---|
| 1 | 5~6단계 상태 enum | **반대(부분 채택)** | `contracts/capability.py::CapabilityState`는 ACTIVE/DEGRADED/DISABLED 3단이고 이 3단이 AI-C-05 장애 격리의 근거다. BLOCKED/MISSING/STALE/COLD는 **상태가 아니라 DISABLED의 사유**다 — 사유는 `runtime/application.py::CapabilityResolution.reason`에 이미 실린다. 표시 등급은 `(state, reason)`에서 가시화가 파생한다. 대신 사유 어휘를 통제한다(§4 P2) |
| 2 | 평상시 Catalog / 요청 시 Resolution 두 모드 | **있음** | Catalog = `ZoneApplication.resolve()` 결과. Resolution = `perception/purpose_requirements.py` → `EvidenceGap` → `decision/info_request.py::plan_for_validation_gaps()` — 이 고리가 닫힌다는 것은 `tests/test_purpose_to_request_loop.py`가 증명 |
| 3 | provider 상세: 입출력 계약·자원·성능·health·미측정 구분 | **있음** | `contracts/capability_contract.py::ExecutionProfile`(latency_ms/quality/resources/**unmeasured_fields**), `RuntimeInstance`(healthy/health_ttl/current_load), `ProviderRegistration.supported_inputs/outputs` |
| 3' | "목적별 사용 가능 여부"를 provider 상태와 분리 | **있음** | `PurposeRequirementRegistry.evaluate_all()`이 목적별 갭을 따로 낸다. provider 자체 상태와 섞이지 않는다 |
| 4 | 불가 원인 체인 + 최소 보충 집합 | **있음(체인) / 채택(최소집합 = 데이터로 이미 가능)** | `CapabilityRequirement.evaluate()`가 `missing_required:<kinds>`를 돌려준다 — 이것이 곧 최소 보충 집합이다(required 중 빠진 kind만). 체인의 다음 단(그 kind에 provider가 왜 없는지)은 `SelectionResult.reason`. 별도 코드 불필요 |
| 5 | 실패 사유 enum 표준화 | **채택(어휘 등록, enum은 아님)** | 지금 사유는 `no_provider_registered`, `no_compatible_provider_within_budget`, `deadline_exceeded`, `input_too_stale`, `execution_profile_conditions_mismatch`, `runtime_instance_unhealthy_or_expired`, `missing_required:*`, `core_capability_unplaced`, egress 게이트 사유 — **사실상 어휘가 있으나** `data_dictionary.py::STATE_CHANGE_REASON`의 value_kind가 `"str"`이라 통제되지 않는다. §4 P2 |
| 6 | Evidence UI: confidence ≠ sufficiency | **있음** | `perception/object_record.py::ObjectRecord.confidence/supporting_groups/available_groups`. 가시화가 그리면 된다 |
| 7 | purpose별 요구(confidence≥, freshness<, 독립 출처 n) 표시 | **부분 있음** | `PurposeRequirement`는 required/preferred **필드 이름**만 갖는다. 임계값·신선도는 `TaskIntent.minimum_evidence/max_input_age`에 따로 있다. 둘을 한 화면에 모으는 건 가시화 몫. 우리 쪽 코드 추가 없음 |
| 8 | Dependency graph를 Capability → Provider 2단으로 | **경계** | 그래프는 가시화 몫. 우리는 이미 `capability_kind`/`provider_id`를 데이터 사전 이름으로 낸다 |
| 9 | 선택 이유 + 대안(탈락 사유) 표시 | **채택 — 진짜 격차** | `selection/selector.py::_ranked_candidates()`가 placement 거부 사유 `rejections`를 계산해 놓고 **버린다**(L67-73). `SelectionResult`는 승자 하나와 사유 하나만 싣는다. §4 P1 |
| 10 | What-if | **있음(시뮬레이터)** | `simulator/scenarios/*.json` + `tests/test_scenarios.py`가 정확히 "GPU가 사라지면 무엇이 어떤 순서로 죽는가"를 재현한다. UI에서 실시간으로 하려면 `ZoneApplication.set_node_tags()` + `resolve()`를 다른 태그로 다시 부르면 된다 — 순수 함수라 부작용 없음. 코드 추가 없음 |
| 11 | availability와 lifecycle FSM 분리 | **있음** | 객체 `PROVISIONAL→CONFIRMED→STALE→EXPIRED`, 명령 `ACCEPTED/EXECUTING/…`(+`Rejection` 별도), 학습 lineage 10단 — 전부 `CapabilityState`와 무관하게 돈다 |
| 12 | 계약 위반 배지(출력 IMAGE vs 소비자 CAMERA_LOCAL) | **부분 있음 / 격차 기록** | `common/coordinates.py::SpatialValue.is_comparable_with()`, `common/data_plane.py::DataPlaneViolation`이 **런타임에** 막는다. 그러나 **선택 시점**에 `supported_inputs/outputs`를 소비자 요구와 대조하지는 않는다 — `contract_mismatch` 사유가 나올 자리가 없다. §4 P5(보류) |
| 13 | AI-C-19 책임 경계 표시 | **있음** | `observability/availability.py::RemoteFeatureGate`(백엔드 판정 소비만), `to_global()`은 있으나 authoritative 아님 |

### 2-2. 답변 ② (k3s/Docker/툴)

| # | 제안 | 판정 | 근거 |
|---|---|---|---|
| 1 | k3s는 배치·복구만, 판단은 프레임워크 | **있음(동일 결론)** | `providers/k3s.py` 모듈 docstring 첫 줄이 이 원칙이다. `K3sControlProvider`와 `LocalControlSupervisor`가 같은 `ControlProvider` 계약 |
| 2 | Docker=빌드, containerd+k3s=실행 | **있음(확정 사항)** | `external-technology-decisions.md` §5: Docker는 "현재 image build 도구", K3s는 provider |
| 3 | 1 provider = 1 OCI + manifest | **채택(로더만)** | `ProviderRegistration`(5계층)이 곧 manifest의 파이썬 형태다. 없는 건 **설정 파일 → `ProviderRegistration` 로더**뿐 — `edge/model_config.py`가 provider *객체*는 만들지만 *등록*은 파이썬 상수로 한다. §4 P3 |
| 4 | FunctionRequest/ProviderBinding/SelectionPlan CRD | **보류** | AI-B-11: 모든 실행영역이 K3s를 갖는다고 전제하지 않는다 → desired state를 CRD에 두면 K3s 없는 구역은 desired state를 잃는다. 이미 `DeploymentProfile`+`CapabilitySpec`(파이썬/설정)이 desired state다. AI-B-10: 파이썬 k8s client를 넣지 않는다(`kubectl` shell-out만). ChatGPT 자신도 "Operator부터 만들지 말라"고 했다 — 그 조언만 받는다 |
| 5 | Pod Ready ≠ provider READY, 3단 합성 | **있음 / 일부 반대** | Infra = `K3sControlProvider.get_status()`, App = `ProviderRegistration.health_check`/`RuntimeInstance.is_selectable()`, Physical = **백엔드 판정을 소비**(`RemoteFeatureGate`). ChatGPT의 "device heartbeat → READY"를 **AI가 계산하면 원칙 #15 위반** — 우리는 백엔드 통합 판정을 입력으로 받는다(§3-1) |
| 6 | 후보 선택은 프레임워크, 노드 배치는 k3s(nodeSelector) | **채택 — 두 번째 진짜 격차** | `K3sControlProvider._start()`는 `params["node_selector"]`를 받아 Pod spec에 박는다(실측 테스트 있음). 없는 건 `CompatibilityProfile` 태그 → 라벨 변환과, `resolve()` 결과를 `request("start")`로 잇는 마디. §4 P4. 계획 파일(jazzy-sprouting-engelbart)에서 이미 "유일한 빈 자리"로 확인된 것과 같은 항목 |
| 7 | Physical / Compute / Software provider 3종 | **있음(태그로)** | 벤더 enum 대신 자유 문자열 태그(`compute.gpu`, `platform.uav`, `sensor.sonar` — 2026-09-17 `PLATFORM_KIND`/`SENSOR_KIND` 등록). 종류를 enum으로 박지 않는 게 원칙 #1. 아이콘 구분은 가시화가 태그 접두어로 한다 |
| 8 | 물리 장비를 k3s node로 넣지 않는다 | **있음** | 원칙 #12, AI-B-10. `hw-vz-integration-boundary.md` §2-1: HW 장치는 adapter 뒤의 provider |
| 9 | Selection Controller(observe→…→re-select) | **부분 있음** | `runtime/reconfiguration.py::ResourceAdaptiveReconfigurer`가 observe→re-resolve→event 기록까지. **bind→deploy→validate** 마디가 없다 = §4 P4와 동일 격차 |
| 10 | 하드 제약 → 소프트 순위 2단 | **있음** | `_ranked_candidates()`: placement 필터 → 호환/예산 필터 → `(priority, preference_penalty, compute_units)` 정렬. 소프트 단에 latency/accuracy/energy 가중합을 **일부러 넣지 않았다**(AI-C-13: 점수식 고정 금지). 실측값은 `ExecutionProfile`에 있으므로 필요하면 ranking policy를 교체 가능하게 꽂는다 — 지금은 요구 없음 |
| 11 | 대체 provider 있음 ≠ 자동 교체 가능 | **있음** | `select_with_degrade()`는 kind 우선순위 사슬을 타고, 각 단에서 다시 호환·예산을 통과해야 한다 |
| 12 | Always-on / On-demand, AVAILABLE_COLD | **보류** | On-demand = AI-E-04 선택형 보조 기능(있음). "등록은 됐지만 Pod가 안 떠 있음"을 구분할 자리가 없다 — `RuntimeInstance` 없음(=검사 생략)과 `healthy=False`(=제외)뿐. K3s scale 0→1은 `_start()`가 이미 한다. **실제 on-demand 배치를 운용하기 전엔** 상태를 만들지 않는다(근거 없는 상태 추가 금지) |
| 13 | KEDA | **보류** | 비안전 워커 한정이라는 조건은 맞다. 다만 `ZoneApplication.resolve()`의 예산 차감이 replica 수를 모른다 — KEDA를 붙이려면 예산 모델부터 바꿔야 해서 지금 이득 없음 |
| 14 | Argo CD(기준 상태) vs Selection Controller(현재 요청) 분리 | **동의, 코드 없음** | 기준 상태 = 이미지·버전 관리 = `ModelDeploymentProvider`/`K3sControlProvider.update_image()/rollback()`. Argo CD는 그 뒤에 올 수 있는 provider 후보일 뿐이고 폐쇄망(AI-C-16)에선 Git 접근 전제가 걸린다. 결정 문서에 "후보"로만 기재 |
| 15 | React + React Flow + FastAPI 메인 UI 직접 제작 | **경계** | 가시화 파트(khw_VZ, TS `viz-debugger`) 몫. 우리는 화면이 소비할 **설명 payload**(§4 P1·P2)를 낸다. 우리 draft 패널(artifact)은 검토용이지 운영 UI가 아니다 |
| 16 | Headlamp | **동의, 코드 없음** | k8s 내부 운영 화면. 우리 코드와 접점 없음. 링크 하나 |
| 17 | Grafana State Timeline | **있음(데이터)** | `ResourceAdaptiveReconfigurer._report()`가 `capability_state_changed` 이벤트(before/after/reason)를 이미 낸다(AI-O-02). Grafana는 백엔드 관측 경로 소유 |
| 18 | Backstage | **반대(지금)** | ChatGPT와 같은 결론 |
| 19 | PostgreSQL/Redis(selection history, cache) | **경계** | 저장소는 AI가 소유하지 않는다. selection history는 `capability_state_changed` 이벤트 + `AuditEntry`로 이미 관측 경로에 나간다 |

## 3. 받지 않는 것과 그 이유

### 3-1. "device heartbeat → provider READY"를 AI가 합성

원칙 #15 / AI-O-04: 장치 최종 가용성은 백엔드가 업무 전송 상태 + 관측 상태를
통합해 판정하고, AI는 그 결과를 **소비**한다. ChatGPT의 3단 합성(Infra AND App AND
Physical)에서 셋째 단을 우리가 heartbeat로 계산하면 백엔드와 판정이 둘이 된다.
그래서 셋째 단은 `RemoteFeatureGate.may_select_remote_capability(backend_verdict)`
그대로 둔다 — 입력이 백엔드 판정이라는 점만 다르고 결과 모양은 ChatGPT 제안과 같다.

### 3-2. 6단계 상태 enum

3단(ACTIVE/DEGRADED/DISABLED)은 "optional 결손은 DEGRADED까지만"이라는 격리
규칙의 표현이다. BLOCKED/MISSING/STALE은 전부 DISABLED이고 **왜** DISABLED인지가
다를 뿐이다. 상태를 늘리면 `CapabilityRequirement.evaluate()`·`StateTransition.is_degradation`·
시뮬레이터 시나리오 검증이 전부 6단 순서를 알아야 한다. 대신 사유 어휘를 통제하면
가시화가 `DISABLED + missing_required:*` → "MISSING", `DISABLED + no_compatible_provider_within_budget`
→ "BLOCKED", `DISABLED + runtime_instance_unhealthy_or_expired` → "STALE"로 파생할 수 있다.

### 3-3. CRD

§2-2 #4. 한 줄로: desired state를 K3s에 두는 순간 K3s가 core dependency가 된다.

### 3-4. 메인 UI 직접 제작

`hw-vz-integration-boundary.md` §2-3에서 정한 경계. 우리가 React 앱을 만들면
가시화 파트와 판단 로직·화면이 둘로 갈라진다(AI-C-19: 가시화는 AI 판단 로직을
중복 구현하지 않는다 — 반대 방향도 같다).

## 4. 채택 계획 (코드) — 우선순위순

전부 기존 계약을 넓히지 않는 추가다. 각 항목은 단독으로 머지 가능.

| P | 항목 | 위치 | 내용 | 검증 |
|---|---|---|---|---|
| **P1** | 탈락 후보와 사유를 결과에 싣기 | `selection/selector.py` | `SelectionResult`에 `alternatives: tuple[tuple[provider_id, reason], ...] = ()` 추가. `_ranked_candidates()`가 이미 계산하는 placement `rejections`와 호환/예산 탈락, `select_for_intent()`의 profile/instance 탈락을 모아 넣는다. 승자 외 순위 통과자도 `"compatible"`로 기록. 기본값 `()`라 기존 호출부 무변경 | 새 테스트 4건: 거부 사유가 후보별로 보존되는지, 순위 통과자가 `compatible`로 남는지, 승자는 alternatives에 없는지, 빈 후보일 때 `()` |
| **P2** | 사유 어휘를 데이터 사전에 통제 어휘로 등록 | `contracts/data_dictionary.py` | `STATE_CHANGE_REASON`·`REJECTION_REASON`의 value_kind를 실제 코드가 내는 어휘 목록으로 교체(`no_provider_registered\|no_compatible_provider_within_budget\|…\|missing_required:<kinds>\|selected\|compatible`). 코드 상수는 그대로 문자열 — enum으로 감싸지 않는다(백엔드 검증 철학: enum으로 값 어휘를 강제하지 않음) | `tests/test_data_dictionary.py`에 "selector가 반환하는 모든 사유가 등록 어휘에 있다" 1건 — 어휘가 흩어지는 걸 이후로 막는다 |
| **P3** | 설정 파일 → `ProviderRegistration` 로더 | `registry/manifest.py`(신규) | JSON/YAML의 `capability_kind/provider_id/version/compatibility{required_hw_tags,preferred_hw_tags,cost,priority}/requirement{required,optional}/supported_inputs/outputs/execution_profile?` → `ProviderRegistration`. `edge/model_config.py`와 같은 상대경로 규칙. `config/providers.example.json`에 s11 시나리오 6종을 옮겨 적는다 | 로더 테스트 3건 + "s11 시나리오를 로더로 읽어 등록해도 `test_scenarios`가 같은 결과" 1건 |
| **P4** | 태그→nodeSelector + resolve→배치 마디 | `runtime/placement.py`(신규) | `node_selector_for(profile: CompatibilityProfile) -> dict[str,str]` — `required_hw_tags`만 라벨로(`aif.io/hw-tier: compute.gpu` 관례, `external-technology-decisions.md` §11.5), preferred는 라벨로 만들지 않는다(선호는 순위이지 제약이 아님, AI-B-04). `PlacementReconciler.apply(resolutions, control: ControlProvider)` — provider가 바뀐 kind만 `stop`/`start(params={image, node_selector})`. `ControlResult.accepted=False`면 그 kind만 `DISABLED`로 재보고, 다른 kind는 손대지 않는다(AI-C-05) | fake `ControlProvider`로 6건: 변화 없는 kind는 호출 없음, 배치 거부가 다른 kind에 전파 안 됨, preferred 태그가 라벨에 안 들어감, `LocalControlSupervisor`와 `K3sControlProvider` 어느 쪽을 꽂아도 같은 호출 순서 |
| P5 | 선택 시점 계약 대조(`contract_mismatch`) | `selection/selector.py` | 소비자가 `TaskIntent`에 요구 입력 종류를 선언하면 `supported_inputs`와 대조. **보류** — `TaskIntent`에 그 필드가 없고, 지금 소비자 중 이걸 요구하는 곳이 없다. 요구가 생기면 P1 위에 얹는다 | — |
| P6 | draft 패널 갱신 | artifact `XZwgze1ETrC3obim9QT2MU` | P1 결과(대안·탈락 사유)를 행마다 접이식으로. **P1 머지 후**, 사용자 확인용 | 육안 |

기대 규모: P1~P4 합쳐 신규 2모듈 + 기존 2파일 수정, 테스트 +14 안팎. 전부
`CapabilityState`·`ProviderRegistration`·`ControlProvider` 시그니처 무변경.

### 4-1. 착수 결과 (2026-09-17, 승인 후 같은 날)

| P | 커밋 | 실제 결과 | 계획과 다른 점 |
|---|---|---|---|
| P1 | `21d44e9`, `b6f0b38` | `CandidateOutcome(provider_id, reason)` 데이터클래스 + `SelectionResult.alternatives`. `select_for_intent()`의 profile/instance 탈락, `select_with_degrade()`의 하위 kind 후보까지 보존. `CapabilityResolution.alternatives`로 `ZoneApplication.resolve()`까지 관통(P1b) | 후보별 사유를 tuple이 아닌 데이터클래스로. 호환 실패를 `required_hw_tag_missing:<tags>` / `required_runtime_tag_missing:<tags>` / `over_budget`으로 세분 |
| P2 | `db06925` | `data_dictionary.STATE_CHANGE_REASONS`(17 토큰) + `state_change_reason_token()`. selector 상수 전부·resolver 사유·egress 게이트 사유가 어휘 안에 있음을 테스트가 강제 | `REJECTION_REASON`은 손대지 않음 — 그건 물리 명령 거부(말단 생산)의 별도 어휘라 이 사전 항목과 섞으면 안 됨 |
| P3 | `3e371ae` | `registry/manifest.py` + `config/providers.example.json`(6종). manifest로 만든 레지스트리가 s11 시나리오 레지스트리와 kind별 같은 provider를 고르는 것을 테스트가 증명 | s11은 실제로 4종만 등록 — 나머지 2종(yolo-world/fastsam)은 `model_config.example.json`에서 옮김. YAML 미지원(의존성 추가 금지) |
| P4 | `36477cb` | `runtime/placement.py`: `node_selector_for()` + `PlacementReconciler`. `LocalControlSupervisor`와 fake가 같은 호출 순서를 내는 것을 테스트가 증명 | 라벨 관례를 `aif.io/<tag>=true`(태그당 1라벨)로 확정 — `aif.io/hw-tier` 단일 키는 required 태그가 2개 이상일 때 표현 불가. `required_runtime_tags`는 라벨화하지 않음(노드 속성이 아니라 이미지 내부 속성) |
| UI | (아래) | `tools/status_ui/` — stdlib HTTP + 단일 HTML, 검토용. 실행법은 `docs/ai/guides/status-ui-runbook.md` | 아티팩트(P6) 갱신 대신 **로컬 실행 도구**로 — 사용자가 직접 what-if·배치를 눌러볼 수 있어야 하므로 |

테스트: 729 → 781 (P1~P4, +52) → UI 포함 수치는 runbook 참조. 전 구간 무회귀.

### 4-2. UI 축 교정 (2026-09-17, 사용자 검토 반영)

첫 버전은 **기기(노드) 중심**이었고 기각됐다 — 기기는 capability의 provider 중 하나일
뿐이며 사용자가 묻는 건 "지금 어떤 기능이 되는가 · 그 기능엔 어떤 자원이 필요한가 ·
그 기기의 **역할**(로봇 온디바이스 / 엣지 / 서버)이 무엇인가"다. 교정:

- 첫 화면 단위 = **기능** = `TaskIntent(required/optional capability kinds)`를 설정
  (`functions[]`)으로. 상태는 `evaluate_availability()` — 새 코드가 아니라 기존 계약.
- 평가는 fleet 단위: 노드마다 `resolve()` → "kind를 어느 역할의 어느 provider가
  서비스하는가" → 기능별 필요 자원(역할별 비용 합, 요구 태그)과 **최소 보충 조건**
  (부족한 kind마다 역할별 탈락 사유).
- 역할은 노드 설정의 `role` + `tier.<role>` 태그(자유 문자열). 기능 화면에는 기기명이
  없고, 역할·기기명은 "계층·자원" 보조 화면과 개발자 화면에만.
- 모든 문구는 `config/status_ui.labels.json`(ko/en)에서 오고 화면 버튼으로 즉시 전환.
  응답 JSON은 id만 실어 언어 중립.
- **범위 밖(사용자 소유)**: 신원·권한·인증과 관점별 응답 필터링 구조는 사용자가
  직접 설계한다. 이 도구는 그 설계가 얹힐 수 있도록 응답을 additive·언어 중립으로만
  유지한다.

## 5. 툴 스택 판정 요약

| 툴 | 우리 결론 | 우리 코드 접점 |
|---|---|---|
| k3s / containerd / Docker(빌드) | 이미 확정 | `providers/k3s.py` |
| React + React Flow / FastAPI | 가시화 파트 | 없음 — payload만 |
| Headlamp | 써도 됨 | 없음 |
| Prometheus / Grafana(State Timeline) | 백엔드 관측 경로 | `capability_state_changed` 이벤트(있음) |
| Argo CD | provider 후보로 기재만 | `ModelDeploymentProvider` 뒤 |
| KEDA | 보류 | 예산 모델 재설계 필요 |
| CRD / Operator | 보류 | — |
| Backstage / PostgreSQL / Redis | 안 함 / 백엔드 | — |

## 6. 착수 순서

P1 → P2 → P3 → P4 순. P1·P2는 반나절, P3·P4는 각각 하루 이내. P4는 실제 K3s
없이 fake로 검증하고, 실측은 기존 `tests/test_k3s_control.py`의 클러스터 환경에서
한 번 더 돌린다. 완료 후 `docs/ai/requirement-traceability.md`의 AI-B-04/AI-C-13/
AI-O-02 행과 이 문서 §4를 결과로 갱신한다.
