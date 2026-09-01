# AI 프레임워크 구조 (진나영 담당분)

CLAUDE.md §4 구조도를 그대로 따른다.

```text
Domain / Application Logic
        │
        ├─ Perception / Decision / Risk / Safety      <- perception_framework/reference/*, 향후 perception/decision/risk 모듈
        │
Common Capability & Provider Interfaces
        │
        ├─ Input / Media Adapter                       <- perception_framework/providers/adapters.py: MediaSourceProvider
        ├─ AI Runtime Provider                          <- perception_framework/providers/adapters.py: AIRuntimeProvider
        ├─ Transport Provider                           <- perception_framework/providers/adapters.py: TransportProvider
        ├─ Serializer Provider                          <- perception_framework/providers/adapters.py: SerializerProvider
        ├─ Control / Orchestrator Provider              <- perception_framework/providers/adapters.py: ControlProvider
        ├─ Observability Provider                       <- perception_framework/providers/adapters.py: ObservabilityProvider
        ├─ Network Overlay Provider                     <- perception_framework/providers/adapters.py: NetworkOverlayProvider
        └─ Model Deployment Provider                    <- perception_framework/providers/adapters.py: ModelDeploymentProvider
        │
Capability Registry + Resource Profile + Deployment Profile
        │                                               <- perception_framework/registry/capability_registry.py
        │                                               <- perception_framework/contracts/profile.py
        │                                               <- perception_framework/selection/selector.py
Concrete Hardware / Sensor / Runtime / Protocol / Infrastructure
                                                          (현재 배포: MQTT/Kafka/OTel/K3s/Tailscale/RTSP 등 -
                                                           위 provider 뒤에 숨음)
        │
Cross-part Wire Contract                                <- contracts/ai/*.schema.json
                                                          perception_framework/integration/wire.py
```

## 핵심 개념과 요구사항 매핑

| 개념 | 위치 | 관련 요구사항 |
|---|---|---|
| `CapabilityState` (ACTIVE/DEGRADED/DISABLED) | `contracts/capability.py` | AI-C-05, AI-C-11 |
| `CapabilityRequirement` (required/optional 선언 + 평가) | `contracts/capability.py` | AI-C-11 |
| `CompatibilityProfile`, `ResourceCost`, `ResourceBudget` | `contracts/profile.py` | AI-B-01, AI-B-04, AI-C-13 |
| `DeploymentProfile` (도메인 = 데이터) | `contracts/profile.py` | AI-C-15 |
| `FieldSpec` / `DATA_DICTIONARY` | `contracts/data_dictionary.py` | AI-C-01, AI-C-14 |
| 8종 provider Protocol (전송·직렬화·미디어·AI 런타임·제어·관측·오버레이·모델 배포) | `providers/adapters.py` | AI-C-04, AI-C-06~09, AI-C-12, AI-C-17, AI-B-03, AI-B-08 |
| `CapabilityRegistry` (local + remote snapshot) | `registry/capability_registry.py` | AI-C-10, AI-B-07 |
| `CapabilitySelector` (호환성 필터 + 최소자원 + 단계적 축소) | `selection/selector.py` | AI-B-01, AI-B-04, AI-B-06, AI-C-13 |
| `LocalSafetyJudge` (수직 슬라이스 예시) | `reference/local_safety.py` | AI-N-01 |
| `AssetResolver` / `AirgapPolicy` | `runtime/airgap.py` | AI-C-16, AI-B-09 |
| `MultiClusterControlProvider` | `runtime/clusters.py` | AI-B-11, AI-B-03, AI-B-05 |
| `TailscaleOverlayProvider` / `OverlayAwareRemoteGate` | `providers/overlay.py` | AI-C-17, AI-O-04 |
| `ModelDeploymentManager` / `ModelDeploymentProvider` | `runtime/model_deployment.py`, `providers/adapters.py` | AI-B-05, AI-B-07, AI-B-08 |
| 공통 JSON Schema / wire adapter | `contracts/ai`, `integration/wire.py` | AI-C-01, AI-C-03, AI-C-06, AI-C-07, 파트 간 연동 |

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

5. **장애 격리 (절대 준수 원칙 #6, AI-B-06/07)**: provider의 `health_check`가 예외를 던져도
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

9. **보안 오버레이 추상화 (원칙 #10, AI-C-17)**: `NetworkOverlayProvider`는 피어 도달성과
   오버레이 상태만 노출한다. 현재 구현인 Tailscale CLI 호출은 `providers/overlay.py`에만
   갇혀 있고, 오버레이 단절은 업무 전송·관측 장애와 별도 신호로 유지된다.

10. **파트 간 계약 고정 (AI-C-01/03/06/07)**: `contracts/ai`의 JSON Schema가 프레임 참조,
    좌표, 식별자, 시간, 채널 payload를 언어 중립 형식으로 고정한다. `integration/wire.py`는
    AI 내부 객체를 이 계약으로만 변환하므로 하드웨어·백엔드·가시화 구현이 내부 Python
    타입에 의존하지 않는다.

11. **모델 교체 원자성 (AI-B-05/07/08)**: `ModelDeploymentManager`는 다운로드, 검증, 활성화를
    명시적 상태로 기록한다. 활성화가 실패하면 provider의 이전 버전으로 롤백하고 결과를
    `model_deployment_result` 채널 계약으로 외부에 전달할 수 있다.

## 추가된 기능 모듈 (하드웨어·타 파트 없이 구현·검증된 부분)

`docs/ai/archive/01-standalone-implementation-plan.md`의 권장 순서를 따라 시작했고, 이후 실
전송·관측·오케스트레이션 provider와 새 인프라 경계까지 확장해 구현·검증했다.
현재 회귀 수치는 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` 실행 결과를 기준으로 한다:

| 모듈 | 요구사항 |
|---|---|
| `providers/fakes.py` | AI-C-04/06/07/08/09/12, AI-B-08 |
| `contracts/data_dictionary.py` | AI-C-01 |
| `decision/subtask.py`, `validator.py`, `regeneration.py` | AI-D-01/02/04 |
| `perception/tracking.py`, `association.py`, `uncertainty.py`, `unconfirmed.py`, `info_selection.py` | AI-S-01~05 |
| `risk/fsm.py`, `scoring.py`, `output.py`, `adjustment.py` | AI-R-01~04 |
| `execution/control.py`, `lifecycle.py`, `conformance.py` | AI-B-03/05/09 |
| `observability/metrics.py`, `events.py`, `reproduction.py`, `availability.py` | AI-O-01~04 |
| `perception/detection.py`, `auxiliary.py`, `edge/calibration.py`, `calibration_profile.py`, `ondevice/config_apply.py` | AI-E-01~04, AI-N-02 |
| `providers/mqtt.py`, `providers/kafka.py`, `providers/otel.py`, `providers/k3s.py`, `providers/compute.py` | AI-C-06, AI-O-01~03, AI-B-02/05/08 |
| `runtime/airgap.py`, `runtime/clusters.py`, `providers/overlay.py` | AI-C-16/17, AI-B-11 |
| `runtime/model_deployment.py`, `integration/wire.py`, `contracts/ai` | AI-B-05/07/08, AI-C-01/03/06/07, 파트 간 연동 |

## 아직 이 저장소에 없는 것

- AI-B-10의 실물 말단 경량성 검증과 AI-N-01 최소 처리주기 실측은 실제 하드웨어가 필요하다.
- AI-C-10의 최종 장치 가용성은 백엔드 통합 판정을 입력으로 소비해야 하므로, 현재는
  `simulation/backend.py` mock으로 대역하고 실제 백엔드 API 연동은 외부 산출물 이후 작업이다.
- 실제 센서 입력, 백엔드 broker/API, 가시화 렌더러 연결은 각 파트 브랜치의 책임이다. 현재
  브랜치가 제공하는 계약은 `contracts/ai/`의 JSON Schema뿐이다.

전체 요구사항 항목별 구현 상태는 [requirement-traceability.md](requirement-traceability.md)를
기준으로 한다.
