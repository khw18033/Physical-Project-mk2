# AI 프레임워크 구조 (진나영 담당분)

CLAUDE.md §4 구조도를 그대로 따른다.

```text
Domain / Application Logic
        │
        ├─ Perception / Decision / Risk / Safety      <- mission_runtime/reference/*, 향후 perception/decision/risk 모듈
        │
Common Capability & Provider Interfaces
        │
        ├─ Input / Media Adapter                       <- mission_runtime/providers/adapters.py: MediaSourceProvider
        ├─ AI Runtime Provider                          <- mission_runtime/providers/adapters.py: AIRuntimeProvider
        ├─ Transport Provider                           <- mission_runtime/providers/adapters.py: TransportProvider
        ├─ Serializer Provider                          <- mission_runtime/providers/adapters.py: SerializerProvider
        ├─ Control / Orchestrator Provider              <- mission_runtime/providers/adapters.py: ControlProvider
        ├─ Observability Provider                       <- mission_runtime/providers/adapters.py: ObservabilityProvider
        ├─ Network Overlay Provider                     <- mission_runtime/providers/adapters.py: NetworkOverlayProvider
        └─ Model Deployment Provider                    <- mission_runtime/providers/adapters.py: ModelDeploymentProvider
        │
Capability Registry + Resource Profile + Deployment Profile
        │                                               <- mission_runtime/registry/capability_registry.py
        │                                               <- mission_runtime/contracts/profile.py
        │                                               <- mission_runtime/selection/selector.py
Concrete Hardware / Sensor / Runtime / Protocol / Infrastructure
                                                          (현재 배포: MQTT/Kafka/OTel/K3s/Tailscale/RTSP 등 -
                                                           위 provider 뒤에 숨음)
        │
Cross-part Wire Contract                                <- schemas/ai/*.schema.json
                                                          mission_runtime/integration/wire.py
```

## 핵심 개념과 요구사항 매핑

| 개념 | 위치 | 관련 요구사항 |
|---|---|---|
| `CapabilityState` (ACTIVE/DEGRADED/DISABLED) | `contracts/capability.py` | AI-C-05 |
| `CapabilityRequirement` (required/optional 선언 + 평가) | `contracts/capability.py` | AI-C-05 |
| `CompatibilityProfile`, `ResourceCost`, `ResourceBudget` | `contracts/profile.py` | AI-B-01, AI-B-04, AI-C-13 |
| `DeploymentProfile` (도메인 = 데이터) | `contracts/profile.py` | AI-C-15 |
| `FieldSpec` / `DATA_DICTIONARY` | `contracts/data_dictionary.py` | AI-C-01, AI-C-06 |
| 8종 provider Protocol (전송·직렬화·미디어·AI 런타임·제어·관측·오버레이·모델 배포) | `providers/adapters.py` | AI-C-04, AI-C-06~08, AI-B-03, AI-B-08 |
| `CapabilityRegistry` (local + remote snapshot) | `registry/capability_registry.py` | AI-C-10, AI-B-05 |
| `CapabilitySelector` (호환성 필터 + 최소자원 + 단계적 축소) | `selection/selector.py` | AI-B-01, AI-B-04, AI-B-06, AI-C-13 |
| `LocalSafetyJudge` (수직 슬라이스 예시, 배포별 `expected_optional_kinds`로 범위 축소 가능) | `reference/local_safety.py` | AI-N-01 |
| `FixedCameraPerceptionStream` (고정 카메라: 안전 판단 없음, 상시 편도 publish) | `reference/fixed_camera_stream.py` | AI-E-01 |
| `PathCandidateRiskEvaluator` (경로 후보 위험 평가, 선택은 하지 않음) | `risk/path_evaluation.py` | AI-R-02, AI-C-19 |
| `AssetResolver` / `AirgapPolicy` | `runtime/airgap.py` | AI-C-16, AI-B-09 |
| `MultiClusterControlProvider` | `runtime/clusters.py` | AI-B-11, AI-B-03, AI-B-05 |
| `TailscaleOverlayProvider` / `OverlayAwareRemoteGate` | `providers/overlay.py` | AI-C-04, AI-O-04 |
| `ModelDeploymentManager` / `ModelDeploymentProvider` | `runtime/model_deployment.py`, `providers/adapters.py` | AI-B-05, AI-B-08 |
| 공통 JSON Schema / wire adapter | `schemas/ai`, `integration/wire.py` | AI-C-01, AI-C-03, AI-C-06, AI-C-07, 파트 간 연동 |

## 설계 원칙이 코드에 반영된 방식

1. **하드코딩 금지 (절대 준수 원칙 #1, #2, #7)**: `providers/adapters.py`의 모든 인터페이스는
   `Protocol`이며 구체 기술(MQTT, Kafka, RTSP, gRPC 등)을 import하지 않는다. 새 provider는
   해당 Protocol을 만족하는 클래스를 만들고 `CapabilityRegistry.register_local`로 등록하는
   것만으로 연결된다 — 핵심 코드 수정이 필요 없다 (AI-B-09).

2. **도메인 분기 금지 (절대 준수 원칙 #3)**: `DeploymentProfile`은 `domain_id`를 데이터 필드로만
   가지고 있고, 프레임워크 어떤 코드도 `if domain_id == "robot"` 같은 분기를 갖지 않는다.
   도메인 차이는 `active_capability_kinds`, `rule_set_id`, `node_tags` 조합으로 표현한다.

3. **필수/선택 분리 (절대 준수 원칙 #4)**: `CapabilityRequirement.evaluate()`는 optional 누락은
   `DEGRADED`, required 누락만 `DISABLED`로 구분한다. `LocalSafetyJudge`가 이 패턴을 실제로
   보여준다 — 인지·추적·거리추정 중 무엇이 빠져도 크래시하지 않고 판단 수준만 낮아지며,
   영상(required)이 없을 때만 `SAFE_STOP`으로 떨어진다.

4. **최소 자원 사용 (절대 준수 원칙 #5, AI-C-13)**: `CapabilitySelector.select()`는 호환
   가능한 provider 중 우선순위와 비용이 가장 낮은 것을 고르고, `select_with_degrade()`는
   상위 capability kind가 예산을 넘으면 더 저렴한 다음 kind로 자동 전환한다.

5. **장애 격리 (절대 준수 원칙 #6, AI-B-06)**: provider의 `health_check`가 예외를 던져도
   `ProviderRegistration.is_healthy()`가 이를 흡수해 `False`로 취급한다 — 한 provider의
   장애가 레지스트리 전체나 무관한 capability를 멈추지 않는다.

6. **중앙 레지스트리 일시 장애 대응 (AI-C-10)**: `CapabilityRegistry`는 `_local`과 `_remote`
   테이블을 분리해서 유지한다. 중앙 레지스트리가 응답하지 않으면 `merge_remote_snapshot`이
   단순히 호출되지 않을 뿐이고, 마지막으로 병합된 스냅샷이 계속 사용된다.

7. **폐쇄망 배치 검증 (원칙 #18, AI-C-16)**: `AssetResolver`는 논리 자산 ID를 내부 저장소
   위치로만 해석하고, `AirgapPolicy`는 공개 egress 의존성을 배치 전에 검출한다. 외부 서비스
   의존성이 선택 항목이면 전체 배치를 막지 않고 해당 선택 기능만 비활성화한다.

8. **서버·엣지 동일 실행관리 계약 (원칙 #11, AI-B-11)**: `MultiClusterControlProvider`는
   서버와 구역 엣지 제어면을 하나의 `ControlProvider`처럼 노출한다. 실행 위치는 클러스터
   이름이 아니라 `PlacementRequest`의 required/preferred tag로 결정된다.

9. **보안 오버레이 추상화 (원칙 #10, AI-C-04)**: `NetworkOverlayProvider`는 피어 도달성과
   오버레이 상태만 노출한다. 현재 구현인 Tailscale CLI 호출은 `providers/overlay.py`에만
   갇혀 있고, 오버레이 단절은 업무 전송·관측 장애와 별도 신호로 유지된다.

10. **파트 간 계약 고정 (AI-C-01/03/06/07)**: `schemas/ai`의 JSON Schema가 프레임 참조,
    좌표, 식별자, 시간, 채널 payload를 언어 중립 형식으로 고정한다. `integration/wire.py`는
    AI 내부 객체를 이 계약으로만 변환하므로 하드웨어·백엔드·가시화 구현이 내부 Python
    타입에 의존하지 않는다.

11. **모델 교체 원자성 (AI-B-05/08)**: `ModelDeploymentManager`는 다운로드, 검증, 활성화를
    명시적 상태로 기록한다. 활성화가 실패하면 provider의 이전 버전으로 롤백하고 결과를
    `model_deployment_result` 채널 계약으로 외부에 전달할 수 있다.

## 관제 콘솔과 그 뒤의 하위 시스템 (2026-11)

처음 읽는 사람이 가장 먼저 띄워 보는 것은 관제 콘솔이다. 한 명령으로 뜬다.

```bash
python tools/fms_console/serve.py        # http://127.0.0.1:8800/
```

콘솔은 **판정을 하지 않는다.** 다른 모듈이 이미 내는 값을 모아 한 스냅샷으로 낼 뿐이다.
배치의 정본은 `tools/status_ui/serve.py` 의 `StatusService.fleet()` 이고(provider manifest 를
노드 태그와 **누적 예산**에 맞춰 해소한다), 콘솔이 같은 판정을 다시 하면 두 화면이 서로
다른 답을 말한다. 그래서 `tools/fms_console/` 안에는 조립과 직렬화만 있다.

탭은 드릴의 칸이 아니라 **하는 일**로 갈린다 — 디지털 트윈 맵 · 임무 명령 · 모니터링 ·
로봇 운영 · 계정 관리 다섯이고, 도메인 → 구역 → 로봇 → 기능 → 서브태스크 드릴은 부모를
가리키는 선으로 이어진 팝업이 맡는다(탭 하나가 드릴 한 칸이면 탭을 갈아타는 것이 곧
어디서 왔는지를 잃는 것이다). 탭과 쓰기 단추는 계정이 가진 **능력**으로 열린다 — 능력이
없는 사람에게는 그려지지 않는다. 눌러서 403 을 받는 단추는 알려 주는 것이 없다.

화면에 숫자가 없는 자리가 있는 것은 미완성이 아니다. 배터리·전압·CPU·메모리·지연을 이
저장소는 **아직 측정하지 않으므로** 그 자리에는 점선과 "미측정" 이 들어가고, 같은 칸에
선언된 예산을 넣을 때는 "쓸 수 있다고 적어 둔 양이지 지금 쓰는 양이 아니다" 를 화면이
직접 적는다(AI-B-01 · AI-O-05). 채택자가 자기 계측 provider 를 붙이면 그 자리가 실측으로
바뀌고, 붙이기 전까지 그럴듯한 숫자가 들어가 있지 않다는 것이 이 화면의 약속이다.

| 하위 시스템 | 하는 일 | 요구사항 |
|---|---|---|
| `tools/fms_console/serve.py`, `index.html` | 조회 전용 상태 뷰 + 분리된 제어 계약. 드릴은 연결된 팝업이 맡는다 | AI-O-06, AI-C-19 |
| `tools/fms_console/accounts.py` | 누가 와 있고 무엇을 해도 되는가. 권한은 역할 이름이 아니라 **능력**이며, 계정 파일이 하나 생기는 순간 비밀번호 없는 예시 자세가 닫힌다 | AI-C-19, AI-B-02 |
| `tools/status_ui/serve.py` | 배치 판정의 정본(`StatusService.fleet()`) + `/api/dashboard` 한 장 — 가속기 **개체별** L1 · 서비스 L2 · 작업 그래프 L3 를 섞지 않고 낸다 | AI-O-05, AI-O-06, AI-B-12, AI-B-13 |
| `tools/fms_console/fleet.py` | 선언(프로파일)과 탐지(공지)를 섞지 않고 구역·로봇·기능 가용성을 조립 | AI-C-10, AI-C-18, AI-C-05 |
| `tools/fms_console/subtasks.py` | 기능 클릭 → 서브태스크 그래프. 간선은 자료 흐름에서 유도하고 분해는 `planning/decomposition.py` 에 위임 | AI-B-12, AI-B-14 |
| `tools/fms_console/twin.py` | 여러 장치의 탐지를 지속 객체로 융합. 출처를 하나도 버리지 않고, 틀린 값의 원인을 leave-one-out 으로 매긴다 | AI-S-02, AI-S-06, AI-L-01/03 |
| `tools/fms_console/handover.py`, `mission.py` | 자리·AP 선언에서 RSSI 를 같은 모델로 다시 계산해 구역 전환을 판단하고, 다중 구역 임무를 순서대로 수행 | AI-N-03, AI-N-02, AI-B-12 |
| `tools/fms_console/overlay.py` | 운영자가 고친 값을 선언 위에 덧대는 append-only 장부 | AI-L-03, AI-S-08 |
| `tools/fms_console/labeling.py` | 저장된 프레임에 사람이 상자를 그려 정답을 만들고, 모델과 다른 답만 학습 후보로 올린다 | AI-L-01/02/03 |
| `tools/fms_console/deployment.py` | 비개발자가 웹에서 하는 네 가지 — 들이기·보정·학습·모델 교체. 판정은 각자 주인에게 넘기고 입력만 그 계약의 자료형으로 옮긴다 | AI-B-09, AI-E-02, AI-L-09, AI-L-10 |
| `perception/device_identity.py` | 같은 기종 두 대를 가리는 문제. 식별력 있는 단서와 없는 단서를 구조로 분리 | AI-S-02, AI-S-04 |
| `perception/appearance_classifier.py` | 외형 class 추정과 그 근거(참조별 유사도·게이트) | AI-E-01, AI-S-04 |
| `perception/spatial_evidence.py` | GPS·depth·point cloud·zero-shot·선언·사람이 잰 값을 한 계약으로 융합 | AI-S-06, AI-S-08, AI-C-02 |
| `perception/evidence_kinds.py` | 모듈마다 자기 모양으로 들고 있던 근거 25 종을 한 계약으로 모은다. 충분도는 점수 합이 아니라 **구조**가 판정한다 | AI-S-03, AI-S-05, AI-S-06 |
| `registry/onboarding.py` | 장치 추가를 코드 변경이 아니라 선언 네 가지로 | AI-B-09, AI-C-18 |
| `runtime/refresh.py` | 반영을 요청으로만 일으키는 장부. 상시 폴링 없음 | AI-C-13, AI-O-01 |
| `runtime/environment_profile.py` | 실행 환경(가속기 가용성 등)을 코드 분기가 아니라 선언 프로파일로 해소. 새 환경은 선언 한 건이고 이 모듈을 고치지 않는다 | AI-B-04, AI-C-15, AI-C-05, AI-B-01 |
| `runtime/mlops_pipeline.py` | 검증된 모델 버전을 실행영역에 하나의 계약으로 배포·확대·롤백 | AI-L-10, AI-L-07, AI-B-11 |
| `observability/failure_trace.py`, `providers/observability_query.py` | 실패한 단계의 원인 후보를 순위와 근거로. 미측정과 정상을 섞지 않는다 | AI-O-02/03/05 |

### 이 묶음에서 반복되는 네 가지 규칙

읽을 때 이 넷을 알고 보면 각 모듈의 선택이 설명된다.

**선언과 관측을 같은 칸에 담지 않는다.** 구역에 무엇이 있을 것인가는 프로파일이고, 실제로
무엇이 있는가는 장치의 `Capability` 공지다. 합치면 "선언했는데 없는 것"과 "있는데 선언에
없는 것"을 구분할 수 없고, 그 구분이 운영자가 알아야 하는 것이다.

**없음과 아님을 구분한다.** 미측정은 0 이 아니고, 한 번도 받지 않은 것은 오래된 것이 아니며,
제공자 부재는 반대 근거가 아니다. 이 구분을 잃는 순간 멀쩡한 축소 운용이 장애로 읽히거나
그 반대가 된다(AI-C-05, AI-O-05).

**가리지 못하면 고르지 않는다.** 외형 단서를 열 개 쌓아도 식별 단서 하나를 뒤집지 못하고,
두 후보가 비슷하면 1위를 집지 않고 무엇을 더 하면 풀리는지를 낸다. 점수만 합치는 설계는
같은 기종 두 대를 영원히 구분하지 못한다.

**사람이 고친 값은 모델을 바꾸지 않는다.** 객체 상태는 즉시 바뀌지만 모델에 닿으려면
AI-L-05 검증과 AI-L-07 단계 적용을 지나야 하고, 센서가 말한 값은 지워지지 않고 나란히
남아 불일치를 수치로 적는다(AI-L-03).

### 전역 좌표는 선택 계층이다

위치·방향 값은 끝까지 자기 기준 좌표계를 들고 다니고 **로컬 값과 전역 값은 같은 칸에
담지 않는다.** 현장 로컬↔전역 변환은 도메인 선언의 `site.datum` 으로만 일어나며, 그
선언은 공리가 아니라 **출처·생성 시점·버전·선언된 정확도**를 가진 근거다 — 그 칸 중
하나라도 빠지면 로더가 사유와 함께 거절한다. 검증되지 않은 datum 으로 유도한 값은 그
재료인 로컬 측정보다 정확한 척하지 못하고, 측정되지 않은 정확도는 `null` 로 남는다
(`accuracy_m: 0` 선언 자체가 거절된다 — 0 은 "오차가 없다"는 주장이다).

**datum 이 없는 현장은 정상 배치다.** 전역 계층만 비활성이 되고 그 사유가 응답에 남으며
(`no_datum` / `datum_unverified`) 지도·구역·로봇과 모든 로컬 판단은 그대로 돈다. 단일
카메라·단일 구역 구성이 아무 추가 선언 없이 도는 이유가 그것이다. 배경 지도 타일도 같은
성격의 선택 계층이고 **기본값은 타일 없음**이다 — 공개 타일 서버를 기본으로 두면 폐쇄망
배치에서 메인 화면이 깨지고 배치 전 검증에 걸린다(AI-C-16). 외부 연결을 요구하는 레이어는
선언에 `requires_external_connection` 과 호스트를 적어야 하고, 폐쇄망 선언에서는 그런
레이어를 켜는 선언 자체가 거절된다.

전역 좌표 **숫자**가 뷰 계약으로 나가는가는 코드 상수가 아니라 **현장마다의 선언**이
정한다. `tools/fms_console/fleet.py::global_release()` 한 곳이 네 조건을 차례로 본다 —
datum 이 있는가 · 검증됐는가 · 정확도가 선언됐는가(미측정은 0 이 아니다) · 전역 상태의
authoritative 주인을 다른 파트와 **재합의한 기록**(`site.boundary_agreement`)이 있는가.
하나라도 없으면 숫자는 나가지 않고 그 자리에 첫 번째로 걸린 사유가 남는다
(`no_datum` / `datum_unverified` / `accuracy_unmeasured` / `boundary_not_reagreed`).

네 조건이 모두 서면 위경도는 로컬 칸 **옆의 다른 칸**(`at_global`)으로 나가고, 같은
칸에 섞이지 않는다. 그 블록은 자기가 유도된 datum 의 선언된 정확도를 들고 다니므로,
유도된 전역 값이 재료인 로컬 측정보다 정확한 척할 수 없다. 이 칸들은 더하기만 한
변화라 계약 판은 minor 로 올랐다(2.1). 자기 배포에서 전역 값을 쓰려는 채택자가 고칠
자리는 코드가 아니라 그 현장의 프로파일 선언이다.

### 가시화는 교체 가능하다

서버 응답에 색·픽셀·폰트가 없다. 맵은 지금 인라인 SVG 로 그리지만 `index.html` 의
`const Map3D = SvgMapRenderer;` 한 줄이 교체 지점이고, Unity WebGL 뷰어는 같은
`/api/scene`·`/api/domain`·`/api/zone` 을 읽어 자기 방식으로 그리면 된다. 외부 가시화 팀이
읽는 계약은 [view-contract.md](view-contract.md) + `schemas/view_*.schema.json` 이며, 응답에
표현 결정이 섞이는 날 `tests/test_view_contract.py` 가 깨진다. 픽셀은 상태 계약으로 나가지
않고 `/api/media` 가 따로 낸다(AI-C-08).

## 추가된 기능 모듈 (하드웨어·타 파트 없이 구현·검증된 부분)

`초기 구현 계획 노트(비공개)`의 권장 순서를 따라 시작했고, 이후 실
전송·관측·오케스트레이션 provider와 새 인프라 경계까지 확장해 구현·검증했다.
현재 회귀 수치는 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` 실행 결과를 기준으로 한다:

| 모듈 | 요구사항 |
|---|---|
| `providers/fakes.py` | AI-C-04/06/07/08, AI-B-08 |
| `contracts/data_dictionary.py` | AI-C-01 |
| `planning/template_proposal.py`, `planning/mission_recommendation.py` | AI-B-14/15 (구 AI-D 계열은 번호를 재사용하지 않는다) |
| `perception/tracking.py`, `association.py`, `uncertainty.py`, `unconfirmed.py`, `info_selection.py` | AI-S-01~05 |
| `risk/fsm.py`, `scoring.py`, `output.py`, `adjustment.py` | AI-R-01/02 (구 AI-R-03/04 는 AI-R-02·AI-C-19 로 흡수) |
| `execution/control.py`, `lifecycle.py`, `conformance.py` | AI-B-03/05/09 |
| `observability/metrics.py`, `events.py`, `reproduction.py`, `availability.py` | AI-O-01~04 |
| `perception/detection.py`, `auxiliary.py`, `edge/calibration.py`, `calibration_profile.py`, `ondevice/config_apply.py` | AI-E-01~04, AI-N-02 |
| `providers/mqtt.py`, `providers/kafka.py`, `providers/otel.py`, `providers/k3s.py`, `providers/compute.py` | AI-C-06, AI-O-01~03, AI-B-02/05/08 |
| `runtime/airgap.py`, `runtime/clusters.py`, `providers/overlay.py` | AI-C-16, AI-C-04, AI-B-11 |
| `runtime/model_deployment.py`, `integration/wire.py`, `schemas/ai` | AI-B-05/08, AI-C-01/03/06/07, 파트 간 연동 |
| `contracts/physical_command.py`, `execution/command_execution.py` | AI-B-03(물리/기능 명령 lifecycle 계약, idempotency, cancel 경쟁 처리) |

## 아직 이 저장소에 없는 것

- AI-B-10의 실물 말단 경량성 검증과 AI-N-01 최소 처리주기 실측은 실제 하드웨어가 필요하다.
- AI-C-10의 최종 장치 가용성은 백엔드 통합 판정을 입력으로 소비해야 하므로, 현재는
  `simulation/backend.py` mock으로 대역하고 실제 백엔드 API 연동은 외부 산출물 이후 작업이다.
- 실제 센서 입력, 백엔드 broker/API, 가시화 렌더러 연결은 각 파트 브랜치의 책임이다. 현재
  브랜치가 제공하는 계약은 `schemas/ai/`의 JSON Schema뿐이다.

요구사항 ID 별 구현 위치는 각 모듈 docstring 첫 줄의 `implements:` 가 정본이다 —
코드와 함께 움직이므로 표처럼 낡지 않는다. `grep -rn 'implements: AI-' .` 로 전부 나온다.
개발 중의 항목별 충족 판정표는 이 저장소의 공개 범위 밖(내부 기록)에 있다.
