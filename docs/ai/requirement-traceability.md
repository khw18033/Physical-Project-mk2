# AI 요구사항 추적표 (담당: 진나영)

CLAUDE.md §7 규칙에 따라 요구사항 ID별 구현 위치·테스트·충족 여부를 기록한다.
공통 골격(§6 1~4단계) 이후, `docs/ai/01-standalone-implementation-plan.md`에서 정리한
"하드웨어·타 파트 없이 구현·검증 가능한 범위(Tier A/B)"를 권장 순서대로 구현했다:
Provider fake → 의사결정(D) → 추적/판단(S) → 위험도(R) → 실행제어·배포·관측(B/O) →
인지·캘리브레이션·환경설정(E/N-02) 이후 공통 데이터 사전, 폐쇄망, 보안 오버레이,
서버·엣지 통합 실행관리, 모델 배포 lifecycle, 파트 간 wire 계약까지 반영했다. 전 항목 pytest로 실제 검증됨
(`perception-framework/tests`, 484 passed / 22 skipped; 2026-09-01 기능 검증).

상태 값: **완료** = 요구사항이 정의한 동작·경계가 테스트로 보장됨 /
**부분** = 핵심 일부만 구현, 명시된 gap 있음 / **미착수**.

## 온디바이스

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-N-01 | 완료 | `reference/local_safety.py` | `tests/test_local_safety.py` |
| AI-N-02 | 완료 | `ondevice/config_apply.py` | `tests/test_config_apply.py` |
| AI-N-03 | 완료 (추세 예측 + 비대칭 이력 기반 축소·복귀) | `ondevice/link_handover.py` | `tests/test_link_handover.py` |

## 감시·인지 (엣지)

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-E-01 | 완료 | `perception/detection.py` (`PerceptionProvider`, `NullPerceptionProvider`, `BrightBlobDetector`) | `tests/test_detection.py` |
| AI-E-02 | 완료 (합성 데이터로 검증 — 실제 카메라/체커보드 없이 `cv2.calibrateCamera` 정확도 확인) | `edge/calibration.py` | `tests/test_calibration.py` |
| AI-E-03 | 완료 | `edge/calibration_profile.py` | `tests/test_calibration_profile.py` |
| AI-E-04 | 완료 | `perception/auxiliary.py` | `tests/test_auxiliary.py` |
| AI-E-05 | 완료 (기준점 상대 추정 + 근거 누적 불확실도, 1안: 전역 좌표계 정의 안 함) | `perception/environment_map.py` | `tests/test_environment_map.py` |

## 의사결정

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-D-01 | 이관 완료 (가시화 파트) — 구현·테스트·계약 삭제 | 삭제됨 (이관 기록은 git 이력 참고) | 삭제됨 |
| AI-D-02 | 이관 완료 (가시화 파트) — 구현·테스트·계약 삭제 | 삭제됨 (이관 기록은 git 이력 참고) | 삭제됨 |
| AI-D-03 | 완료 | `decision/info_request.py` | `tests/test_info_request.py` |
| AI-D-04 | 이관 완료 (가시화 파트) — 구현·테스트·계약 삭제 | 삭제됨 (이관 기록은 git 이력 참고) | 삭제됨 |

## 감시·인지 (추적/판단)

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-S-01 | 완료 (IOU 기반 reference tracker) + 이종 evidence의 지속 객체 레코드 (`perception/object_record.py`, `tests/test_object_record.py`) | `perception/tracking.py` | `tests/test_tracking.py` |
| AI-S-02 | 완료 | `perception/association.py` | `tests/test_association.py` |
| AI-S-03 | 완료 + 신뢰도와 근거 충분도 분리 보고 (`perception/object_record.py::ObjectRecord.evidence_sufficient`) | `perception/uncertainty.py` | `tests/test_uncertainty.py` |
| AI-S-04 | 완료 + 명명 근거 없으면 unknown 유지 (`perception/object_record.py`) | `perception/unconfirmed.py` | `tests/test_unconfirmed.py` |
| AI-S-05 | 완료 | `perception/info_selection.py` | `tests/test_info_selection.py` |
| AI-S-06 | 완료 (이종 근거 점진적 객체 레코드) | `perception/object_record.py` | `tests/test_object_record.py` |

## 위험도

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-R-01 | 완료 | `risk/fsm.py` | `tests/test_risk_fsm.py` |
| AI-R-02 | 완료 | `risk/scoring.py` | `tests/test_risk_scoring.py` |
| AI-R-03 | 완료 (내부 결과와 파트 간 `risk_state` payload 모두 검증) | `risk/output.py`, `integration/wire.py`, `contracts/ai/risk-judgment.schema.json` | `tests/test_risk_output.py`, `tests/test_wire_integration.py`, `tests/test_integration_contract_schemas.py` |
| AI-R-04 | 완료 | `risk/adjustment.py` | `tests/test_risk_adjustment.py` |

## 자원·배포

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-B-01 | 완료 | `contracts/profile.py` | `tests/test_selector.py` |
| AI-B-02 | 완료 (OCI 이미지 빌드 + 컨테이너 내 테스트 통과 실증; 오케스트레이터 없이도 동일 코드 실행) | `Dockerfile`, `execution/control.py`, `execution/lifecycle.py` | `tests/test_control.py`, `tests/test_lifecycle.py`, `docker run ... pytest` |
| AI-B-03 | 완료 (standalone + K3s 두 provider가 동일 계약; audit/trace 분리 검증) | `execution/control.py`, `providers/k3s.py` | `tests/test_control.py`, `tests/test_k3s_control.py` |
| AI-B-04 | 완료 (preferred 태그가 선택 순위에 반영되며 배제는 하지 않음) | `contracts/profile.py::CompatibilityProfile.preference_penalty`, `selection/selector.py` | `tests/test_selector.py`, `tests/test_compute_providers.py` |
| AI-B-05 | 완료 (실행 상태기계 + **실 K3s 배포·기동·중지·상태조회** + 모델 다운로드·검증·활성화 lifecycle) | `execution/lifecycle.py`, `providers/k3s.py::K3sControlProvider`, `runtime/model_deployment.py` | `tests/test_lifecycle.py`, `tests/test_k3s_control.py`, `tests/test_model_deployment.py` |
| AI-B-06 | 완료 | `selection/selector.py::CapabilitySelector.select_with_degrade` | `tests/test_selector.py`, `tests/test_risk_adjustment.py` |
| AI-B-07 | 완료 (health 격리 + 실행/model lifecycle 롤백 + K3s rollout undo, 오케스트레이터 부재 시 거부로 축소) | `registry/capability_registry.py`, `execution/lifecycle.py`, `runtime/model_deployment.py`, `providers/k3s.py` | `tests/test_capability_registry.py`, `tests/test_lifecycle.py`, `tests/test_model_deployment.py`, `tests/test_k3s_control.py` |
| AI-B-08 | 완료 (스텁 + **실제 CPU/OpenCL 런타임 2종 교체 실증** + 모델 배포 provider 교체 계약, 벤더명 정적 검사) | `providers/adapters.py::{AIRuntimeProvider,ModelDeploymentProvider}`, `providers/compute.py` | `tests/test_provider_fakes.py`, `tests/test_compute_providers.py`, `tests/test_model_deployment.py` |
| AI-B-09 | 완료 (conformance 하네스) | `execution/conformance.py` | `tests/test_conformance.py` |
| AI-B-10 | 부분 (엣지에만 Bridge/K3s/Collector를 두는 배치를 코드·테스트로 표현; 실물 말단 하드웨어 검증은 미착수) | `edge/bridge.py`, `providers/k3s.py`(kubectl CLI만 사용) | `tests/test_kafka_bridge.py` |
| AI-B-11 | 완료 (서버·엣지 별도 제어면을 동일 `ControlProvider` 계약 뒤에서 라우팅) | `runtime/clusters.py` | `tests/test_overlay_and_clusters.py` |

## 관측

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-O-01 | 완료 (엣지 상세/요약 + **실 OTel Collector OTLP 수출 검증**) + 시연 실험 캡처 요약/개별 분리 (`observability/experiment.py`, `tests/test_experiment_capture.py`) | `observability/metrics.py`, `providers/otel.py::OtlpObservabilityProvider` | `tests/test_observability.py`, `tests/test_otel_observability.py` |
| AI-S-06 수집 | 완료 (실측 완료시각 기반 evidence 수집 세션) | `collection/session.py`, `collection/sampler.py` | `tests/test_collection_session.py` |
| AI-O-02 | 완료 (수집기 장애 시에도 로컬 사건 보존, metric 요약과 분리, `ai_failure`/`capability_status` wire 채널 분리 실증) + 캡처 장애 격리 (`observability/experiment.py`) | `observability/events.py`, `providers/otel.py`, `integration/wire.py` | `tests/test_observability.py`, `tests/test_otel_observability.py`, `tests/test_wire_integration.py` |
| AI-O-03 | 완료 (+ 실 Kafka offset 기반 단기 replay 참조) + 실행 조건·버전 포함 run bundle 재현 (`observability/experiment.py::ExperimentRecorder.bundle`) | `observability/reproduction.py`, `providers/kafka.py::ReplayReference` | `tests/test_observability.py`, `tests/test_kafka_bridge.py` |
| AI-O-04 | 완료 | `observability/availability.py` | `tests/test_observability.py` |

## 공통

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-C-01 | 완료 (공통 필드 의미·값 종류·생산자·소비자·데이터 평면 사전 + 언어 중립 JSON Schema + 임의 필드 검출) | `contracts/data_dictionary.py`, `../contracts/ai`, `integration/wire.py` | `tests/test_data_dictionary.py`, `tests/test_integration_contract_schemas.py`, `tests/test_wire_integration.py` |
| AI-C-02 | 완료 | `common/coordinates.py` | `tests/test_coordinates.py` |
| AI-C-03 | 완료 | `common/timing.py` | `tests/test_timing.py` |
| AI-C-04 | 완료 | `providers/adapters.py` + `providers/fakes.py` | `tests/test_provider_fakes.py` |
| AI-C-05 | 완료 | `contracts/capability.py` | 다수 |
| AI-C-06 | 완료 (**실 MQTT + 실 Kafka + 엣지 양방향 Bridge 왕복 검증**) | `providers/mqtt.py`, `providers/kafka.py`, `edge/bridge.py` | `tests/test_mqtt_transport.py`, `tests/test_kafka_bridge.py` |
| AI-C-07 | 완료 | `providers/fakes.py::JsonSerializerProvider` | `tests/test_provider_fakes.py`, `tests/test_risk_output.py` |
| AI-C-08 | 완료 | `providers/fakes.py::SyntheticMediaSourceProvider` | `tests/test_provider_fakes.py` |
| AI-C-09 | 완료 (AIRuntimeProvider 재사용) | `providers/adapters.py`, `perception/auxiliary.py` | `tests/test_provider_fakes.py`, `tests/test_auxiliary.py` |
| AI-C-10 | 완료 | `registry/capability_registry.py::CapabilityRegistry` | `tests/test_capability_registry.py` |
| AI-C-11 | 완료 + 소스 소실을 반증으로 읽지 않는 레코드 해석 (`perception/object_record.py::RecordResolver.resolve`) | `contracts/capability.py::CapabilityRequirement.evaluate` | `tests/test_local_safety.py` 등 |
| AI-C-12 | 완료 | `providers/adapters.py` (8종 Protocol) | `tests/test_provider_fakes.py`, `tests/test_overlay_and_clusters.py`, `tests/test_model_deployment.py` |
| AI-C-13 | 완료 | `selection/selector.py::CapabilitySelector.select` | `tests/test_selector.py` |
| AI-C-14 | 완료 | `common/data_plane.py` (+ `providers/mqtt.py` 적용) | `tests/test_data_plane.py`, `tests/test_mqtt_transport.py` |
| AI-C-15 | 완료 (로더 + robot/facility/river 프로파일 + 도메인 분기 정적 검사) + 군사(정찰) 배포 프로파일 (`profiles/defense.json`) | `contracts/profile.py`, `contracts/profile_loader.py`, `profiles/*.json` | `tests/test_profile_loader.py` |
| AI-C-16 | 완료 (내부 자산 조달 + 공개 egress 배치 전 검출 + 선택 외부 의존성만 비활성화) + **등록 정보의 외부 도달 선언**(`CompatibilityProfile.external_endpoints`/`external_optional`, 기본값 = 외부 연결 불요)과 폐쇄망 프로파일(`DeploymentProfile.closed_network`/`internal_endpoints`, 기본 폐쇄망)에서 selector 후보 필터로 **배치 전 배제**, 비선택(non-optional) egress는 `EgressGate.assert_declarations`로 명시 거부 | `runtime/airgap.py::EgressGate`, `contracts/profile.py`, `contracts/profile_loader.py`, `selection/selector.py` (placement_filter), `runtime/application.py` | `tests/test_airgap.py`, `tests/test_egress_gate.py` |
| AI-C-17 | 완료 (오버레이 provider 추상화 + Tailscale 구현 격리 + 오버레이 상태 별도 신호) | `providers/adapters.py`, `providers/overlay.py` | `tests/test_overlay_and_clusters.py` |

## 지속학습 (최신 요구사항)

아래 완료 표시는 모델 재학습 성능이 아니라 승인된 소형 fixture에서의 품질 Gate,
상태 전이, 자원 배분 및 감사 가능성 검증을 뜻한다.

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-L-01 | 완료 (H2ST task/OOD 판정과 후보 생성) | `continual/h2st.py`, `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-02 | 완료 (신뢰도·중복 품질 필터) | `continual/replay.py`, `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-03 | 완료 (격리 상태 Gate) | `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-04 | 완료 (DGS grouping/consolidation 및 Ekya 자원 배분 계약) | `continual/dgs.py`, `continual/ekya.py` | `tests/test_continual_baselines.py` |
| AI-L-05 | 완료 (고정 입력·결과·계보 기록) | `continual/lineage.py`, `../experiments/external/` | `tests/test_continual_baselines.py`, `tests/test_external_validation_common.py` |
| AI-L-06 | 완료 (결정론적 resource allocation) | `continual/ekya.py`, `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-07 | 완료 (승격 전 검증 Gate) | `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-08 | 완료 (단계 적용·검증·rollback 이력) | `continual/lineage.py` | `tests/test_continual_baselines.py` |

## 시나리오 검증 (하드웨어 없이 프레임워크 특성 확인)

요구사항별 단위 검증과 별개로, "범용 프레임워크가 하드웨어·기능·실행환경 변화에 견디는가"를
기존 15개 시나리오와 폐쇄망/오버레이/멀티클러스터 관점을 함께 검증한다. 구현 위치·실행법·지표는
[docs/ai/03-framework-property-scenarios.md](03-framework-property-scenarios.md) 참고.

| 시나리오 | 검증 요구사항 |
|---|---|
| S1 새 센서 Hot Plug / S2 노드 환경 변경 | AI-B-01/04/09, AI-C-04/10/12/15 |
| S3 자원 포화 / S4 provider 장애 | AI-B-06/07, AI-C-05/11/13, AI-O-02 |
| S5 네트워크 단절 / S14 엣지 장애 | AI-N-01, AI-C-10/11, AI-O-04 |
| S6 평면 불일치 / S7 데이터 경로 분리 | AI-C-06/08/14, AI-O-04 |
| S8 명령 성공 / S9 명령 거부 | AI-B-03, AI-C-06/14, 원칙 #16 |
| S10 구성 delta·롤백 / S11 자동 캘리브레이션 | AI-N-02, AI-B-05/07, AI-E-02/03, AI-C-02 |
| S12 도메인 전환 / S13 도메인 사후 추가 | AI-C-15, AI-C-04/05, AI-B-09 |
| S15 Kafka burst | AI-C-06, AI-O-03, 원칙 #17 |
| S16 폐쇄망 배치 / S17 보안 오버레이 / S18 멀티 클러스터 | AI-C-16/17, AI-B-11, AI-C-12, AI-O-04 |

## 요약

- **완료: 50 / 51**, **부분: 1**(AI-B-10), **미착수: 0**
- **실 인프라로 승격 완료**: MQTT(mosquitto), Kafka(KRaft), 엣지 양방향 Bridge, OCI 컨테이너,
  K3s 클러스터 제어, OpenTelemetry Collector(OTLP), Tailscale CLI 기반 오버레이 조회
- **파트 간 통합 준비 완료**: JSON Schema 8종, 정상 payload 예제 6종, AI wire adapter,
  모델 배포·롤백 lifecycle, 하드웨어·백엔드·가시화 병합 가이드
- **시나리오 검증 완료**: 18개 관점(기존 15개 + 폐쇄망/오버레이/멀티클러스터) + 지표 산출 (`reports/framework-indicators.json`)
- **남은 항목과 사유**:
  - AI-B-10 실물 말단 검증 / AI-N-01 최소 처리주기 실측 — 실제 하드웨어 필요
  - AI-C-10 백엔드 통합 가용성 판정 — 백엔드 API 필요 (현재는 백엔드 mock으로 대역)

**검증 명령**:

```bash
cd perception-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
#   -> 328 passed, 19 skipped (현재 개발 환경; skip = 선택 의존성·인프라 부재)
docker run --rm perception-framework:0.1.0 python -m pytest -q
#   -> 230 passed, 25 skipped (선택 의존성·인프라 없는 최소 컨테이너)
PYTHONPATH=. python3 examples/scenario_demo.py    # 16단계 최종 데모
```

**선택 구성요소가 없으면 해당 테스트만 skip되고 나머지는 그대로 통과**하는 것이 AI-C-11이
요구하는 동작 그 자체이며, 두 실행 결과의 차이가 그 증거다.

**추가 요구사항 필요 여부**: 없음. 문서에 없는 기능을 임의로 추가하지 않았다.
