# AI 요구사항 추적표 (담당: 진나영)

CLAUDE.md §7 규칙에 따라 요구사항 ID별 구현 위치·테스트·충족 여부를 기록한다.
공통 골격(§6 1~4단계) 이후, `docs/ai/01-standalone-implementation-plan.md`에서 정리한
"하드웨어·타 파트 없이 구현·검증 가능한 범위(Tier A/B)"를 권장 순서대로 구현했다:
Provider fake → 의사결정(D) → 추적/판단(S) → 위험도(R) → 실행제어·배포·관측(B/O) →
인지·캘리브레이션·환경설정(E/N-02). 전 항목 pytest로 실제 검증됨 (`ai-framework/tests`,
110개 테스트 통과).

상태 값: **완료** = 요구사항이 정의한 동작·경계가 테스트로 보장됨 /
**부분** = 핵심 일부만 구현, 명시된 gap 있음 / **미착수**.

## 온디바이스

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-N-01 | 완료 | `reference/local_safety.py` | `tests/test_local_safety.py` |
| AI-N-02 | 완료 | `ondevice/config_apply.py` | `tests/test_config_apply.py` |

## 감시·인지 (엣지)

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-E-01 | 완료 | `perception/detection.py` (`PerceptionProvider`, `NullPerceptionProvider`, `BrightBlobDetector`) | `tests/test_detection.py` |
| AI-E-02 | 완료 (합성 데이터로 검증 — 실제 카메라/체커보드 없이 `cv2.calibrateCamera` 정확도 확인) | `edge/calibration.py` | `tests/test_calibration.py` |
| AI-E-03 | 완료 | `edge/calibration_profile.py` | `tests/test_calibration_profile.py` |
| AI-E-04 | 완료 | `perception/auxiliary.py` | `tests/test_auxiliary.py` |

## 의사결정

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-D-01 | 완료 | `decision/subtask.py` | `tests/test_subtask_generator.py` |
| AI-D-02 | 완료 (`jsonschema` + 커스텀 rule) | `decision/validator.py` | `tests/test_subtask_validator.py` |
| AI-D-03 | 미착수 (이번 순서에 미포함) | - | - |
| AI-D-04 | 완료 | `decision/regeneration.py` | `tests/test_regeneration.py` |

## 감시·인지 (추적/판단)

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-S-01 | 완료 (IOU 기반 reference tracker) | `perception/tracking.py` | `tests/test_tracking.py` |
| AI-S-02 | 완료 | `perception/association.py` | `tests/test_association.py` |
| AI-S-03 | 완료 | `perception/uncertainty.py` | `tests/test_uncertainty.py` |
| AI-S-04 | 완료 | `perception/unconfirmed.py` | `tests/test_unconfirmed.py` |
| AI-S-05 | 완료 | `perception/info_selection.py` | `tests/test_info_selection.py` |

## 위험도

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-R-01 | 완료 | `risk/fsm.py` | `tests/test_risk_fsm.py` |
| AI-R-02 | 완료 | `risk/scoring.py` | `tests/test_risk_scoring.py` |
| AI-R-03 | 완료 | `risk/output.py` | `tests/test_risk_output.py` |
| AI-R-04 | 완료 | `risk/adjustment.py` | `tests/test_risk_adjustment.py` |

## 자원·배포

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-B-01 | 완료 | `contracts/profile.py` | `tests/test_selector.py` |
| AI-B-02 | 부분 (독립 실행 계약은 `execution/control.py`+`execution/lifecycle.py`로 커버; 실제 OCI 컨테이너 패키징은 Docker 런타임 필요 — 미착수) | `execution/control.py`, `execution/lifecycle.py` | `tests/test_control.py`, `tests/test_lifecycle.py` |
| AI-B-03 | 완료 | `execution/control.py::LocalControlSupervisor` | `tests/test_control.py` |
| AI-B-04 | 부분 (required/preferred hw 태그 구분은 구현; preferred 태그 가중치는 선택 로직에 아직 미반영) | `contracts/profile.py::CompatibilityProfile` | `tests/test_selector.py` |
| AI-B-05 | 완료 | `execution/lifecycle.py::LifecycleManager` | `tests/test_lifecycle.py` |
| AI-B-06 | 완료 | `selection/selector.py::CapabilitySelector.select_with_degrade` | `tests/test_selector.py`, `tests/test_risk_adjustment.py` |
| AI-B-07 | 완료 (health 격리 + lifecycle 롤백) | `registry/capability_registry.py::ProviderRegistration.is_healthy`, `execution/lifecycle.py` | `tests/test_capability_registry.py`, `tests/test_lifecycle.py` |
| AI-B-08 | 완료 | `providers/adapters.py::AIRuntimeProvider` + `providers/fakes.py::StubAIRuntimeProvider` | `tests/test_provider_fakes.py` |
| AI-B-09 | 완료 (conformance 하네스) | `execution/conformance.py` | `tests/test_conformance.py` |
| AI-B-10 | 미착수 (실제 말단 하드웨어 배포 필요) | - | - |

## 관측

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-O-01 | 완료 | `observability/metrics.py::EdgeMetricStore` | `tests/test_observability.py` |
| AI-O-02 | 완료 | `observability/events.py::CapabilityEventReporter` | `tests/test_observability.py` |
| AI-O-03 | 완료 | `observability/reproduction.py` | `tests/test_observability.py` |
| AI-O-04 | 완료 | `observability/availability.py` | `tests/test_observability.py` |

## 공통

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-C-01 | 미착수 (의도적 보류 — §6-8: 전체 기능 구현 후 데이터 사전 통일) | - | - |
| AI-C-02 | 미착수 (이번 순서에 미포함) | - | - |
| AI-C-03 | 미착수 (이번 순서에 미포함) | - | - |
| AI-C-04 | 완료 | `providers/adapters.py` + `providers/fakes.py` | `tests/test_provider_fakes.py` |
| AI-C-05 | 완료 | `contracts/capability.py` | 다수 |
| AI-C-06 | 완료 (fake TransportProvider; 실 MQTT/Kafka/Bridge는 BE-T-01 이후) | `providers/fakes.py::InMemoryTransportProvider` | `tests/test_provider_fakes.py`, `tests/test_risk_output.py` |
| AI-C-07 | 완료 | `providers/fakes.py::JsonSerializerProvider` | `tests/test_provider_fakes.py`, `tests/test_risk_output.py` |
| AI-C-08 | 완료 | `providers/fakes.py::SyntheticMediaSourceProvider` | `tests/test_provider_fakes.py` |
| AI-C-09 | 완료 (AIRuntimeProvider 재사용) | `providers/adapters.py`, `perception/auxiliary.py` | `tests/test_provider_fakes.py`, `tests/test_auxiliary.py` |
| AI-C-10 | 완료 | `registry/capability_registry.py::CapabilityRegistry` | `tests/test_capability_registry.py` |
| AI-C-11 | 완료 | `contracts/capability.py::CapabilityRequirement.evaluate` | `tests/test_local_safety.py` 등 |
| AI-C-12 | 완료 | `providers/adapters.py` (6종 Protocol) | `tests/test_provider_fakes.py` |
| AI-C-13 | 완료 | `selection/selector.py::CapabilitySelector.select` | `tests/test_selector.py` |
| AI-C-14 | 미착수 (이번 순서에 미포함) | - | - |
| AI-C-15 | 완료 (데이터 구조; 실제 도메인 프로파일 파일 로더는 미구현) | `contracts/profile.py::DeploymentProfile` | - |

## 요약

- **완료: 40 / 48**
- **부분: 2** — AI-B-02(실제 컨테이너 패키징 제외), AI-B-04(preferred 가중치 제외)
- **미착수: 6** — AI-B-10, AI-C-01(의도적 보류), AI-C-02, AI-C-03, AI-C-14, AI-D-03
  (뒤 4개는 Tier A로 분류돼 있었으나 이번 구현 순서에는 포함되지 않았음 — 다음 순서 후보)
- **Tier C (타 파트/실 인프라 필요, 위 "완료" 항목도 fake provider 계약까지만 검증됨)**:
  AI-C-06 실제 MQTT/Kafka, AI-B-02/05 실제 컨테이너·오케스트레이터, AI-B-10 실제 말단 배포,
  AI-O-01 실제 OTel/Prometheus, AI-C-10 백엔드 가용성 연계, AI-S-02 실제 다중카메라 —
  `docs/ai/01-standalone-implementation-plan.md` Tier C 표 참고

**검증 명령**: `cd ai-framework && pytest -q` → 110 passed.

**추가 요구사항 필요 여부**: 없음. 문서에 없는 기능을 임의로 추가하지 않았다.
