# AI 요구사항 추적표 (담당: 진나영)

CLAUDE.md §7 규칙에 따라 요구사항 ID별 구현 위치·테스트·충족 여부를 기록한다.
**2026-09-02 갱신**: 요구사항 정의서가 Google Sheets `진나영` 탭(53개 요구사항)으로
갱신되어 이 표도 그 ID 체계로 전면 재구성했다. 이전 51개 체계 대비 변경:

- **삭제·이관**: AI-D-01/02/04(서브태스크 생성·검증)는 가시화 파트로 이관되어 코드·계약
  삭제(git 이력 참고). AI-D-03("추가 정보 요청")의 실질 기능은 AI-S-05로 흡수.
- **병합**: 구 AI-E-02(카메라 자동 캘리브레이션)+AI-E-03(보정 프로파일 생성·배포) → 신
  AI-E-02(카메라 보정 lifecycle). 구 AI-R-03(위험 판단 결과·권고 출력)+AI-R-04(관측·분석
  수준 조정 요청) → 신 AI-R-02 / AI-S-05로 흡수. 구 AI-B-07(장애 복구·롤백) → 신
  AI-B-05로 흡수. 구 AI-C-09(선택형 외부·고비용 기능 연동)/AI-C-12(인프라 제공자
  추상화)/AI-C-17(보안 오버레이) → 신 AI-C-04로 흡수. 구 AI-C-11(선택 기능·의존성
  격리) → 신 AI-C-05로 흡수. 구 AI-C-14(데이터 유형별 경로 분리) → 신 AI-C-06으로 흡수.
- **신규**: AI-N-03(링크 품질 기반 실행 전환), AI-S-06~08(이종 모델 결과의 점진적 객체
  레코드 구성 / 업무 목적별 요구 근거 정의 / 환경·사전정보 관리), AI-C-18(구성요소
  Capability 선언 규약), AI-C-19(AI 판단·권한·책임 경계), AI-C-20(물리 명령 의미 계약).
- **미확정 ID 정정**: 이전 버전의 "AI-E-05"(기준점 상대 추정, `perception/environment_map.py`)는
  구 51개·신 53개 어느 요구사항 정의서에도 존재하지 않는 ID였다. 내용상 가장 가까운
  신규 AI-S-08(환경·사전정보 관리)의 부분 구현 증거로 재배치했다 — 전체 계약(출처·유효
  범위·버전·관측과의 분리)까지 충족하는지는 미검증이라 "부분"으로 표시한다.
- **2026-09-04 추가 정정**: 같은 미확정 ID "AI-E-05"를 `perception/coverage.py`(구역 커버리지·
  사각지대)와 `simulation/digital_twin.py`의 관련 docstring 두 곳이 **환경 구조 추정과는 다른
  의미로** 별도로 인용하고 있었다. 내용(공간 구역 단위 근거 충분도)이 AI-S-03에 더 정확히
  대응해 AI-S-03으로 재배치했다 — `environment_map.py`(AI-S-08)와 `coverage.py`(AI-S-03)는
  같은 옛 ID를 썼지만 서로 다른 요구사항의 구현이었다는 뜻이다. `contracts/data_dictionary.py`의
  두 관련 주석도 함께 정정.

상태 값: **완료** = 요구사항이 정의한 동작·경계가 테스트로 보장됨 /
**부분** = 핵심 일부만 구현, 명시된 gap 있음 / **미착수**.

## 안전·말단운용

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-N-01 | 완료 (2026-09-08: 이동형 에이전트 온디바이스/엣지 재설계 — 의미 분류·추적을 edge로 옮기고 온디바이스는 class-agnostic proposal+distance/TTC만 유지하기로 함에 따라, `LocalSafetyJudge`가 배포별 `expected_optional_kinds`를 받도록 파라미터화. "설계상 없음"과 "장애로 없음"을 못 갈랐던 기존 gap을 해소 — `MOBILE_AGENT_OPTIONAL_KINDS`로 구성하면 video+distance만으로 FULL_AWARENESS 도달) | `reference/local_safety.py` | `tests/test_local_safety.py` |
| AI-N-02 | 완료 | `ondevice/config_apply.py` | `tests/test_config_apply.py` |
| AI-N-03 | 완료 (추세 예측 + 비대칭 이력 기반 축소·복귀) | `ondevice/link_handover.py` | `tests/test_link_handover.py` |

## 감시·인지

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-E-01 | 완료 | `perception/detection.py` (`PerceptionProvider`, `NullPerceptionProvider`, `BrightBlobDetector`) | `tests/test_detection.py` |
| AI-E-01 (고정 카메라 수직 슬라이스) | 완료 (2026-09-08 추가: 고정 카메라는 AI-N-01 "이동형 에이전트" 범위 밖이라 안전 판단 자체가 없음 — 상시 편도(one-way) 인지 결과 publish만 수행, edge로부터 받는 것 없이 동작. 보정/구성 갱신은 별도 저빈도 채널(`edge/calibration_profile.py`, `ondevice/config_apply.py`)) | `reference/fixed_camera_stream.py` | `tests/test_fixed_camera_stream.py` |
| AI-E-02 | 완료 (구 AI-E-02 자동보정 + 구 AI-E-03 보정 프로파일 생성·배포가 "카메라 보정 lifecycle" 한 요구사항으로 병합됨. 합성 데이터로 검증 — 실제 카메라/체커보드 없이 `cv2.calibrateCamera` 정확도 확인) | `edge/calibration.py`, `edge/calibration_profile.py` | `tests/test_calibration.py`, `tests/test_calibration_profile.py` |
| AI-E-04 | 완료 (+ 구 AI-C-09 "선택형 외부·고비용 기능 연동"의 AIRuntimeProvider 재사용 증거 흡수) | `perception/auxiliary.py`, `providers/adapters.py` | `tests/test_auxiliary.py`, `tests/test_provider_fakes.py` |
| AI-S-01 | 완료 (IOU 기반 reference tracker) + 이종 evidence의 지속 객체 레코드 (`perception/object_record.py`, `tests/test_object_record.py`) | `perception/tracking.py` | `tests/test_tracking.py` |
| AI-S-02 | 완료 | `perception/association.py` | `tests/test_association.py` |
| AI-S-03 | 완료 + 신뢰도와 근거 충분도 분리 보고 (`perception/object_record.py::ObjectRecord.evidence_sufficient`) + 구역 단위 커버리지·사각지대(원인 5종: NO_SOURCE/OCCLUDED/SOURCE_FAILURE/STALE/INCOMPLETE) — 객체 단위 근거 충분도의 공간적 대응 (2026-09-04: docstring이 인용하던 미확정 구 ID "AI-E-05"를 AI-S-03으로 정정) | `perception/uncertainty.py`, `perception/coverage.py` | `tests/test_uncertainty.py`, `tests/test_coverage.py` |
| AI-S-04 | 완료 + 명명 근거 없으면 unknown 유지 (`perception/object_record.py`) + (2026-09-04) FOMO/OW-OVD/OWOBJ 세 unknown-likelihood 정책을 실제 OWL-ViT raw score에 연결(`perception/unknownness.py`) — `object_record.py`/`unconfirmed.py`는 무수정, `Evidence.label=None`이면 투표에서 자동 제외되는 기존 경로만 사용. TAO 기반 방향성 검증 스크립트 완비(`research/fomo/`), 실행은 로컬 LLM(attribute 생성) 준비 후 | `perception/unconfirmed.py`, `perception/unknownness.py` | `tests/test_unconfirmed.py`, `tests/test_unknownness.py` |
| AI-S-05 | 완료 (+ 구 AI-D-03 "추가 정보 요청"과 구 AI-R-04 "관측·분석 수준 조정 요청"의 실질 기능 흡수) | `perception/info_selection.py`, `decision/info_request.py`, `risk/adjustment.py` | `tests/test_info_selection.py`, `tests/test_info_request.py`, `tests/test_risk_adjustment.py` |
| AI-S-06 | 완료 (이종 근거 점진적 객체 레코드 — 생성·활성·관측 소실·종료 lifecycle, 근거 provenance) | `perception/object_record.py` | `tests/test_object_record.py` |
| AI-S-07 | 완료 (2026-09-09: JDL Data Fusion Model 설계 근거로 목적별 required/preferred 필드 계약 + 현재 확보 필드 대비 gap 평가 구현. 동일 레코드가 목적마다 다른 충분도를 가질 수 있음을 `evaluate_all`로 보장) | `perception/purpose_requirements.py` | `tests/test_purpose_requirements.py` |
| AI-S-08 | 완료 (2026-09-09: 기준점 상대 추정(`environment_map.py`)에 더해 PROV-O `wasRevisionOf`/ISO 19115 lineage 설계 근거로 출처·대상범위·생성·갱신시점·버전·유효범위·사용가능여부를 갖춘 `PriorInfoRecord`/`PriorInfoStore` 신규 구현. `report_conflict`+`needs_reevaluation`으로 반복 불일치·노후 사전정보를 재평가 대상으로 식별. "confirm/promote" 메서드를 두지 않는 것 자체가 "사전정보만으로 확정 금지" 원칙의 구조적 보장) | `perception/environment_map.py`, `perception/environment_prior.py` | `tests/test_environment_map.py`, `tests/test_environment_prior.py` |

## 판단·위험

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-R-01 | 완료 | `risk/fsm.py` | `tests/test_risk_fsm.py` |
| AI-R-02 | 완료 (+ 구 AI-R-03 "위험 판단 결과·권고 출력"의 내부 결과·wire payload 검증 흡수) | `risk/scoring.py`, `risk/output.py`, `integration/wire.py`, `contracts/ai/risk-judgment.schema.json` | `tests/test_risk_scoring.py`, `tests/test_risk_output.py`, `tests/test_wire_integration.py`, `tests/test_integration_contract_schemas.py` |
| AI-R-02 (경로 후보 평가 확장) | 완료 (2026-09-08 추가: "AI가 경로 후보 평가까지는 관여" 결정 반영. 외부에서 온 경로 후보의 확률점을 기존 `RuleBasedRiskScorer`로 위험도·근거 충분도만 매기고, 후보 순위화·선택은 하지 않음 — AI-C-19 경계) | `risk/path_evaluation.py` | `tests/test_path_evaluation.py` |

## 실행·자원

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-B-01 | 완료 (호환성 프로파일. "검증" 필드 확장 — 미측정 항목 구분, 재측정 강제 — 은 아직 부분) | `contracts/profile.py` | `tests/test_selector.py` |
| AI-B-02 | 완료 (OCI 이미지 빌드 + 컨테이너 내 테스트 통과 실증; 오케스트레이터 없이도 동일 코드 실행) | `Dockerfile`, `execution/control.py`, `execution/lifecycle.py` | `tests/test_control.py`, `tests/test_lifecycle.py`, `docker run ... pytest` |
| AI-B-03 | 완료 (기능 lifecycle 제어 + AI-C-20 물리 명령 계약과의 경계 분리: 수락·실행·종료 분리, idempotency, 비동기 cancel 경쟁, SQLite 재시작 복구, 교체 가능한 하드웨어 adapter 경계) | `execution/control.py`, `providers/k3s.py`, `contracts/physical_command.py`, `execution/command_execution.py`, `execution/hardware_adapter.py` | `tests/test_control.py`, `tests/test_k3s_control.py`, `tests/test_physical_command_contract.py`, `tests/test_external_contract_application.py` |
| AI-B-04 | 완료 (preferred 태그가 선택 순위에 반영되며 배제는 하지 않음. 2026-09-17 P4: required 태그만 `aif.io/<tag>` nodeSelector 라벨로 변환하고 `resolve()` 결과를 `ControlProvider` start/stop으로 잇는 배치 마디 추가 — preferred는 라벨이 되지 않음) | `contracts/profile.py::CompatibilityProfile.preference_penalty`, `selection/selector.py`, `runtime/placement.py` | `tests/test_selector.py`, `tests/test_compute_providers.py`, `tests/test_placement.py` |
| AI-B-05 | 완료 (실행 상태기계 + **실 K3s 배포·기동·중지·상태조회** + 모델 다운로드·검증·활성화 lifecycle + 구 AI-B-07 "장애 복구·버전 롤백"의 health 격리·rollout undo 흡수) | `execution/lifecycle.py`, `providers/k3s.py::K3sControlProvider`, `runtime/model_deployment.py`, `registry/capability_registry.py` | `tests/test_lifecycle.py`, `tests/test_k3s_control.py`, `tests/test_model_deployment.py`, `tests/test_capability_registry.py` |
| AI-B-06 | 완료 | `selection/selector.py::CapabilitySelector.select_with_degrade` | `tests/test_selector.py`, `tests/test_risk_adjustment.py` |
| AI-B-08 | 완료 (스텁 + **실제 CPU/OpenCL 런타임 2종 교체 실증** + 모델 배포 provider 교체 계약, 벤더명 정적 검사) | `providers/adapters.py::{AIRuntimeProvider,ModelDeploymentProvider}`, `providers/compute.py` | `tests/test_provider_fakes.py`, `tests/test_compute_providers.py`, `tests/test_model_deployment.py` |
| AI-B-09 | 완료 (conformance 하네스. 2026-09-17 P3: 등록 정보 자체를 JSON manifest에서 읽는 로더 — provider 추가가 `config/providers*.json` 편집으로 끝남) | `execution/conformance.py`, `registry/manifest.py` | `tests/test_conformance.py`, `tests/test_provider_manifest.py` |
| AI-B-10 | 부분 (엣지에만 Bridge/K3s/Collector를 두는 배치를 코드·테스트로 표현; 실물 말단 하드웨어 검증은 미착수) | `edge/bridge.py`, `providers/k3s.py`(kubectl CLI만 사용) | `tests/test_kafka_bridge.py` |
| AI-B-11 | 완료 (서버·엣지 등 복수 실행영역이 동일 `ControlProvider` 계약 뒤에서 라우팅됨; "동일 오케스트레이터 강제 안 함" 문구는 provider 분리 구조로 이미 충족) | `runtime/clusters.py` | `tests/test_overlay_and_clusters.py` |

## 관측·운영

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-O-01 | 완료 (엣지 상세/요약 + **실 OTel Collector OTLP 수출 검증**) + 시연 실험 캡처 요약/개별 분리 (`observability/experiment.py`, `tests/test_experiment_capture.py`) + AI-S-06 실측 완료시각 기반 evidence 수집 세션 (`collection/session.py`, `collection/sampler.py`) | `observability/metrics.py`, `providers/otel.py::OtlpObservabilityProvider` | `tests/test_observability.py`, `tests/test_otel_observability.py`, `tests/test_collection_session.py` |
| AI-O-02 | 완료 (수집기 장애 시에도 로컬 사건 보존, metric 요약과 분리, `ai_failure`/`capability_status` wire 채널 분리 실증) + 캡처 장애 격리 (`observability/experiment.py`) | `observability/events.py`, `providers/otel.py`, `integration/wire.py` | `tests/test_observability.py`, `tests/test_otel_observability.py`, `tests/test_wire_integration.py` |
| AI-O-03 | 완료 (+ 실 Kafka offset 기반 단기 replay 참조) + 실행 조건·버전 포함 run bundle 재현 (`observability/experiment.py::ExperimentRecorder.bundle`) | `observability/reproduction.py`, `providers/kafka.py::ReplayReference` | `tests/test_observability.py`, `tests/test_kafka_bridge.py` |
| AI-O-04 | 완료 | `observability/availability.py` | `tests/test_observability.py` |

## 공통 아키텍처

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-C-01 | 완료 (공통 필드 의미·값 종류·생산자·소비자·데이터 평면 사전 + 언어 중립 JSON Schema + 임의 필드 검출) | `contracts/data_dictionary.py`, `../contracts/ai`, `integration/wire.py` | `tests/test_data_dictionary.py`, `tests/test_integration_contract_schemas.py`, `tests/test_wire_integration.py` |
| AI-C-02 | 완료 (2026-09-09: ROS REP-103 설계 근거로 `SpatialValue.unit`/`axis_convention` 추가 — 두 provider가 같은 frame·source_id를 쓰면서도 다른 축 관례를 쓰는 경우를 `is_comparable_with()`가 감지) | `common/coordinates.py` | `tests/test_coordinates.py` |
| AI-C-03 | 완료 (2026-09-09: OGC SensorThings phenomenonTime/resultTime 분리 근거로 `DerivedResult.produced_at` 추가 — 캡처시각과 결과생산시각을 구분) | `common/timing.py` | `tests/test_timing.py` |
| AI-C-04 | 완료 (Sensor/Media/Transport/Serializer/Runtime/Control/Observability Provider + 구 AI-C-12 "인프라 제공자 추상화"의 8종 Protocol, 구 AI-C-17 "보안 오버레이"의 Tailscale 격리를 Security/NetworkOverlay Provider로 흡수) | `providers/adapters.py`, `providers/fakes.py`, `providers/overlay.py` | `tests/test_provider_fakes.py`, `tests/test_overlay_and_clusters.py` |
| AI-C-05 | 완료 (핵심·선택 기능 declare + evaluate + 구 AI-C-11 "선택 기능·의존성 격리"의 소스 소실 반증 처리 흡수) | `contracts/capability.py`, `perception/object_record.py::RecordResolver.resolve` | `tests/test_local_safety.py` 등 |
| AI-C-06 | 완료 (MQTT 5 request/response 속성, Kafka 처리 후 commit, 엣지 양방향 Bridge SQLite outbox 포함; 실 Mosquitto·Kafka 양방향 검증 + 구 AI-C-14 "데이터 유형별 경로 분리" 흡수; `terminal/<device-id>/{downlink,uplink}` 물리 명령 wire round-trip을 실 브로커로 검증) | `providers/mqtt.py`, `providers/kafka.py`, `edge/bridge.py`, `common/data_plane.py`, `execution/physical_command_gateway.py`, `deploy/integration/docker-compose.yml` | `tests/test_mqtt_transport.py`, `tests/test_kafka_bridge.py`, `tests/test_data_plane.py`, `tests/test_external_contract_application.py`, `tests/test_physical_command_gateway.py` |
| AI-C-07 | 완료 (일반 JSON + 물리 명령 canonical Protobuf binding — `grpcio-tools`로 컴파일, 시스템 `protoc` 불필요) | `providers/fakes.py::JsonSerializerProvider`, `providers/serialization.py`, `providers/physical_command_protobuf.py`, `contracts/proto/physical_command.proto` | `tests/test_provider_fakes.py`, `tests/test_serialization_policy.py`, `tests/test_external_contract_application.py` |
| AI-C-08 | 완료 | `providers/fakes.py::SyntheticMediaSourceProvider` | `tests/test_provider_fakes.py` |
| AI-C-10 | 완료 (물리 명령 `Capability` 선언이 네트워크로 도착하면 `PhysicalCommandGateway`가 `ProviderRegistration`으로 변환해 local 레지스트리에 등록 — 최종 가용성 재판정 없이 등록만 담당, 장치 소실 시 unregister는 외부 판정을 받은 호출자가 트리거) | `registry/capability_registry.py::CapabilityRegistry`, `execution/physical_command_gateway.py` | `tests/test_capability_registry.py`, `tests/test_physical_command_gateway.py` |
| AI-C-13 | 완료 (2026-09-17 P1: `SelectionResult.alternatives`/`CapabilityResolution.alternatives`로 고려한 모든 후보와 탈락 사유를 노출 — 선택 방법 비교·화이트박스 설명 가능. P2: 사유 문자열은 `data_dictionary.STATE_CHANGE_REASONS` 통제 어휘) | `selection/selector.py::CapabilitySelector.select`, `runtime/application.py`, `contracts/data_dictionary.py` | `tests/test_selector.py`, `tests/test_application_alternatives.py`, `tests/test_data_dictionary.py` |
| AI-C-15 | 완료 (로더 + robot/facility/river/defense 도메인 프로파일 + 도메인 분기 정적 검사) — 도메인 프로파일은 `simulator/scenarios/domain-*.json`의 `profile` 필드로 옮겨져 시뮬레이터 시나리오와 함께 실행·검증된다(과거 `profiles/` 디렉터리 대체) | `contracts/profile.py`, `contracts/profile_loader.py`, `simulator/scenarios/domain-*.json` | `tests/test_profile_loader.py`, `tests/test_scenarios.py` |
| AI-C-16 | 완료 (내부 자산 조달 + 공개 egress 배치 전 검출 + 선택 외부 의존성만 비활성화, 폐쇄망 프로파일 한정 적용) + **등록 정보의 외부 도달 선언**(`CompatibilityProfile.external_endpoints`/`external_optional`)과 폐쇄망 프로파일(`DeploymentProfile.closed_network`/`internal_endpoints`)에서 selector 후보 필터로 **배치 전 배제**, 비선택(non-optional) egress는 `EgressGate.assert_declarations`로 명시 거부 | `runtime/airgap.py::EgressGate`, `contracts/profile.py`, `contracts/profile_loader.py`, `selection/selector.py` (placement_filter), `runtime/application.py` | `tests/test_airgap.py`, `tests/test_egress_gate.py` |
| AI-C-18 | 부분 (2026-09-09: 일반 구성요소로 확장된 5계층 목표 계약 — `Capability`/`Implementation`/`ExecutionProfile`/`RuntimeInstance`/`TaskIntent` — 을 `contracts/capability_contract.py`로 신규 구현. 2026-09-10: 이 계약을 `ProviderRegistration.execution_profile`/`runtime_instance` 참조 필드 + `CapabilitySelector.select_for_intent()`로 실제 선택 알고리즘에 연결 완료 — 조건 불일치 evidence 재사용 방지·TTL 만료 instance 배제가 selection 단계에서 동작함. 남은 gap: `physical_command.Capability`(idempotent/cancel_supported 등 action 고유 필드)를 이 계약으로 이관하는 작업만 남음 — 물리 명령 action 범위의 기존 구현은 변경 없음) | `contracts/physical_command.py::Capability`, `contracts/capability.py`, `contracts/capability_contract.py`, `registry/capability_registry.py`, `selection/selector.py` | `tests/test_physical_command_contract.py`, `tests/test_capability_contract.py`, `tests/test_selector.py` |
| AI-C-19 | 완료 (구조적 보장 — AI 코드 어디에도 로봇 SDK·액추에이터 API를 직접 호출하지 않음. `execution/hardware_adapter.py`가 실제 device provider를 외부 주입받는 경계로 명시. 네트워크 경계쪽도 동일 원칙: `PhysicalCommandGateway`는 `terminal/<device-id>/downlink`에 명령 바이트를 publish할 뿐 장치를 직접 제어하지 않음) | `execution/hardware_adapter.py`, `execution/physical_command_gateway.py`, `contracts/physical_command.py`(docstring 경계 선언) | `tests/test_physical_command_contract.py`, `tests/test_external_contract_application.py`, `tests/test_physical_command_gateway.py` |
| AI-C-20 | 완료 (Command/CommandAcceptance/ExecutionStatus/CommandResult/CommandStatus/CancelCommandRequest·Response/Capability, REJECTED는 별도 수락 결과로 분리, command_id idempotency, cancel-vs-완료 경쟁 처리. `interface-spec/spec/physical-command-interface.md`가 정의한 `terminal/<device-id>/{downlink,uplink}` wire 규약의 엣지측 구현 — `CommandExecutionSupervisor`는 동일 프로세스 내 동기 handler를 가정하는 반면 `PhysicalCommandGateway`는 네트워크 너머 장치가 비동기로 보내는 uplink 메시지로 명령별 상태를 추적하고(`wait_for_result`), `Capability` 도착을 `CapabilityRegistry` 등록으로 연결 — 실 Mosquitto 브로커 왕복까지 검증) | `contracts/physical_command.py`, `execution/command_execution.py`, `providers/physical_command_protobuf.py`, `execution/physical_command_gateway.py` | `tests/test_physical_command_contract.py`, `tests/test_physical_command_gateway.py` |

## 학습·MLOps

아래 완료 표시는 모델 재학습 성능이 아니라 승인된 소형 fixture에서의 품질 Gate,
상태 전이, 자원 배분 및 감사 가능성 검증을 뜻한다.

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-L-01 | 완료 (H2ST task/OOD 판정과 후보 생성) | `continual/h2st.py`, `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-02 | 완료 (신뢰도·중복 품질 필터) | `continual/replay.py`, `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-03 | 완료 (격리 상태 Gate) | `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-04 | 완료 (DGS grouping/consolidation 및 Ekya 자원 배분 계약) | `continual/dgs.py`, `continual/ekya.py` | `tests/test_continual_baselines.py` |
| AI-L-05 | 완료 (고정 입력·결과·계보 기록 + 2026-09-09: Kayenta canary 방식 근거로 `DynamicTaskGrouper.forgetting_max` 회귀 게이트 추가 — divergence만으로 병합 판단 시 기존 검증된 group의 adapter_state를 과도하게 흔드는 gap을 옵션 게이트로 닫음, 기본값은 비활성이라 기존 동작 불변) | `continual/lineage.py`, `continual/dgs.py`, `observability/validation_artifacts.py` | `tests/test_continual_baselines.py`, `tests/test_external_validation_common.py` |
| AI-L-06 | 완료 (결정론적 resource allocation) | `continual/ekya.py`, `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-07 | 완료 (승격 전 검증 Gate) | `continual/lineage.py` | `tests/test_continual_baselines.py` |
| AI-L-08 | 완료 (단계 적용·검증·rollback 이력) | `continual/lineage.py` | `tests/test_continual_baselines.py` |

## 시나리오 검증 (하드웨어 없이 프레임워크 특성 확인)

요구사항별 단위 검증과 별개로, "범용 프레임워크가 하드웨어·기능·실행환경 변화에 견디는가"를
기존 15개 시나리오와 폐쇄망/오버레이/멀티클러스터 관점을 함께 검증한다. 구현 위치·실행법·지표는
[docs/ai/validation/framework-property-scenarios.md](validation/framework-property-scenarios.md) 참고.
시나리오 자체는 신·구 ID 매핑과 무관하게 유효하므로 연관 ID만 새 체계로 갱신했다.

| 시나리오 | 검증 요구사항 |
|---|---|
| S1 새 센서 Hot Plug / S2 노드 환경 변경 | AI-B-01/04/09, AI-C-04/10/15/18 |
| S3 자원 포화 / S4 provider 장애 | AI-B-06/05, AI-C-05, AI-O-02 |
| S5 네트워크 단절 / S14 엣지 장애 | AI-N-01, AI-C-10/05, AI-O-04 |
| S6 평면 불일치 / S7 데이터 경로 분리 | AI-C-06/08, AI-O-04 |
| S8 명령 성공 / S9 명령 거부 | AI-B-03, AI-C-06/20 |
| S10 구성 delta·롤백 / S11 자동 캘리브레이션 | AI-N-02, AI-B-05, AI-E-02, AI-C-02 |
| S12 도메인 전환 / S13 도메인 사후 추가 | AI-C-15, AI-C-04/05, AI-B-09 |
| S15 Kafka burst | AI-C-06, AI-O-03, 원칙 #17 |
| S16 폐쇄망 배치 / S17 보안 오버레이 / S18 멀티 클러스터 | AI-C-16, AI-C-04, AI-B-11, AI-O-04 |

## 요약

- **완료: 51 / 53**(2026-09-09: AI-S-07/AI-S-08 신규 완료), **부분: 2**(AI-B-10, AI-C-18), **미착수: 0**
- **실 인프라로 승격 완료**: MQTT(mosquitto), Kafka(KRaft), 엣지 양방향 Bridge, OCI 컨테이너,
  K3s 클러스터 제어, OpenTelemetry Collector(OTLP), Tailscale CLI 기반 오버레이 조회,
  Protobuf(grpcio-tools 컴파일, 시스템 protoc 불필요)
- **파트 간 통합 준비 완료**: JSON Schema 8종, 정상 payload 예제 6종, AI wire adapter,
  모델 배포·롤백 lifecycle, 하드웨어·백엔드·가시화 병합 가이드
- **시나리오 검증 완료**: 18개 관점(기존 15개 + 폐쇄망/오버레이/멀티클러스터) + 지표 산출 (`reports/framework-indicators.json`)
- **남은 항목과 사유**:
  - AI-B-10 실물 말단 검증 / AI-N-01 최소 처리주기 실측 — 실제 하드웨어 필요
  - AI-C-10 백엔드 통합 가용성 판정 — 백엔드 API 필요 (현재는 백엔드 mock으로 대역)
  - AI-C-18 구성요소 Capability 선언 규약 — 5계층 목표 계약(`contracts/capability_contract.py`)과
    `selection/selector.py`·`registry/capability_registry.py` 연결은 2026-09-10 완료.
    `physical_command.Capability`(idempotent/cancel_supported 등)와의 이관 정리만 남음
    (`docs/ai/design/external-technology-decisions.md` §10-2)
  - (2026-09-09 해소) AI-S-07 업무 목적별 요구 근거 정의 — `perception/purpose_requirements.py`로 완료
  - (2026-09-09 해소) AI-S-08 환경·사전정보 관리 — `perception/environment_prior.py`로 완료

**검증 명령**:

```bash
cd perception-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
#   -> 663 passed, 15 skipped (2026-09-10 기준; skip = 선택 의존성·인프라 부재)
docker run --rm perception-framework:0.1.0 python -m pytest -q
PYTHONPATH=. python3 simulator/simulation.py      # 하드웨어 없이 프레임워크 성질 확인
```

**선택 구성요소가 없으면 해당 테스트만 skip되고 나머지는 그대로 통과**하는 것이 AI-C-05가
요구하는 동작 그 자체이며, 두 실행 결과의 차이가 그 증거다.

**추가 요구사항 필요 여부**: AI-C-18 미완성분은 요구사항 자체는 이미 정의되어 있으므로
"추가 요구사항 필요"가 아니라 "구현 필요"다(2026-09-09: AI-S-07/AI-S-08은 이번 갱신으로
완료 처리해 이 목록에서 제외). 새 요구사항 ID를 임의로 발명한 사례는 없는지 이번 갱신에서
재검토했다 — 이전에 근거 없이 쓰였던 "AI-E-05"는 AI-S-08 부분 구현으로 재배치했다(위 변경
요약 참고).
