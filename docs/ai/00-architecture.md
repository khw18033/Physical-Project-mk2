# AI 프레임워크 구조 (진나영 담당분)

CLAUDE.md §4 구조도를 그대로 따른다.

```text
Domain / Application Logic
        │
        ├─ Perception / Decision / Risk / Safety      <- ai_framework/reference/*, 향후 perception/decision/risk 모듈
        │
Common Capability & Provider Interfaces
        │
        ├─ Input / Media Adapter                       <- ai_framework/providers/adapters.py: MediaSourceProvider
        ├─ AI Runtime Provider                          <- ai_framework/providers/adapters.py: AIRuntimeProvider
        ├─ Transport Provider                           <- ai_framework/providers/adapters.py: TransportProvider
        ├─ Serializer Provider                          <- ai_framework/providers/adapters.py: SerializerProvider
        ├─ Control / Orchestrator Provider              <- ai_framework/providers/adapters.py: ControlProvider
        └─ Observability Provider                       <- ai_framework/providers/adapters.py: ObservabilityProvider
        │
Capability Registry + Resource Profile + Deployment Profile
        │                                               <- ai_framework/registry/capability_registry.py
        │                                               <- ai_framework/contracts/profile.py
        │                                               <- ai_framework/selection/selector.py
Concrete Hardware / Sensor / Runtime / Protocol / Infrastructure
                                                          (현재 배포: MQTT/Kafka/OTel/K3s/RTSP 등 -
                                                           위 provider 뒤에 숨음, 이 저장소에는 아직 미구현)
```

## 핵심 개념과 요구사항 매핑

| 개념 | 위치 | 관련 요구사항 |
|---|---|---|
| `CapabilityState` (ACTIVE/DEGRADED/DISABLED) | `contracts/capability.py` | AI-C-05, AI-C-11 |
| `CapabilityRequirement` (required/optional 선언 + 평가) | `contracts/capability.py` | AI-C-11 |
| `CompatibilityProfile`, `ResourceCost`, `ResourceBudget` | `contracts/profile.py` | AI-B-01, AI-B-04, AI-C-13 |
| `DeploymentProfile` (도메인 = 데이터) | `contracts/profile.py` | AI-C-15 |
| `TransportProvider` / `SerializerProvider` / `MediaSourceProvider` / `AIRuntimeProvider` / `ControlProvider` / `ObservabilityProvider` | `providers/adapters.py` | AI-C-04, AI-C-06~09, AI-C-12, AI-B-03, AI-B-08 |
| `CapabilityRegistry` (local + remote snapshot) | `registry/capability_registry.py` | AI-C-10, AI-B-07 |
| `CapabilitySelector` (호환성 필터 + 최소자원 + 단계적 축소) | `selection/selector.py` | AI-B-01, AI-B-04, AI-B-06, AI-C-13 |
| `LocalSafetyJudge` (수직 슬라이스 예시) | `reference/local_safety.py` | AI-N-01 |

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

## 추가된 기능 모듈 (하드웨어·타 파트 없이 구현·검증된 부분)

`docs/ai/01-standalone-implementation-plan.md`의 권장 순서를 따라 아래 모듈을 fake
provider와 합성 데이터로 구현·검증했다 (48개 중 40개 완료, `pytest -q` 110개 통과):

| 모듈 | 요구사항 |
|---|---|
| `providers/fakes.py` | AI-C-04/06/07/08/09/12, AI-B-08 |
| `decision/subtask.py`, `validator.py`, `regeneration.py` | AI-D-01/02/04 |
| `perception/tracking.py`, `association.py`, `uncertainty.py`, `unconfirmed.py`, `info_selection.py` | AI-S-01~05 |
| `risk/fsm.py`, `scoring.py`, `output.py`, `adjustment.py` | AI-R-01~04 |
| `execution/control.py`, `lifecycle.py`, `conformance.py` | AI-B-03/05/09 |
| `observability/metrics.py`, `events.py`, `reproduction.py`, `availability.py` | AI-O-01~04 |
| `perception/detection.py`, `auxiliary.py`, `edge/calibration.py`, `calibration_profile.py`, `ondevice/config_apply.py` | AI-E-01~04, AI-N-02 |

## 아직 이 저장소에 없는 것

- 위 fake provider를 실제 MQTT/Kafka/K3s/OTel provider 구현에 연결하는 어댑터
  (AI-C-06 실연동, AI-B-02/05 실제 컨테이너·오케스트레이터, AI-B-10, AI-O-01 실 관측스택 등
  — Tier C, 타 파트 산출물 필요).
- AI-D-03, AI-C-02, AI-C-03, AI-C-14 (Tier A로 분류되었으나 이번 구현 순서에는 미포함).
- 공통 데이터 사전 기반 변수명 통일 (AI-C-01) — CLAUDE.md §6-8 순서상 전체 기능 구현 후
  진행 대상이므로 의도적으로 보류함.

전체 48개 항목별 구현 상태는 [requirement-traceability.md](requirement-traceability.md),
표준형 없이 구현 가능한 범위 판단 기준은 [01-standalone-implementation-plan.md](01-standalone-implementation-plan.md) 참고.
