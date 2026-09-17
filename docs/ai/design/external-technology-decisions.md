# 외부 기술·프로토콜·Capability 계약 결정

상태: 결정 및 저장소 적용 기록.
구현 상태는 [requirement-traceability](../requirement-traceability.md)를 함께 확인한다.
근거: `reports/2026-09-01_2122_물리제어명령_프로토콜_조사.md`(1차 조사), 백엔드 `데이터 전송
아키텍처 정리 v8`(구간별 전송 확정), 2026-09-02 외부 기술 전체 정리(등급 분류).

이 문서는 이전에 `docs/ai/05-external-technology-contracts.md`, `docs/obsidian/
protocol-contract-reference.md`, `docs/obsidian/capability-contract-technology-selection.md`
세 파일로 나뉘어 있던 것을 하나로 병합했다(2026-09 정리) — 세 문서가 다른 시점에 같은 주제
(외부 기술·프로토콜·Capability 계약 결정)를 썼기 때문에 겹치는 내용이 많았다.

## 0. 배경

mk1(`fleet_mission-dashboard`)은 Redis LIST/HASH/PubSub로 물리 명령을 다뤘다. Redis 자료구조가
command semantics 역할까지 겸해 전달 보장(Pub/Sub는 at-most-once), 상태 이력(HASH는 최신값만),
identity·idempotency, deadline, E-stop과 cancel의 구분이 모두 계약 없이 임시로 처리됐다. 이
문서는 두 가지를 분리한다: **전송(transport)**은 이미 백엔드가 구간별로 확정했으므로 AI 파트가
재설계·재비교하지 않고(§2), **의미 계약(semantic contract)**만 AI 파트가 정의한다(§3, §4).

## 1. 4단계 분류

새 외부 기술을 검토할 때는 항상 이 표의 등급부터 정한다.

| 등급 | 의미 | 코드에서의 위치 |
|---|---|---|
| A. Core Contract | 프레임워크가 직접 소유하는 의미 규약 | `contracts/`, 이 저장소가 정의 |
| B. Canonical Binding | 의미 계약을 표현하는 데 의도적으로 고정한 직렬화 형식 | Protobuf/JSON |
| C. Deployment Technology | 현재 배포가 쓰는 구체 기술. provider 뒤에 숨김 | `providers/*.py` |
| D. Semantic Reference | 설계 원칙만 차용하고 런타임 의존성은 만들지 않는 외부 표준 | 코드에 없음, 설계 근거로만 인용 |

```text
[외부 표준의 검증된 설계 원칙]
 ROS Action   AIP-155   W3C WoT   VDA 5050   KubeEdge
      \          |         |          |          /
       └───────── 설계 근거만 사용 (D) ──────────┘
                         ↓
             Project Semantic Contract (A)
                         ↓
                Protobuf Binding (B)
                         ↓
        ┌─────────────────────────┐
        │   현재 Deployment (C)   │
        │ MQTT / Kafka / OTLP     │
        │ OCI / K3s / Tailscale   │
        └─────────────────────────┘
                         ↓
                  Robot Adapter → Vendor SDK
```

매번 새 기술을 검토할 때는 "이건 (1) 의미 계약인가 (2) serialization인가 (3) transport인가
(4) runtime/deployment인가 (5) 설계 참고일 뿐인가"부터 판정한다. 핵심 원칙: **MQTT와 Kafka는
Command Contract가 아니다.** `command_id`, `ACCEPTED`, `CANCELED` 같은 의미를 MQTT topic 이름이나
Kafka header 자체에 종속시키지 않는다.

## 2. 구간별 확정 전송 계층 (백엔드 확정 — 재평가 대상 아님)

| 구간/기능 | 기술 | 등급 | 관련 요구사항 | 구현/공식 출처 |
|---|---|---|---|---|
| 말단↔엣지 업무·명령·heartbeat | MQTT 5.0 (Paho, Mosquitto) | C | AI-C-06 | `providers/mqtt.py`; [OASIS MQTT 5.0](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html), [Eclipse Paho](https://eclipse.dev/paho/clients/python/), [Mosquitto](https://mosquitto.org/documentation/) |
| 엣지↔서버 업무·명령 | Apache Kafka | C | AI-C-06 | `providers/kafka.py`; [Kafka Docs](https://kafka.apache.org/documentation/) |
| MQTT↔Kafka 브릿지 | 엣지 양방향 Bridge | C | AI-C-06 | `edge/bridge.py` |
| 서버→엣지 명령 경로 | Kafka → 브릿지 → MQTT (A안 확정) | C | AI-B-03, AI-C-06 | `execution/command_execution.py`, `edge/bridge.py` |
| 관측(metric/log/trace) | OpenTelemetry OTLP | C | AI-O-01/02 | `providers/otel.py`; [OTLP Spec](https://opentelemetry.io/docs/specs/otlp/) |
| metric 엣지→서버 | Prometheus Federation(요약만) | C | AI-O-01 | 백엔드 소유; [Prometheus Federation](https://prometheus.io/docs/prometheus/latest/federation/) |
| 장애 알림 통합 | Prometheus Alertmanager | C | AI-O-01 | [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) |
| trace 저장 | Grafana Tempo | C | AI-O-01 | [Tempo Docs](https://grafana.com/docs/tempo/latest/) |
| 장치 생사·치명 오류 | MQTT LWT/heartbeat + Prometheus up, 백엔드 단일 지점 통합 판정 | C | AI-O-04, AI-C-10 | AI는 통합 판정 결과를 소비만 함 |
| 영상(말단↔엣지) | RTP/UDP + JPEG | C | AI-C-08 | 백엔드/하드웨어 소유; [RFC 3550](https://www.rfc-editor.org/info/rfc3550/), [RFC 2435](https://www.rfc-editor.org/info/rfc2435/)(현재 구현이 실제로 준수하는지는 미확인) |
| 영상(엣지↔서버↔뷰어) | WebSocket + `frame_ref` | C | AI-C-08, `contracts/ai/frame-reference.schema.json` | 백엔드 소유; [RFC 6455](https://www.rfc-editor.org/info/rfc6455/). `frame_ref` 자체는 WebSocket 표준이 아니라 프로젝트 자체 계약 |
| 업무 감사 기록 | MySQL (command_id 기준 책임·결과 저장) | C | AI-B-03 | 백엔드 소유, AI는 ID만 전달; [MySQL 8.4 Reference](https://dev.mysql.com/doc/refman/8.4/en/) |
| 원격 구간 보안 | Tailscale overlay | C | AI-C-17 | `providers/overlay.py`; [Tailscale Docs](https://tailscale.com/docs) |
| 오케스트레이션(서버·엣지) | K3s (양쪽 클러스터, 공통 계약) | C | AI-B-05/11 | `providers/k3s.py`, `runtime/clusters.py`; [K3s Docs](https://docs.k3s.io/) |
| 명령 기술 추적 | OTel trace → Tempo | C | AI-O-01 | `providers/otel.py`; [OTel Traces](https://opentelemetry.io/docs/concepts/signals/traces/) |

이 표의 기술은 실험·대안 비교 대상이 아니다. 새 transport 후보(DDS, Zenoh, gRPC 등)를 "현재
프로젝트에 도입할지" 판단하는 문서가 별도로 없다면 이미 결정 완료로 간주한다.

## 3. AI 파트가 소유하는 물리 명령 의미 계약 (Core Contract, AI-C-20)

전송이 확정되어 있으므로, AI 파트가 실제로 정의할 것은 그 위에 얹는 의미 계약뿐이다.
전 구간 wire 규약은 [`interface-spec/spec/physical-command-interface.md`](../../../interface-spec/spec/physical-command-interface.md)를 따른다(엣지↔장치의 `terminal/<device-id>/{downlink,uplink}`).

| 구성 요소 | 역할 | 상태 |
|---|---|---|
| `Command` | 명령 발행 (command_id, correlation_id, target, action, parameters, deadline) | 구현 (`contracts/physical_command.py::Command`) |
| `CommandAcceptance` | 수락/거부 (accepted, rejection.code/message) | 구현 |
| `ExecutionStatus` enum | ACCEPTED / EXECUTING / CANCELING / SUCCEEDED / ABORTED / CANCELED | 구현 |
| `CommandStatus` | (선택) 비종료 상태의 중간 보고 | 구현 |
| `CommandResult` | 종료 상태·결과·실패 원인 (terminal state만 허용, `__post_init__`에서 검증) | 구현 |
| `CancelCommandRequest/Response` | 취소 요청과 수락(정지 완료 아님) — cancel-vs-완료 경쟁 시 CANCELING이 우선 | 구현 |
| `Capability` | name/version/parameter_schema/result_schema/cancel_supported/required_resources | 구현. `compatibility_profile()`로 AI-B-01 배치 태그에 연결 |
| `CommandExecutionSupervisor` | 동일 프로세스 내 동기 handler 가정 — dedupe, deadline, 비동기 실행·취소, SQLite 상태 복구 | 구현 (`execution/command_execution.py`) |
| `HardwareAdapterHandler` | `CommandExecutionSupervisor` ↔ 실제 장치 provider(capability 확인·execute·cancel) 경계 | 구현 (`execution/hardware_adapter.py`); 구체 로봇 SDK는 하드웨어 파트가 주입 |
| `PhysicalCommandGateway` | 네트워크 너머 장치가 비동기로 보내는 uplink 메시지로 명령별 상태를 추적, `Capability` 도착을 `CapabilityRegistry` 등록으로 연결 | 구현 (`execution/physical_command_gateway.py`) — `interface-spec`의 실제 엣지측 구현체 |

**상태 모델.** `REJECTED`는 `ExecutionStatus`에 없다 — `CommandAcceptance.accepted=false`로만
표현한다(ROS 2 Action 규칙). `CommandResult.__post_init__`이 non-terminal 상태로는 생성 자체가
안 되게 막고, `CommandAcceptance.__post_init__`이 accepted와 rejection의 상호 배타 조건을
강제한다.

**idempotency.** `payload_fingerprint()`(target/action/parameters만 해시, correlation_id·
deadline은 제외)로 구현했다. 동일 command_id+동일 payload는 재실행 없이 기존 acceptance를
반환하고, 동일 command_id+다른 payload는 `ALREADY_EXISTS`로 거부한다. Google AIP-155가 명시하는
"request ID의 주 목적은 idempotency guarantee와 safe retry"를 그대로 따른다 — 새 `idempotency_key`
필드는 추가하지 않고 `command_id`가 이미 이 역할을 한다. `google.api.*` Protobuf annotation 같은
Google API 전용 의존성은 쓰지 않는다.

**Canonical Binding: Protobuf.** `contracts/proto/physical_command.proto`(시스템 `protoc` 없이
`grpcio-tools`로 컴파일)와 `PhysicalCommandProtobufSerializerProvider`를 구현했다.
`physical_command` 경계의 기본 직렬화 정책은 이 binding이며, 기존 `JsonSerializerProvider`(AI-C-07)는
교체되지 않고 나란히 남아 있다(AI-C-11 선택 기능 격리 원칙) — physical command 채널만 이
Protobuf provider를 기본 binding으로 쓰고 다른 채널은 기존 JSON 그대로다. `protobuf`는
`pyproject.toml`의 core dependency다(mqtt/kafka/otel과 달리 선택 extra가 아니다 — Canonical
Binding은 의도적으로 고정하는 것이므로 이는 설계와 일치한다). JSON 교환용
`contracts/ai/physical-command.schema.json`도 동일 lifecycle 전체를 검증한다.

**범위.** `CommandExecutionSupervisor`는 `LocalControlSupervisor`(기능 시작/중지/재시작,
`execution/control.py`, AI-B-03)와 별개의 참조 구현이다. 이 계약은 action/target/parameters를
해석하지 않으므로 로봇 SDK나 도메인 분기를 포함하지 않는다 — 실제 물리 액추에이터 명령 생성은
여전히 AI-C-19에 따라 백엔드·하드웨어 파트 책임이다.

**E-stop / Cancel / SafeStop 분리.**

| 기능 | 의미 | 담당 |
|---|---|---|
| `CancelCommand` | 정상 업무 명령 취소 | 이 command protocol |
| `SafeStopRequest` | 시스템이 로봇에게 안전 상태 전이를 요청 | local safety + adapter |
| Emergency Stop | safety function | independent safety system |

`MQTT topic: /robot/estop` 하나만으로 E-stop safety function이 구현됐다고 주장하면 안 된다.
IEC 61508, 산업 AMR이면 ISO 3691-4, service robot이면 ISO 10218-1(scope 제한 있음, 자동 적용
금지)의 해당 여부는 로봇 종류·환경 위험평가로 별도 결정한다. 이 계약은 안전 기능을 대체하지
않는다.

**command_id와 trace_id 관계.** `command_id`(업무/물리 명령 identity, idempotency, 책임 추적 —
백엔드 발급, MySQL 감사 저장소)와 `trace_id`(실제 distributed execution path, 기술 지연·오류
분석 — OpenTelemetry → Tempo)는 합치지 않는다. 하나의 command는 retry나 bridge 처리 등으로
여러 span을 가질 수 있기 때문이다. 이 분리는 백엔드 `데이터 전송 아키텍처 정리 v8` §5-6/§5-7에도
동일하게 있다 — 이 계약이 새로 만드는 것이 아니라 기존 구조에 idempotency 의미를 얹는 것이다.

**설계 근거(D. Semantic Reference만 채택 — 런타임 의존성 없음).**

| 외부 표준 | 채택 | 채택하지 않는 부분 |
|---|---|---|
| [ROS 2 Action](https://design.ros2.org/articles/actions.html) | ACCEPTED/EXECUTING/CANCELING/SUCCEEDED/ABORTED/CANCELED 상태 의미, status/result 분리, rejected 분리 | Action Client/Server, `.action` IDL, rclpy/rclcpp, DDS/RMW |
| [Google AIP-155](https://google.aip.dev/155) | `command_id == request_id` 의미로 idempotency 판단 | `google.api.*` annotation |
| [W3C WoT Thing Description 1.1](https://www.w3.org/TR/wot-thing-description11/) | `ActionAffordance`의 input/output/idempotent/synchronous/invoke·query·cancel 분리 — Capability 필드 설계 근거 | JSON-LD, Forms, runtime. `safe`는 "internal state 불변"을 뜻하며 functional safety가 아니므로 안전 개념으로 차용하지 않음 |
| VDA 5050 factsheet | capability discovery 패턴(robot type을 machine-readable JSON으로) | wire protocol(order/node/edge/navigation model) 전체 — AMR fleet 특화 |
| [KubeEdge Mapper](https://kubeedge.io/docs/concept/device/mapper/) | `Robot ↕ Robot Adapter ↕ Common Command Contract ↕ MQTT` 구조의 선례 | 런타임(Device Controller/DeviceTwin/CRD) |

## 4. Capability·Provider 계약 계층

### 4.1 목적과 계층

AI 모델, 실행 환경, 센서·로봇 동작을 한 객체에 혼합하지 않고 **능력–구현–배포–현재 상태**로
분리한다. 외부 표준은 의미와 검증 방법의 근거로 사용하며, 표준을 참고했다는 이유만으로 해당
런타임이나 wire format을 도입하지 않는다.

```text
TaskIntent → RequiredCapability → Capability
                                  ↓ realizes
                              Implementation
                                  ↓ deployed as
                           ExecutionProfile
                                  ↓ instantiated by
                            RuntimeInstance
```

| 계약 | 책임 | 대표 필드 | 주 근거 |
|---|---|---|---|
| `Capability` | 구현 독립 의미와 제약 | kind, semantic I/O, properties, preconditions, limitations | IDTA Capability Description, ISO 22166 |
| `Implementation` | capability를 실현하는 provider/model artifact | provider_id, implementation_version, model_ref, artifact_digest | Capability/Skill reference model, IDTA Model Nameplate |
| `ExecutionProfile` | 고정 조건에서 측정한 실행 특성 | runtime, hardware, input profile, resources, latency, quality, evidence_ref | IDTA AI Deployment, MLModelScope, MLPerf |
| `RuntimeInstance` | 현재 배치와 가용성 | instance_id, deployment_ref, health, health_ttl, current_load | KServe V2 health/ready 패턴 |
| `TaskIntent` | 작업이 요구하는 능력과 hard constraint | required/optional capabilities, deadline, max_input_age, minimum_evidence, safety invariants | IDTA required/provided matching, TOSCA requirement/capability |

`PhysicalActionCapability`도 같은 `Capability` 의미 계층을 사용하되 실행 interface에는 W3C WoT
ActionAffordance의 `input`, `output`, `idempotent`, `synchronous` 및 invoke/query/cancel 분리를
참고한다. functional safety는 WoT의 `safe`가 아니라 별도 interlock·authorization·safety
invariant로 유지한다.

**이는 목표 계약이다** — 호환 schema와 migration이 끝나기 전에는 구현 완료로 간주하지 않는다.
현재 단일 타입의 기존 필드는 호환 입력으로 유지하고, 신규 다섯 계약과 reference ID로 단계적으로
이동한다. AAS/TOSCA/OWL-S/KServe package나 대형 benchmark dataset은 이 결정만으로 다운로드하지
않는다.

### 4.2 채택 범위

| 외부 기술 | 등급 | 채택 | 채택하지 않는 부분 |
|---|---|---|---|
| [IDTA Capability Description 1.0](../obsidian/papers/idta-capability-description.md) | D | capability/property/constraint/skill 및 required↔provided matching 의미 | AASX, AAS runtime, 산업 생산 ontology 강제 |
| [IDTA AI Model Nameplate 1.0](../obsidian/papers/idta-ai-model-nameplate.md) | D | model과 deployment 분리, model metadata 참조 | template field의 무비판적 복제 |
| [IDTA AI Deployment 1.0](../obsidian/papers/idta-ai-deployment.md) | D | HW/SW requirement, performance·monitoring·risk 정보의 책임 경계 | provider selector 또는 inference protocol로 사용 |
| [ISO 22166-201/-202](../obsidian/papers/iso-22166-201.md) | D | vendor-neutral module 정보와 software module 특성 분리의 상위 근거 | 유료 원문 미확보 세부 field·conformance 주장 |
| [Capability/Skill reference model](../obsidian/papers/capability-skill-reference-model.md) | D | capability와 executable implementation 분리 | 제조 domain class를 core에 강제 |
| [TOSCA 2.0](../obsidian/papers/tosca-2.md) | D | requirement/capability allocation과 constraint filtering 원리 | TOSCA DSL, CSAR, orchestrator runtime |
| [OWL-S 1.2](../obsidian/papers/owl-s.md) | D | profile/model/grounding 분리와 composition의 선행 근거 | ontology와 2004 runtime 전면 도입 |
| [KServe Open Inference Protocol V2](../obsidian/papers/kserve-open-inference-protocol-v2.md) | D/선택 C | tensor metadata와 live/ready/model-ready adapter | semantic capability·safety 계약으로 간주 |
| [MLModelScope](../obsidian/papers/mlmodelscope.md) / [MLPerf Inference](../obsidian/papers/mlperf-inference.md) | D | 조건 고정·재현 가능한 execution evidence 방법 | benchmark runtime을 core dependency로 사용, 다른 workload로 점수 일반화 |

### 4.3 Selector 불변조건

1. capability 의미가 맞지 않는 후보는 성능 점수가 높아도 선택하지 않는다.
2. deadline, node feature, resource, input age, safety invariant는 hard filter로 처리한다.
3. 측정값은 `model/artifact × runtime × hardware × input profile × dataset/manifest`가 같은
   evidence만 사용하며 선언 성능과 구분한다.
4. health가 없거나 TTL이 만료된 runtime instance는 과거 benchmark가 있어도 선택하지 않는다.
5. required capability를 만족하지 못할 때 optional 기능만으로 성공 처리하지 않는다. 허용된
   degraded mode가 없다면 명시적으로 unavailable/fail-safe를 반환한다.

## 5. 전체 외부 기술 목록

| 기술 | 등급 | Core dependency? | 관련 요구사항 |
|---|---|---|---|
| Protobuf | B | 예(물리 명령 계약 한정) | AI-C-01, AI-C-07 |
| JSON | B | 예(현재 전체 채널 기본) | AI-C-01, AI-C-07 |
| MQTT / Paho / Mosquitto | C | 아니오 (provider 뒤) | AI-C-06 |
| Kafka | C | 아니오 | AI-C-06 |
| OpenTelemetry/OTLP | C | 아니오 | AI-O-01/02 |
| Prometheus / Alertmanager | C | 아니오 | AI-O-01, AI-O-04 |
| Tempo | C | 아니오 | AI-O-01 |
| MySQL(백엔드 감사 저장소) | C | 아니오 (AI는 command_id만 전달) | AI-B-03 |
| RTP/UDP/JPEG, WebSocket | C | 아니오 | AI-C-08 |
| Tailscale | C | 아니오 | AI-C-17 |
| OCI Image/Runtime | C | 배포 profile만 | AI-B-02 |
| Docker | C | 아니오 (현재 image build 도구) | AI-B-02 |
| K3s | C | 아니오 | AI-B-05, AI-B-11 |
| Helm | C | 아니오, 선택 | AI-B-05 |
| Node Feature Discovery | C | 아니오, 선택 | AI-B-04 |
| Kubernetes Device Plugin | C | 아니오, 선택 | AI-B-04 |
| K8s RBAC/PSS/Secrets | C | 아니오, 선택 | (§6 참고) |
| ROS 2 Action | D | 아니오 — 설계 근거만 | AI-B-03, AI-C-20 |
| AIP-155 | D | 아니오 — 설계 근거만 | AI-B-03, AI-C-20 |
| W3C WoT | D | 아니오 — 설계 근거만 | AI-B-01, AI-C-18 |
| VDA 5050 | D | 아니오 — 참고만 | AI-B-01, AI-C-18 |
| KubeEdge | D | 아니오 — 참고만 | AI-C-04 |
| AsyncAPI | D | 아니오 — 선택 문서화 | — |
| CloudEvents | D | 아니오 — 현재 미채택 | AI-O-02 |
| gRPC | D | 아니오 — 오류 모델(status code)만 참고 | AI-B-03 |
| Sigstore Cosign | D | 아니오 — 선택 확장 | (§6 참고) |
| IDTA Capability Description | D | 아니오 — 의미 모델 | AI-C-18, AI-B-01 |
| IDTA AI Model Nameplate / AI Deployment | D | 아니오 — 책임 분리·metadata 근거 | AI-B-01, AI-B-04 |
| ISO 22166-201/-202 | D | 아니오 — 공개 범위의 상위 근거 | AI-B-01, AI-C-18 |
| Capability/Skill reference model | D | 아니오 — 설계 근거 | AI-C-18, AI-B-01 |
| TOSCA 2.0 / OWL-S | D | 아니오 — matching/composition 참고 | AI-C-13, AI-S-05 |
| KServe Open Inference Protocol V2 | D, 선택 C | 아니오 — adapter에서만 선택 | AI-B-08 |
| MLModelScope / MLPerf Inference | D | 아니오 — 측정 방법 참고 | AI-B-01 |
| pyjevsim (DEVS 시뮬레이션 엔진) | C | 아니오 — `simulator/`(테스트·데모 도구) 전용, `perception_framework` 패키지는 이 의존성을 모른다. `pyproject.toml`의 `sim` extra | 요구사항 소유 없음(검증 도구) |

## 6. 보안 경계 (4계층)

Tailscale 하나로 끝나지 않는다.

| 계층 | 현재/권고 기술 | 역할 |
|---|---|---|
| Network | Tailscale | remote edge↔server connectivity |
| Messaging | Mosquitto/Kafka authentication + ACL | 누가 command를 publish/consume 가능한가 |
| Workload | K8s ServiceAccount/RBAC/Pod Security Standards | 어떤 Pod가 어떤 API/device를 쓸 수 있는가 |
| Artifact | OCI digest, 향후 signature | 어떤 code/image가 실제 실행되는가 |

**Messaging.** Tailscale이 있다고 모든 MQTT client가 모든 command topic에 publish하도록
허용하면 안 된다. 예:
```text
robot/go1-01 adapter
subscribe: command/go1-01
publish:   acceptance/go1-01, status/go1-01, result/go1-01
다른 robot command: DENY
```
Mosquitto Dynamic Security plugin([문서](https://mosquitto.org/documentation/dynamic-security/))은
clients/groups/roles 기반 인증·인가를 제공하고, Kafka도 SSL/SASL authentication·TLS·authorization을
공식 지원한다([Kafka Security](https://kafka.apache.org/43/security/security-overview/)).

**Workload.** Kubernetes RBAC(`Role`/`ClusterRole`/`RoleBinding`)으로 API authorization을
제공한다. Robot Adapter가 불필요한 `cluster-admin` 권한을 갖지 않는다. Pod Security Standards의
`Restricted` 정책은 privileged container·불필요한 hostPath·privilege escalation을 제한한다 —
`privileged: true`, `hostPID: true`, `hostNetwork: true`, `hostPath: /`를 robot adapter 기본
설정으로 쓰지 않는다. Kubernetes Secret은 기본적으로 underlying datastore에 암호화되지 않을
수 있다고 공식 문서가 경고한다 — MQTT/Kafka credential, API key, Tailscale auth key는 container
image에 넣지 않는다.

**Artifact.** OCI Image의 content-addressable digest로 `image digest + configuration version +
contract version`을 연결해 실행을 감사한다. 향후 Sigstore Cosign으로 image signature를 추가할
수 있으나 현재는 선택 확장이다.

## 7. 적용 범위와 외부 운영 의존성

AI 저장소가 소유할 수 있는 클라이언트·배포 경계는 적용했다: MQTT 5 response topic/correlation/
expiry와 TLS·사용자 인증 입력, Kafka SASL/TLS 입력·`acks=all`·순서 보존 retry·처리 성공 뒤
consumer offset commit(중복 실행 방지는 전송 계층이 아니라 `command_id` 실행 계약에서 보장),
Bridge의 SQLite outbox와 순서 보존 재전송, K3s image digest 강제 옵션·service account/image
pull secret/container security context, capability 요구 자원의 `CompatibilityProfile` 변환.

다음 항목은 브로커·클러스터·장치 소유자가 설정하고 통합 환경에서 검증해야 하며, 이 저장소
코드만으로 완료 처리하지 않는다: MQTT/Kafka topic ACL 계정 발급, K8s RBAC/PSS 정책 생성·적용,
OCI 서명 검증(Cosign 키·정책·admission), 실 로봇 명령 검증(adapter 계약은 완성됐으나 구체 SDK
구현과 물리 안전 검증은 하드웨어 파트 소유).

## 8. 명시적으로 배제한 기술

| 기술 | 이유 |
|---|---|
| ROS 2 Action runtime, DDS, Zenoh | 전송은 §2에서 이미 MQTT/Kafka로 확정. 추가 middleware 불필요 |
| VDA 5050 wire protocol 전체 | AMR fleet/navigation 특화, 범용 physical capability에 부적합 |
| KubeEdge 런타임(EdgeCore/DeviceTwin CRD) | K3s + MQTT + 백엔드 조합과 기능 중복 |
| OPC UA Robotics 전체 stack | 산업 통합에는 강하나 저사양 edge adapter에 과도 |
| Sparkplug B | metric-centric IIoT 모델, command lifecycle 없음 |
| CloudEvents를 command envelope로 사용 | command_id/trace 분리가 이미 있어 추가 envelope 실익 부족. event 용도로만 향후 검토 |
| gRPC를 command transport로 사용 | MQTT/Kafka가 이미 확정. cancellation/status code 개념만 참고 |
| AAS/TOSCA/OWL-S runtime 전면 도입 | 의미 모델 근거에는 유용하지만 현재 JSON/Protobuf 계약과 K3s 배포에 중복 계층을 추가 |
| ISO 22166 field 복제 | 정식 유료 원문을 확보하지 않은 상태에서 공개 초록 밖의 schema를 추정할 수 없음 |
| KServe V2를 전체 capability 계약으로 사용 | tensor serving과 readiness는 다루지만 물리 의미·evidence·safety constraint는 다루지 않음 |

## 9. 공통 원칙 문장

새 외부 기술을 추가할 때 기준으로 삼는 문장(CLAUDE.md AI-C-04를 구체화):

> 외부 표준과 오픈소스 기술은 프로젝트의 공통 의미 계약, 현재 배포 구현, 또는 설계 참고 근거를
> 구분하여 사용해야 한다. ROS 2 Action, AIP-155, W3C WoT, VDA 5050, KubeEdge 등에서 차용한
> 상태·식별·capability·edge autonomy 개념은 해당 middleware, wire protocol, SDK, runtime의
> 사용을 요구하지 않아야 한다. 현재 배포에서 사용하는 MQTT, Kafka, OpenTelemetry, OCI, K3s
> 등의 구체 기술도 provider 또는 deployment profile 경계 안에 두고, 상위 AI·판단·물리 명령
> 의미 계약이 해당 기술의 API나 자료구조에 직접 의존하지 않아야 한다. Protobuf는 물리 명령
> 계약의 canonical serialization binding으로 사용하되, 의미 계약과 직렬화 규칙은 구분해서
> 관리한다.

## 10. 남은 합의 사항

1. `command_id` 발급 주체(현재 백엔드가 발급)와 MySQL 감사 스키마에 `deadline`/`capability`
   관련 필드를 얹을 수 있는지를 백엔드 파트와 확정해야 한다.
2. **부분 진행 (2026-09-09~10)**: §4의 5계층 목표 계약 dataclass(`Capability`/
   `Implementation`/`ExecutionProfile`/`RuntimeInstance`/`TaskIntent`)와 §4.3 불변조건 중
   순수 데이터 판정 부분(3/4/5)을 `contracts/capability_contract.py`로 구현했고(§12), 이어서
   `ProviderRegistration`에 `execution_profile`/`runtime_instance` 참조 필드를 추가하고
   `CapabilitySelector.select_for_intent()`로 실제 선택 알고리즘과 연결했다(§12) — provider가
   이 필드를 채우면 조건 불일치 evidence 재사용 방지(불변조건 3)와 TTL 만료 instance 배제
   (불변조건 4)가 selection 단계에서 실제로 적용된다. 아직 남은 것: §3의
   `physical_command.Capability`를 이 계약으로 이관하는 일 — `idempotent`/`cancel_supported`
   같은 action 고유 필드가 이 계층 어디에 속하는지 아직 정하지 않아 손실 없는 변환을 만들
   수 없으므로 보류한다. `contracts/profile.py::CompatibilityProfile`과의 관계는 이번
   `select_for_intent`가 `CompatibilityProfile.is_compatible()`을 그대로 재사용하는 방식으로
   당장은 "나란히 공존" 상태를 유지한다(중복 판정 로직을 새로 만들지 않음).
3. §6의 메시징/워크로드 권한 모델은 소유 요구사항 ID가 없으므로, 백엔드·하드웨어 파트와 조율
   후 "추가 요구사항 필요" 여부를 결정한다.
4. AsyncAPI 문서화는 후보 비교가 아니라 §2에서 확정된 MQTT/Kafka+브릿지 경로 하나만 기술하는
   것으로 범위를 좁혀 작성한다(선택, 필요 시점에).
5. **부분 진행 (2026-09-09)**: AI-S-07(`perception/purpose_requirements.py`)과 AI-S-08
   (`perception/environment_prior.py`)을 완료했다. §11에서 D grade로만 기록하고 아직 코드에
   반영하지 않은 나머지(AI-O-02 Evidently식 drift 필드, AI-L-01/02 Model Card/Datasheet
   구조화, AI-L-08 DVC식 lineage_ref, MLPerf 시나리오 태그, AI-S-06 Evidence의 PROV-O
   provenance 확장)를 다음 우선순위로 구현 착수한다.

## 11. 그 외 대분류별 설계 근거 (2026-09-09 조사)

§2~§9는 물리 명령·capability 계층만 다룬다. 아래는 나머지 대분류(안전·말단운용/인지·추적·
융합/목적기반 근거·사전정보/판단·위험/실행·자원 보강/관측·운영/학습·MLOps/좌표·시간 규약
보강)에서 찾은 업계 표준 설계 근거다. 전부 D(Semantic Reference) 등급 — 런타임 의존성을
추가하지 않는다. "반영"란이 "완료"인 것만 코드에 실제 적용됐고, 나머지는 §10-5의 후속 작업
대상이다.

### 11.1 안전·말단운용 (AI-N-01/02/03)

| 표준 | 반영 |
|---|---|
| ISO 3691-4 / ANSI-RIA R15.08(AMR 안전 — protective/warning field, safety-rated stop) | `reference/local_safety.py`의 CLEAR/CAUTION/STOP 계층 설계 근거로 인용(코드 변경 없음 — 원문 유료라 2차 자료로만 확인) |
| OMA LwM2M Firmware Update Object(Idle/Downloading/Downloaded/Updating + Update Result 코드 + 실패 시 자동 롤백) | `ondevice/config_apply.py`의 버전 적용·last-known-good 롤백 설계 근거 |
| 3GPP Event A3 handover(hysteresis + Time-to-Trigger) | `ondevice/link_handover.py`의 이력 기반 판단 설계 근거 |

### 11.2 인지·추적·융합 (AI-E-01/02, AI-S-01/02/03/04/06)

| 표준 | 반영 |
|---|---|
| MOTChallenge 포맷(MOTA/IDF1, `bb_left/top/width/height`+`conf`) | `perception/tracking.py` 필드명·평가지표 설계 근거 |
| OpenCV `calibrateCamera`(Zhang's method) | `edge/calibration.py`가 이미 이 방법을 wrapping — 사실상 채택 확인 |
| COCO JSON 어노테이션 포맷 | `perception/object_record.py::Evidence`의 region/label 표현 근거 |
| SAE J2735 SDSM(속성별 개별 confidence, 단일 스칼라로 합치지 않음) | `object_record.py`가 이미 evidence별 confidence를 병합하지 않는 설계와 일치 확인 |

### 11.3 목적기반 근거·사전정보 (AI-S-05/07/08)

| 표준 | 반영 |
|---|---|
| JDL Data Fusion Model(Level 0~5, 목적별 요구 정보 수준 계층화) | AI-S-07 "목적별 요구 근거 정의" 설계 틀로 채택, `perception/purpose_requirements.py`(`PurposeRequirement`/`evaluate_gap`) — **완료**(§12) |
| W3C PROV-O/PROV-DM(Entity/Activity/Agent, `wasGeneratedBy`/`wasDerivedFrom`/`wasRevisionOf`) | AI-S-08 `PriorInfoRecord.revision_of`(`PriorInfoStore.revise`)로 반영 — **완료**(§12). AI-S-06 Evidence provenance 쪽은 아직 미반영 |
| CCIR/PIR + NATO STANAG 4559 IRM&CM(requirement→tasking→collection→evaluation 루프) | AI-S-05는 이미 `decision/info_request.py`로 완료돼 있고 이 표준은 그 구조(부족 식별→후보 선택→요청→미해결 명시)와 일치함을 확인만 함 — 코드 변경 없음 |
| ISO 19115 lineage/quality 모델(source/scope/valid_from·to/version) | AI-S-08 `PriorInfoRecord`(source/scope/created_at/updated_at/version/valid_from/valid_until/available) — **완료**(§12) |

### 11.4 판단·위험 (AI-R-01/02)

| 표준 | 반영 |
|---|---|
| NWS 홍수경보 4단계(Watch→Advisory→Warning→Emergency, hysteresis 해제) | `risk/fsm.py` 상태 설계가 이미 부합 — docstring 인용 권장(코드 변경 불필요) |
| CAP(OASIS, severity/certainty/urgency 분리 + `<instruction>`) | `risk/output.py`의 `evidence_sufficiency`↔certainty, `recommendation`↔instruction 대응 문서화 권장 |
| ISO 31000/31010 | 위험 점수식을 표준 taxonomy가 아니라 프레임워크 자체 값으로 유지하는 근거(표준 자체가 점수식을 강제하지 않음을 확인) |

### 11.5 실행·자원 보강 (AI-B-01/04/08 — §4.2의 MLModelScope/MLPerf 채택에 추가)

| 표준 | 반영 |
|---|---|
| MLPerf Inference LoadGen 4 시나리오(SingleStream/MultiStream/Server/Offline) | `contracts/profile.py::CompatibilityProfile`에 시나리오 태그 추가 검토 — 미착수 |
| ONNX Runtime Execution Provider 패턴 | `providers/adapters.py::AIRuntimeProvider`가 이미 이 패턴(가속기 은닉, 미설치 시 자동 축소)을 따름 — 사실상 채택 확인 |
| K8s Device Plugin + NFD 라벨링(`requiredDuringScheduling`/`preferredDuringScheduling`) | `CompatibilityProfile.required_hw_tags`/`preferred_hw_tags` 명명이 이미 이 관례와 일치 확인 |

### 11.6 관측·운영 (AI-O-01/02/03 — 백엔드 OTel/Prometheus/Grafana/Kafka 채택과 별개, AI 관리 오버헤드 특화)

| 표준 | 반영 |
|---|---|
| OTel GenAI Semantic Conventions | 모델 호출 자체의 latency/token만 표준화 — "관리 계층 자체 오버헤드"는 이 범위 밖. K8s controller-manager/Istio의 "관리 계층도 워크로드와 동일 스키마로 자기 계측" 관행 참고 필요 — 미착수 |
| Evidently AI 드리프트 방법론(K-S test/Wasserstein/Chi-Square + `drift_share`) | AI-O-02 이상 사건에 `metric_name`/`score`/`threshold`/`method` 필드 추가 검토 — 미착수 |
| MLflow Tracking(run↔params/metrics/artifact) | `observability/reproduction.py`의 참조 구조 설계 근거 |

### 11.7 학습·MLOps (AI-L-01~08)

| 표준 | 반영 |
|---|---|
| MLflow Model Registry 4-stage(2.9부터 deprecated) | `continual/lineage.py`의 10-state 머신이 단순 4-stage보다 적절하다는 근거로 채택 — 표준을 그대로 복제하지 않는 근거로 인용 |
| Model Cards / Datasheets for Datasets | `LineageEvent.evidence_ref`(현재 자유문자열) 구조화 검토 — 미착수 |
| Kayenta(Netflix/Google canary, Mann-Whitney U test 기반 baseline-vs-candidate) | `continual/dgs.py`에 `forgetting_max` 회귀 게이트로 반영 **완료**(§12) |
| NIST AI RMF 1.0(Govern/Map/Measure/Manage) | AI-L-06 승인 정보 구조 설계 근거 |
| DVC(`dvc.yaml` DAG + lock 파일) | `continual/ekya.py::MicroProfile`에 `lineage_ref` 추가 검토 — 미착수 |

### 11.8 좌표·시간 규약 보강 (AI-C-02/03)

| 표준 | 반영 |
|---|---|
| ROS REP-103/105(body vs camera optical axis convention, `odom` vs `map`) | `common/coordinates.py::SpatialValue`에 `unit`/`axis_convention` 필드 추가, `is_comparable_with()`가 불일치를 감지 — **완료**(§12) |
| OGC SensorThings API — `phenomenonTime` vs `resultTime` | `common/timing.py::DerivedResult`에 `produced_at` 필드 추가로 관측시각/생산시각 분리 — **완료**(§12) |

## 12. 2026-09-09 코드 반영 요약

이번 세션에서 실제로 코드·테스트에 반영한 것:

| 변경 | 파일 | 근거 | 테스트 |
|---|---|---|---|
| `SpatialValue.unit`/`axis_convention` 추가, `is_comparable_with()`가 불일치 감지(양쪽 다 명시된 경우만 — 미명시는 기존처럼 comparable 유지) | `common/coordinates.py` | REP-103 §11.8 | `tests/test_coordinates.py` |
| `DerivedResult.produced_at` 추가(관측시각과 분리) | `common/timing.py` | OGC O&M phenomenonTime/resultTime §11.8 | `tests/test_timing.py` |
| `DynamicTaskGrouper.forgetting_max`(옵션, 기본 비활성) — 병합 전 기존 그룹 대비 상태 이동량이 임계값을 넘으면 병합 대신 격리 | `continual/dgs.py` | Kayenta canary §11.7 | `tests/test_continual_baselines.py` |
| `Capability`/`Implementation`/`ExecutionProfile`/`RuntimeInstance`/`TaskIntent` 5계층 목표 계약(§4) dataclass + §4.3 불변조건 3/4/5의 순수 함수 구현 | `contracts/capability_contract.py`(신규) | §4.2 IDTA/ISO22166/TOSCA/KServe/MLPerf(재조사 없이 기존 채택 그대로 사용) | `tests/test_capability_contract.py` |
| `PurposeRequirement`/`PurposeRequirementRegistry`/`evaluate_gap` — 목적별 required/preferred 필드 계약 + gap 평가(AI-S-07, 미착수였던 요구사항 완료) | `perception/purpose_requirements.py`(신규) | JDL Data Fusion Model §11.3 | `tests/test_purpose_requirements.py` |
| `PriorInfoRecord`/`PriorInfoStore` — 출처/범위/버전/유효기간/사용가능여부 + `revise`(재작성 아닌 버전 연결) + `report_conflict`/`needs_reevaluation`(AI-S-08 완료) | `perception/environment_prior.py`(신규) | ISO 19115, W3C PROV-O §11.3 | `tests/test_environment_prior.py` |
| `decision/info_request.py` docstring의 폐기된 "implements: AI-D-03"을 현재 요구사항 ID(AI-S-05)로 정정(코드 로직 변경 없음 — AI-D 계열은 이미 삭제·이관됐고 실질 기능만 AI-S-05로 흡수된 상태였음) | `decision/info_request.py` | — | 기존 `tests/test_info_request.py` 그대로 통과 |
| `ProviderRegistration`에 `execution_profile`/`runtime_instance` 참조 필드 추가(둘 다 기본 `None`) + `CapabilitySelector.select_for_intent()` 신규 — `TaskIntent`의 deadline/input-age hard filter, 그리고 후보에 `ExecutionProfile`/`RuntimeInstance`가 붙어 있을 때만 §4.3 불변조건 3/4를 추가 적용. 기존 `select()`/`select_with_degrade()`는 내부 후보 정렬 로직을 `_ranked_candidates()`로 추출만 하고 동작·반환값 불변 | `registry/capability_registry.py`, `selection/selector.py` | §4.3 (capability_contract.py와 동일 근거) | `tests/test_selector.py` |

전부 기존 필드에 옵션 필드를 추가하거나 신규 모듈을 나란히 추가하는 방식이라 기존 동작을
바꾸지 않는다 — 전체 회귀 스위트 **663 passed, 15 skipped**(세션 시작 시점 626 passed, 15
skipped)로 확인했다.
