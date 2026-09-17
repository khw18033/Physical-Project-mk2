# Physical AI 기반 분산 인지·디지털 트윈 프레임워크 전체 설계

## 1. 문서 목적

본 문서는 여러 고정 카메라와 이동형 카메라를 이용하여 물리 환경을 지속적으로 인지하고, 고정 카메라만으로 해결되지 않는 미확인 객체·사각지대·추가 업무 요구를 이동형 에이전트가 필요할 때만 보완하도록 하는 분산 인지 프레임워크의 전체 설계를 정리한다.

설계의 핵심은 특정 카메라, 센서, AI 모델, 하드웨어, 런타임, 전송 기술에 종속되지 않는 범용 구조를 유지하면서도, 저사양 온디바이스에서는 외부 엣지·서버의 가용성과 무관하게 최소 인지 기능이 항상 유지되도록 하는 것이다.

고정 카메라는 상시 감시 인프라이고, 드론·사족보행 로봇 등 이동형 카메라는 상시 구성요소가 아니라 이벤트 또는 Task에 의해 호출되는 Active Perception 자원이다.

---

## 2. 핵심 아이디어

전체 시스템은 다음 네 축을 결합한다.

1. **Always-on Passive Perception**
   - 고정 카메라와 Raspberry Pi 5급 저사양 온디바이스에서 항상 동작하는 경량 Known/Unknown 인지
   - 외부 네트워크와 서버 없이도 최소 인지 유지

2. **Asynchronous Multi-view Fusion**
   - 서로 다른 viewpoint의 고정 카메라 결과를 엣지에서 시간·공간적으로 정렬
   - 동일 객체를 지속 객체 단위로 통합
   - 서로 가려진 영역과 부분 관측을 보완

3. **Task-triggered Active Perception**
   - 고정 카메라 fusion 이후에도 남는 미확인 객체, 사각지대, 부족한 속성, 특정 업무 요구가 있을 때만 이동형 카메라 출동
   - 필요한 정보 종류에 적합한 Capability를 가진 에이전트 또는 Provider 선택

4. **Persistent Evidence-based Digital Twin**
   - 모델의 단일 출력이 아니라 여러 관측과 여러 Provider가 생성한 Evidence를 지속 객체에 누적
   - 객체 상태가 점진적으로 완성된 뒤 백엔드에서 authoritative Digital Twin state로 반영
   - 반복 미확인 객체, OOD, 사용자 확인 정보는 지속학습 후보로 연결

핵심 개념은 다음과 같이 요약한다.

`Viewpoint Diversity + Capability Diversity + Persistent Evidence + Resource-Aware Execution`

---

## 3. 전체 아키텍처

```text
PHYSICAL ENVIRONMENT
        │
        ▼
┌─────────────────────────────────────────────┐
│ Fixed Camera Nodes                          │
│ Raspberry Pi 5급 경량 온디바이스             │
│                                             │
│ Camera                                      │
│   ↓                                         │
│ Calibration Profile 적용                    │
│   ↓                                         │
│ Always-on Known/Unknown Perception          │
│   ↓                                         │
│ Local Tracking                              │
│   ↓                                         │
│ Observation / Local Evidence                │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│ Zone Edge Node                              │
│                                             │
│ Observation 수신                            │
│   ↓                                         │
│ Temporal Alignment                          │
│   ↓                                         │
│ Spatial Alignment                           │
│   ↓                                         │
│ Cross-view Association                      │
│   ↓                                         │
│ Multi-view Fusion                           │
│   ↓                                         │
│ Zone Persistent Object / Scene State        │
│   ↓                                         │
│ Evidence Sufficiency Check                  │
└──────────────────────┬──────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
     Evidence 충분             Evidence 부족 / Task
          │                         │
          │                         ▼
          │               Missing Information
          │                         │
          │                         ▼
          │               Required Capability
          │                         │
          │                         ▼
          │                 Task Generation
          │                         │
          │        ┌────────────────┼────────────────┐
          │        │                │                │
          │   On-device        Mobile Agent       Edge/Server
          │   Provider         Robot/Drone        Provider
          │        │                │                │
          │        └────────────────┼────────────────┘
          │                         ▼
          │                    New Evidence
          │                         │
          └─────────────────────────┘
                       │
                       ▼
                Persistent Object Update
                       │
                       ▼
┌─────────────────────────────────────────────┐
│ Backend / Digital Twin                      │
│                                             │
│ Global Coordinate Transform                 │
│ Authoritative Object State                  │
│ DT History / Prior                          │
│ Task / Command Coordination                 │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│ Server / Learning                           │
│                                             │
│ Learning Candidate                          │
│   ↓                                         │
│ Validation / User Confirmation              │
│   ↓                                         │
│ Continual Learning                          │
│   ↓                                         │
│ Regression / Forgetting Test                │
│   ↓                                         │
│ Model Registry                              │
│   ↓                                         │
│ Approval / Canary / Rollback                │
└─────────────────────────────────────────────┘
```

---

## 4. 계층별 책임

### 4.1 온디바이스

대상 예시는 Raspberry Pi 5와 같은 저사양 연산 장치이다.

#### 필수 역할
- 카메라 입력
- 검증된 Calibration Profile 적용
- 항상 실행되는 Known/Unknown 인지
- 경량 Local Tracking
- Observation 생성
- Local Evidence 생성
- 엣지 연결이 없어도 최소 인지 유지
- 이동형 로봇에서는 로컬 안전 판단 지원

#### 선택 역할
- 경량 Zero-shot / Open-vocabulary 인지
- 색, 형태, OCR 등 일부 특화 Provider
- Task가 주어졌을 때 추가 정보 생성
- 네트워크 상태가 나쁠 때 추가 로컬 처리

#### 기본적으로 두지 않는 기능
- 중앙 메시지 Broker
- 전체 Observability Collector
- 중앙 Database
- 중앙 Orchestrator
- 대형 VLM/LLM
- 전체 Digital Twin authoritative state

### 4.2 엣지 노드

한 구역의 여러 카메라와 이동형 에이전트 결과를 합치는 핵심 Perception Coordinator이다.

#### 주요 역할
- 여러 고정 카메라 Observation 수신
- Timestamp 기반 Temporal Alignment
- 좌표계 변환 및 Spatial Alignment
- Cross-view Object Association
- Multi-view Fusion
- Zone-level Persistent Object 관리
- Evidence Sufficiency 판단
- Missing Information 식별
- Capability 탐색
- Active Perception Task 생성
- 이동형 에이전트 및 추가 Provider 결과 수신
- Evidence Fusion
- 실행 자원·지연 상태 관측
- Provider 실행 정책 수행

엣지는 단순 inference 서버가 아니라 **해당 구역에서 어떤 객체가 존재하며, 무엇이 확인되었고, 무엇이 아직 확인되지 않았는지를 관리하는 지역 인지 조정 계층**이다.

### 4.3 서버

#### 주요 역할
- 고비용 AI Provider
- Continual Learning
- Training Dataset 관리
- Model Validation
- Regression / Forgetting Test
- Model Registry
- Model Version 관리
- 배포 승인
- Shadow / Canary / Rollback
- 장기 이력과 학습 Lineage 관리

서버가 없어져도 온디바이스의 기본 Known/Unknown 인지는 유지되어야 한다.

### 4.4 백엔드 / Digital Twin

#### AI가 담당
- 인지
- 추적
- 객체 Evidence
- Object Hypothesis
- 추가 정보 필요성
- Capability 선택
- 학습 후보
- 학습 및 검증 결과

#### 백엔드가 담당
- 장치의 authoritative availability
- 전역 좌표 변환
- 최종 Digital Twin object state
- 물리 Task 및 Command coordination
- 장치 선택과 실제 제어
- 장기적인 DT history

`AI Object Hypothesis != Authoritative DT State`

---

## 5. 고정 카메라 상시 인지

### 5.1 기본 구조

```text
Camera
  ↓
Calibration Profile
  ↓
Always-on Known/Unknown Perception
  ↓
Local Tracking
  ↓
Observation / Local Evidence
```

고정 카메라는 항상 동작하며 외부 엣지·서버 연결 여부와 무관하게 최소 인지를 유지한다.

### 5.2 상시 모델의 우선 목적

상시 모델은 다음 질문에 먼저 답한다.

1. 객체가 존재하는가
2. 학습된 Known인가
3. 학습되지 않은 Unknown인가
4. 시간에 따라 같은 객체인가

기본적으로 필요한 의미 정보 예시는 다음과 같다.

- local object/track identity
- bounding box 또는 관측 위치
- known/unknown state
- known class if available
- confidence
- capture timestamp
- camera identity
- calibration reference

구체 변수명은 공통 데이터 사전 확정 후 통일한다.

---

## 6. OSOD와 Zero-shot 역할 분리

### 6.1 Always-on 기본 인지

상시 기본 기능은 **Explicit Known/Unknown Detection Capability**이다.

현재 연구 후보:
- Sato & Law의 YOLO11n 기반 OSOD
- YOLO-UniOW-S
- 기타 경량 explicit-unknown detector

요구사항에는 특정 알고리즘명이 아니라 Known/Unknown Detection Capability를 적는다.

### 6.2 Zero-shot / Open-vocabulary

Zero-shot은 기본 상시 기능이 아니라 선택 Provider로 둔다.

사용 사례:
- Unknown의 semantic 후보 생성
- 특정 Task vocabulary 검색
- 사용자 요청 객체 검색
- Known class vocabulary 확장

### 6.3 계층 구조

```text
Tier 0
Always-on Known/Unknown Detection

Tier 1
Task-triggered Local Specialist
- Zero-shot
- Color
- Shape
- OCR
- Depth
- Segmentation

Tier 2
Edge / Server Specialist
- Large OVD
- VLM / MLLM
- Complex Geometry
- High-cost Semantic Analysis
```

Tier 1과 Tier 2가 없어도 Tier 0은 계속 동작한다.

---

## 7. Local Track과 Zone Persistent Object

### Local Track

단일 카메라에서 시간에 따라 유지되는 객체 상태이다.

```text
Camera A
frame 1 → local_track_5
frame 2 → local_track_5
frame 3 → local_track_5
```

### Zone Persistent Object

엣지에서 여러 카메라의 Local Track을 같은 물리 객체로 통합한다.

```text
Camera A local_track_5 ─┐
Camera B local_track_2 ─┼→ zone_object_17
Camera C local_track_8 ─┘
```

이 Zone Persistent Object가 Evidence 누적과 이후 Active Perception의 기준 단위가 된다.

---

## 8. Observation, Evidence, Object 분리

### Observation
특정 카메라 또는 센서가 특정 시각에 직접 관측한 결과.

### Evidence
Observation 또는 추가 Provider가 생성한 개별 근거.

예:
- detection evidence
- objectness evidence
- known/unknown evidence
- color evidence
- shape evidence
- material evidence
- OCR evidence
- depth evidence
- motion evidence
- segmentation evidence
- semantic evidence
- infrastructure prior
- user confirmation

### Persistent Object

```text
Zone Object #17
├ observations
├ tracks
├ class hypothesis
├ attributes
├ geometry
├ evidence provenance
├ confidence / uncertainty
├ lifecycle
└ missing evidence
```

모델 출력 하나를 Digital Twin 객체로 직접 간주하지 않는다.

---

## 9. 비동기 Multi-view Fusion

각 카메라는 촬영, 추론, queue, 전송 지연이 다르므로 결과 도착 순서대로 단순 fusion하면 안 된다.

### 필요한 시간 의미
- capture timestamp
- processing start
- completion timestamp
- edge receive timestamp
- camera identity
- camera pose 또는 extrinsic

### 비교할 보정 수준

#### B0
도착 순서 기반 단순 fusion

#### B1
Timestamp Window

#### B2
Tracking 기반 현재 시점 propagation

`x(tf) = x(ti) + v(tf-ti)`

#### B3
Feature-level asynchronous compensation

연구 후보:
- CoBEVFlow
- LRCP
- BEVSync
- TraF-Align
- CATNet

### 핵심 연구 질문

**저비용 Object-level Temporal Compensation만으로 충분한지, 또는 Feature-level Compensation의 추가 비용을 감수할 만큼 실질적인 성능 향상이 있는지 비교한다.**

---

## 10. Spatial Alignment

필요한 경우 다음 좌표 변환 계층을 사용한다.

```text
Image Coordinate
  ↓
Camera Local Coordinate
  ↓
Zone Coordinate
  ↓
Backend Global Coordinate
```

AI는 전역 좌표를 authoritative하게 소유하지 않는다.

Calibration이나 3D 변환 기능이 없으면 image coordinate 기반 결과를 계속 유지한다.

---

## 11. Camera Calibration Lifecycle

Calibration은 매 frame 실행하지 않는다.

### Trigger
- 새 카메라 등록
- 해상도 변경
- crop 변경
- zoom 변경
- 장착 위치 변화
- calibration quality 저하
- 관리자 재보정 요청

### 흐름

```text
Calibration Trigger
      ↓
Calibration Provider
      ↓
Quality Validation
      ↓
Versioned Calibration Profile
      ↓
On-device / Edge 배포
```

새 Calibration이 실패하면 마지막 정상 Profile을 유지하며, 그것도 사용할 수 없으면 image coordinate 기반 인지를 유지한다.

후보:
- checkerboard / ChArUco
- AnyCalib
- GeoCalib
- DroidCalib
- 기타 self-calibration

---

## 12. 고정 카메라 Fusion 이후 상태

Passive Perception 이후 객체와 영역은 다음 상태를 가질 수 있다.

- Known Object
- Unknown Object
- Partially Observed Object
- Conflicting Object
- Blind Region
- Low-confidence Region

여기까지는 고정 인프라가 항상 수행한다.

---

## 13. Evidence Sufficiency

Model Confidence와 업무에 필요한 정보의 충분성을 분리한다.

`Model Confidence != Task Evidence Sufficiency`

예를 들어 Detector confidence가 높아도 자산 식별 Task에서 OCR이나 재질 정보가 없다면 Evidence는 부족할 수 있다.

### 판단 구조

```text
Task Required Evidence
         ↓
Current Object Evidence
         ↓
Missing Evidence
```

---

## 14. Active Perception Trigger

드론이나 사족보행 로봇은 평소 대기하고 다음 조건에서만 Task가 생성된다.

1. Persistent Unknown이 일정 조건 이상 유지
2. 고정 카메라가 볼 수 없는 Blind Region 존재
3. Object identification에 필요한 Evidence 부족
4. Evidence 간 충돌
5. 특정 업무 Task가 추가 관측 요구
6. 위험 분석이 추가 확인 요구
7. 관리자 요청

---

## 15. Passive Perception과 Active Perception

```text
Always-on Fixed Perception
          ↓
Zone Scene State
          ↓
Unknown / Blind Spot / Task
          ↓
Active Perception Task
          ↓
Mobile Agent
```

고정 카메라는 **Always-on Passive Perception**, 이동형 에이전트는 **Task-triggered Active Perception**으로 역할을 분리한다.

---

## 16. Capability-Specialized Mobile Agent

이동형 에이전트의 주요 연구 가설은 같은 모델을 여러 대에서 반복 실행하는 것보다 물리적 viewpoint와 서로 다른 AI Capability를 함께 활용하는 것이다.

예:

### 사족보행 로봇 A
- close range
- shape
- side geometry

### 사족보행 로봇 B
- color
- material
- OCR

### Drone
- top view
- large area coverage
- geometry
- high-place observation

### Edge GPU
- semantic open-vocabulary
- segmentation
- high-accuracy perception

### Server VLM
- semantic reasoning
- multimodal identification

---

## 17. 장치 이름이 아니라 Capability 기반 선택

상위 AI는 특정 장치를 직접 선택하지 않는다.

예:

```text
Required Capability
- top_view_geometry
- material
```

Registry가 현재 실행 가능한 후보를 반환하고 실행 정책이 후보를 선택한다.

이 구조는 새 로봇, 드론, 센서, 모델을 추가해도 상위 판단 로직을 유지하기 위한 것이다.

---

## 18. 이동형 Agent의 Capture-time Pose

이동형 카메라는 촬영 후 처리 시간 동안 pose가 계속 변한다.

따라서 Observation에는 반드시 **촬영 시점의 camera pose**가 연결되어야 한다.

`T_world_camera(t_capture)`

필요 의미:
- capture timestamp
- camera pose at capture
- agent identity
- local track identity

처리 완료 시점의 현재 pose를 과거 frame의 pose로 사용해서는 안 된다.

---

## 19. Evidence-specialized 역할 분담

### Homogeneous Baseline

```text
Robot A → same model
Robot B → same model
Drone   → same model
```

### Capability-specialized Candidate

```text
Robot A → shape evidence
Robot B → color evidence
Drone   → top-view geometry
Edge    → semantic evidence
Server  → high-cost semantic hypothesis
```

핵심 비교는 다음이다.

`Viewpoint Diversity`  
vs  
`Viewpoint Diversity + Capability Diversity`

---

## 20. Evidence Fusion

각 Provider의 결과를 바로 하나의 Label로 덮어쓰지 않고 개별 Evidence로 유지한다.

```text
Object #17

Evidence A
source = fixed_camera_A
type = known_unknown
value = unknown

Evidence B
source = robot_A
type = color
value = red

Evidence C
source = robot_B
type = shape
value = cylindrical

Evidence D
source = drone
type = top_geometry
value = circular

Evidence E
source = OCR
value = "ABC-12"

Evidence F
source = server_vlm
type = semantic_hypothesis
value = fire extinguisher
```

Resolver/Fusion은 이 Evidence를 이용해 Object Hypothesis를 갱신한다.

---

## 21. Infrastructure Prior

시설 DB, Digital Twin History, 과거 관측은 현재 센서 Observation과 분리한다.

Prior에는 최소한 다음 의미를 유지한다.

- source
- version
- created time
- updated time
- valid scope
- validity

실제 Observation과 충돌하는 Prior만으로 객체 상태를 확정하지 않는다.

---

## 22. Provider Abstraction

Provider는 모델 이름이 아니라 정보를 제공하는 기능 단위이다.

### Perception
- Known/Unknown Detector
- OVD
- Detector
- Segmenter
- Depth

### Attribute
- Color
- Shape
- Material
- Texture
- OCR

### Spatial
- Tracking
- ReID
- Calibration
- Geometry
- SLAM

### Semantic
- CLIP
- VLM
- MLLM
- Retrieval

### External
- DT History
- Facility DB
- Inventory
- External AI Service

---

## 23. Provider Configuration

같은 Provider라도 실행 조건이 바뀌면 별도 Configuration으로 관리한다.

`ProviderConfiguration = Capability × Model × Runtime × Hardware × Input × ExecutionLocation`

예:
- color + model_v1 + NCNN + Pi5 + 320×320 + on-device
- semantic + model_v3 + CUDA + RTX GPU + crop + edge

각 조합은 별도 실측 프로파일을 갖는다.

---

## 24. Resource-aware Execution

Provider 선택에는 실제 품질과 실행 비용을 사용한다.

측정 후보:
- accuracy
- unknown recall
- latency
- p95 latency
- throughput
- CPU
- GPU
- RAM
- temperature
- queue delay
- network bytes
- failure rate
- external call cost

### 연구 후보
- ApproxDet
- DACC
- nn-Meter
- OCTOPINF

### 비교
- Static Profile
- Content-aware Profile
- Content + Resource-aware Profile

---

## 25. Graceful Degradation

선택 기능이 없어졌다고 전체 시스템이 중단되지 않는다.

```text
FULL
 ↓
DEGRADED
 ↓
MINIMAL
 ↓
SAFE FALLBACK
```

예:

### VLM unavailable
- Known/Unknown 유지
- Tracking 유지
- Semantic enrichment만 비활성화

### Edge unavailable
- 온디바이스 Known/Unknown 유지
- Local Tracking 유지
- Local Evidence 유지

### 영상 자체 unavailable
- 영상 기반 기능 비활성화
- 이동형 로봇은 보수적 안전 상태 사용

---

## 26. Digital Twin Update

AI가 생성하는 것은 다음과 같은 후보 상태이다.

- local object state
- object hypothesis
- evidence
- uncertainty
- provenance

백엔드는 이를 이용해:
- global position
- global identity
- authoritative state
- DT history

를 관리한다.

---

## 27. Continual Learning

다음 사건을 학습 후보로 연결할 수 있다.

- 반복 Unknown
- OOD
- 사용자 수정
- 반복 오분류
- Domain Shift
- 성능 저하

### 흐름

```text
Operational Evidence
      ↓
Learning Candidate
      ↓
Isolation / Quarantine
      ↓
User or Validation
      ↓
Training
      ↓
New Model Candidate
      ↓
New-domain Evaluation
      ↓
Old-domain Regression Test
      ↓
Latency / Resource Test
      ↓
Approval
      ↓
Shadow / Canary
      ↓
Deploy or Rollback
```

VLM suggestion, model hypothesis, user-confirmed label, validated label, training data를 서로 구분한다.

---

## 28. 지속학습 연구 후보

### 학습 후보 탐지
- confidence filtering
- persistent unknown
- H2ST OOD

### Incremental Learning
- DGS
- RGR-IOD

### Training / Inference Resource Scheduling
- Ekya

---

## 29. 센서 및 장치 구성

### 최소 고정 구성
- 고정 카메라
- Raspberry Pi 5급 온디바이스
- 네트워크
- Zone Edge Node

### 이동형 구성
- 사족보행 로봇 또는 드론
- 카메라
- 온디바이스 연산 장치
- 위치/pose 정보

### 선택 센서
- IMU
- LiDAR
- ToF
- RGB-D
- 열화상
- 환경 센서
- 기타 Domain Sensor

선택 센서는 Capability를 추가하지만 프레임워크 필수조건으로 두지 않는다.

---

## 30. 카메라 구성

### 이동형 또는 저비용 실험 후보
- Raspberry Pi Camera Module 3 Wide
- Raspberry Pi Global Shutter Camera
- Raspberry Pi HQ Camera

### 고정 시설 카메라 권장 조건
- IP Camera
- RTSP
- ONVIF Profile T
- PoE

상위 AI에서는 모두 Media Source로 추상화한다.

---

## 31. Media Source Abstraction

```text
Pi Camera
→ LocalCameraAdapter

IP CCTV
→ RTSP / ONVIF Adapter

Recorded Video
→ File Adapter

Robot Camera
→ Robot Media Adapter
```

영상 픽셀은 MQTT/Kafka/OTLP에 직접 싣지 않고 별도 Media Path를 사용한다.

---

## 32. 전송 경계

### 업무 데이터
예:
- object
- evidence
- task
- command
- state

현재 후보:
- MQTT
- Kafka

### Observability
- OpenTelemetry

### Media
- RTP
- RTSP
- GStreamer
- 필요 시 WebSocket relay

의미 규약과 전송 구현은 분리한다.

---

## 33. Observability

Inference뿐 아니라 Framework overhead도 측정한다.

측정 대상:
- inference latency
- queue delay
- provider selection time
- fusion time
- tracking time
- CPU
- GPU
- RAM
- temperature
- network
- drop
- timeout
- error

구현 후보:
- OpenTelemetry
- Prometheus Node Exporter
- NVIDIA DCGM Exporter
- Edge Metrics Manager

---

## 34. 기존 연구 활용 구조

### 고정 Edge Camera + Fusion
- Object-level 3D Semantic Mapping using a Network of Smart Edge Sensors
- External Camera-based Mobile Robot Pose Estimation for Collaborative Perception with Smart Edge Sensors

활용:
`local inference → evidence transmission → multi-view fusion`

### Fixed + Mobile Active Perception
- Distributed multi-target tracking and active perception with mobile camera networks

활용:
`fixed cameras → insufficient observation → mobile camera → better viewpoint → additional attribute`

직접 경쟁 Baseline으로 사용한다.

### Semantic/Metric Active Mapping
- Active Metric-Semantic Mapping by Multiple Aerial Robots

활용:
`map uncertainty → informative viewpoint → active exploration`

### Asynchronous Fusion
- CoBEVFlow
- LRCP
- BEVSync
- TraF-Align
- CATNet

### Unknown Detection
- Sato & Law YOLO11n OSOD
- FOMO
- OW-OVD
- PASS
- OW-CFA
- YOLO-UniOW

### Unknown Semantic Enrichment
- Sato & Law
- Multi-LLM Attribute-aware OVD 계열

### Runtime Selection
- ApproxDet
- DACC
- nn-Meter
- OCTOPINF

### Continual Learning
- DGS
- H2ST
- RGR-IOD
- Ekya

---

## 35. 논문에서 직접 증명할 핵심 아이디어

모든 아키텍처 요소를 연구 기여로 주장하지 않는다.

### 35.1 Multi-view Fixed Perception

질문:

**단일 고정 카메라 대비 여러 고정 카메라의 비동기 fusion이 Unknown Recall과 Scene Coverage를 실제로 개선하는가?**

비교:
- Single Fixed
- Multi Fixed
- Multi Fixed + Temporal Compensation

### 35.2 Homogeneous vs Capability-specialized Active Perception

핵심 연구 후보이다.

비교:

```text
Homogeneous
Robot A → same model
Robot B → same model
Drone   → same model
```

```text
Capability-specialized
Robot A → shape
Robot B → color
Drone   → geometry
Edge    → semantic
```

질문:

**동일하거나 유사한 자원에서 Capability-specialized Evidence Acquisition이 Homogeneous Active Perception보다 Unknown Resolution과 자원 효율에서 유리한가?**

### 35.3 All-agent vs Selective Dispatch

비교:
- 모든 이동형 Agent 출동
- Missing Evidence에 필요한 Agent만 선택

측정:
- dispatch count
- travel distance
- total inference
- network traffic
- unresolved unknown
- final identification accuracy

### 35.4 Frame-level vs Persistent-object-level Provider Execution

비교:
- 매 frame Provider 실행
- Persistent Object에 이미 확보된 Evidence 재사용

측정:
- Provider calls
- latency
- compute
- network
- final quality

### 35.5 Static vs Context-aware Provider Selection

비교:
- Static measured profile
- content-aware
- content + resource-aware

측정:
- prediction error
- p95 latency
- SLO violation
- selection regret
- final quality

---

## 36. 핵심 실험 단계

### B0
Single Fixed Camera

### B1
Multi Fixed Cameras

### B2
Multi Fixed + Temporal Compensation

### B3
Fixed + Homogeneous Mobile Agents

### B4
Fixed + Capability-specialized Mobile Agents

### B5
Capability-specialized + Missing-evidence Selective Dispatch

### B6
B5 + Persistent Evidence Reuse

### B7
B6 + Resource-aware Provider Selection

각 단계에서는 가능한 한 한 요소만 추가하고 나머지 조건을 동일하게 유지한다.

---

## 37. 평가 지표

### OWOD / OSOD
- Known mAP
- U-Recall
- U-mAP
- Wilderness Impact
- Unknown false negative

### Tracking / Persistent Object
- Association Accuracy
- ID Switch
- Object duplication
- Object lifetime consistency

### Multi-view Fusion
- Cross-view association accuracy
- Duplicate object rate
- Spatial error
- Temporal alignment error

### Map / Scene
- Observed area
- Blind area reduction
- Scene coverage
- Object completeness

### Unknown Resolution
- Unresolved unknown rate
- Final identification accuracy
- Attribute accuracy
- Time-to-identification

### Active Perception
- Dispatch count
- Travel distance
- Observation count
- Task completion rate

### Resource
- FPS
- p50 latency
- p95 latency
- CPU
- GPU
- RAM
- temperature
- network bytes
- queue delay
- provider calls
- energy when measurable

### Continual Learning
- New-domain AP
- Old-domain AP
- Forgetting
- Training time
- GPU hours
- Selected training samples

---

## 38. 구현 우선순위

### Phase 0 — 기준선 동결
기존 캡스톤 결과는 비교 기준으로 보존한다.

### Phase 1 — Pi5 Always-on Known/Unknown
1. Sato YOLO11n OSOD 재현
2. 공개 dataset 성능 재현
3. Pi5 배포
4. runtime 비교
5. FPS / RAM / CPU / 온도 측정

Runtime 후보:
- PyTorch
- ONNX Runtime
- OpenVINO
- NCNN

### Phase 2 — Local Tracking
1. ByteTrack 등 경량 tracker 적용
2. Local Track 생성
3. Frame identity와 Track identity 분리
4. Local Evidence 생성

### Phase 3 — Multi Fixed Fusion
1. 여러 Pi5 camera node
2. 시간 동기화
3. calibration profile
4. cross-view association
5. zone persistent object
6. temporal alignment 비교

### Phase 4 — Unknown / Blind Task
1. unresolved unknown 판단
2. blind region 검출
3. task generation
4. task schema 정의

### Phase 5 — Mobile Active Perception
1. 사족보행 로봇
2. 드론 또는 다른 이동형 카메라
3. capture-time pose
4. evidence provider 실행
5. edge evidence fusion

### Phase 6 — Capability Specialization
1. color
2. shape
3. material
4. OCR
5. geometry
6. semantic

각 Provider에 대해 실측 품질·자원 Profile을 생성한다.

### Phase 7 — Resource-aware Selection
1. Static Profile
2. ApproxDet-style predictor
3. DACC-style content feature
4. nn-Meter latency predictor
5. 실제 resource telemetry 적용

### Phase 8 — Continual Learning
1. persistent unknown
2. OOD
3. learning candidate
4. user/validation
5. DGS/RGR baseline
6. regression test
7. model deployment

---

## 39. 설계 원칙

1. 특정 센서가 없다고 전체 시스템이 실패하지 않는다.
2. 특정 모델이 없다고 전체 인지가 실패하지 않는다.
3. 특정 하드웨어와 런타임을 상위 AI가 직접 참조하지 않는다.
4. 실제 Observation과 Prior를 구분한다.
5. Model Confidence와 Evidence Sufficiency를 구분한다.
6. Frame 결과와 Persistent Object를 구분한다.
7. AI 판단과 물리 제어 권한을 구분한다.
8. AI Object State와 authoritative DT state를 구분한다.
9. 상시 저비용 기능과 선택적 고비용 기능을 분리한다.
10. 새 기술은 기존 연구와 동일 조건 재현 후 비교한다.
11. 측정되지 않은 Model × Runtime × Hardware 조합의 성능을 다른 조합에서 임의 재사용하지 않는다.
12. 관리 정책 자체의 latency와 resource overhead도 측정한다.

---

## 40. 최종 시스템 정의

> 여러 고정 카메라가 Raspberry Pi 5급 경량 온디바이스에서 외부 엣지·서버와 관계없이 Known/Unknown 객체 인지를 항상 수행하고, 해당 구역 엣지 노드는 여러 viewpoint에서 비동기적으로 생성된 Observation을 시간·공간적으로 정렬하여 Persistent Object와 Scene State를 구성한다. 고정 카메라만으로 확인되지 않는 Persistent Unknown, Blind Region, 부족한 Evidence 또는 외부 Task가 발생하면 필요한 Capability를 식별하고 해당 Capability를 제공할 수 있는 이동형 로봇, 드론, 온디바이스, 엣지 또는 서버 Provider를 선택적으로 호출한다. 각 Provider가 생성한 색, 형태, 재질, OCR, Geometry, Semantic 등 서로 다른 Evidence를 동일 객체에 누적하여 객체 상태를 점진적으로 완성하고, 백엔드는 이를 전역 좌표와 기존 Digital Twin 정보에 통합하여 authoritative DT state를 관리한다. 반복 Unknown, OOD, 사용자 확인 및 성능 저하는 검증된 Continual Learning 흐름으로 연결한다.

---

## 41. 연구 핵심 문장

> 고정 카메라 기반 Always-on Lightweight Known/Unknown Perception이 기본 장면 상태를 유지하고, 미확인 객체나 사각지대에서 부족한 Evidence type에 따라 서로 다른 Capability에 특화된 이동형 Agent를 선택적으로 호출하여 비동기 Evidence를 Persistent Object에 통합했을 때, 기존 Homogeneous Active Perception 대비 Unknown Resolution과 Accuracy-Latency-Resource Trade-off가 개선되는지를 검증한다.

---

## 42. 최종 핵심 흐름

```text
Always-on Fixed Known/Unknown Perception
                    ↓
       Asynchronous Multi-view Fusion
                    ↓
       Zone Persistent Scene/Object
                    ↓
        Evidence Sufficiency Check
                    ↓
   Unknown / Blind Spot / External Task
                    ↓
          Required Capability
                    ↓
           Selective Dispatch
                    ↓
 Capability-Specialized Active Perception
                    ↓
             New Evidence
                    ↓
         Persistent Object Update
                    ↓
              Digital Twin
                    ↓
          Continual Learning
```
