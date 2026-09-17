# LOTUSim-Energy: A Maritime Simulator for Human-Drone Interaction in Autonomous Offshore Operation & Maintenance

## 메타데이터
- categories: 분산 서버-클라이언트 시뮬레이터 아키텍처, 다중 도메인(공중·수상·수중) 이동체 통합, Human-in-the-Loop 해양 로보틱스, 에너지 인지형 임무 계획
- domain: [[로보틱스·다중로봇]]
- source: Grosset, Juliette, Dubromel, Marie, Lechêne, Hélène, Arzel, Quentin, Buche, Cédric. "LOTUSim-Energy: A Maritime Simulator for Human-Drone Interaction in Autonomous Offshore Operation & Maintenance." arXiv preprint arXiv:2609.17124, 2026.
- url: https://arxiv.org/abs/2609.17124
- year: 2026
- authors: Juliette Grosset, Marie Dubromel, Hélène Lechêne, Quentin Arzel (CROSSING IRL 2010, Naval Group), Cédric Buche (CROSSING IRL 2010, CNRS, IMT Atlantique)

## 1. 핵심 요약
- 해상풍력 O&M(운영·유지보수)은 공중·수상·수중 세 영역에 걸친 이기종 로봇 협업과 사람의 감독을 함께 요구하지만, 기존 시뮬레이터는 한 영역(air/surface/subsea)에 특화돼 있거나 고정밀 렌더링·물리 중 하나만 강하고 둘 다 갖춘 것이 드물다.
- 논문은 *LOTUSim-Energy*를 제안한다 — Gazebo를 중앙 오케스트레이터로 두고 물리(LOTUSim-Xdyn)·에이전트 상호작용(ROS 2)·렌더링(Unity, 선택적)을 분리된 클라이언트 모듈로 두는 분산 서버-클라이언트 아키텍처다.
- 표층(바람 응력+Coriolis로 생기는 Ekman spiral) · 중층(무영향) · 저층(해저 지형 보정) 3단 정상상태 Ekman 모델로 해류를 계산하고, Airy 파동 이론으로 수면파를 모델링해 UAV/USV/AUV/ROV 모두에 물리적으로 일관된 환경 외력을 가한다.
- 배터리 상태(state-of-charge) 시뮬레이터, YOLO 기반 실시간 균열·부식 탐지 파이프라인, AIS(자동선박식별장치) 기반 궤적 추종, Desktop/VR 몰입형 HITL 인터페이스(Leap Motion 제스처 포함)를 실증 시나리오(모노파일+천이피스 다중 도메인 점검)로 통합 검증했다.

## 2. 문서 목적
- 해결하려는 문제: 해상풍력 O&M을 위한 자율 로봇 팀을 실해역에 투입하기 전에, 공중·수상·수중을 가로지르는 이기종 로봇 협업과 사람의 개입(HITL)을 현실적인 환경 물리(바람·파도·해류) 아래에서 함께 검증할 수 있는 시뮬레이터가 없다는 문제.
- 기술적 목표: (1) 통합 다중 도메인 물리 시뮬레이터, (2) 반복 가능한 O&M 임무 벤치마크 태스크 라이브러리, (3) 항법·추적·에너지 인지형 센싱을 포함하는 모듈형 자율성 스택 — 이 세 가지를 하나의 생태계로 제공하는 것.
- 다루는 범위: 아키텍처(물리/에이전트상호작용/렌더링 3클라이언트 분리), 환경 모델(표면 Xdyn 유체역학, 항력계수, Ekman 해류 3계층), 대표 O&M 태스크 목록(표 II), 배터리 플러그인, 실증 시나리오(경로추종·AIS 궤적추종·YOLO 시각탐지·HITL VR 인터페이스)의 시스템 수준 성능 검증.

## 3. 핵심 개념 상세

### 분산 서버-클라이언트 아키텍처(3-클라이언트 분리)
- 원문 표현: "The core simulation control module interfaces with three primary client modules: Physics: LOTUSim-Xdyn as the physics interface, Agent Interaction: ROS 2 for inter-agent messaging and hardware-in-the-loop bridges, Rendering: Unity as the optional high-fidelity renderer for human-robot interaction (HRI)."
- 정의: Gazebo가 결정론적 스텝 스케줄러로 자산(asset) 관리와 시뮬레이션 타이밍을 총괄하는 중앙 오케스트레이터 역할을 하고, 물리·에이전트 상호작용·렌더링 세 클라이언트는 각각 gRPC/WebSocket, ROS 2 DDS, (렌더링은 선택적) 별도 프로세스로 분리돼 있다.
- 역할: 물리 백엔드를 교체해도 코어 시뮬레이터를 바꾸지 않아도 되게 하고("This abstraction allows users to swap or extend physics backends without changing the core simulator"), 렌더링을 끄면 대규모 학습에 필요한 가속 시간 실행이 가능하다("Rendering is optional and often disabled for large-scale training").

### Ekman 나선 기반 3계층 해류 모델
- 원문 표현: "LOTUSim-Energy implements an Ekman model with three steady-state vertical layers. A surface layer, where wind stress and the Coriolis effect produce the Ekman spiral, and a bottom layer, shaped by frictional drag and bathymetric gradients, bound an intermediate geostrophic interior unaffected by either boundary."
- 정의: 표층은 바람 응력(항력계수 C_D가 10m 풍속 U_10에 따라 구간별로 다른 경험식을 따름)과 지구자전에 의한 Coriolis 힘이 만드는 Ekman spiral로, 저층은 마찰항력·해저 지형 경사가 만드는 별도의 Ekman spiral로 표현되며, 중간층은 파도·경계 어느 쪽 영향도 받지 않는 지형류(geostrophic) 층으로 단순화된다.
- 역할: 로봇 유도·에너지 인지형 계획·정위치 유지(station-keeping)에 직접 영향을 미치는 깊이 의존적 유속 프로파일을 제공한다 — 특히 모노파일·케이블·해저 구조물 근처의 자율 점검에서 이 깊이별 프로파일이 정확도의 전제 조건이라고 명시한다("Realistic current modeling is critical for autonomous inspection near monopiles, cables, and subsea foundations").

### 에너지 인지형(Energy-aware) 배터리 시뮬레이터 플러그인
- 원문 표현: "we developed a modular battery simulator plugin that couples state-of-charge estimation to each vehicle's instantaneous propulsive effort, rather than assuming a constant power draw."
- 정의: 고정 전력 소모를 가정하지 않고 각 차량의 순간 추진 노력(propulsive effort)에 실시간으로 결합된 충전 상태 추정 모델. 실시간 전압·충전상태를 발행해 임무 계획자·오퍼레이터가 사용할 수 있게 한다.
- 역할: LRAUV 등 장기 임무 이동체가 회수를 위한 예비 배터리를 남기도록 점검 강도를 조절하는 데 쓰인다("letting operators adapt inspection intensity to ensure reserve for safe recovery") — 순수 항법 정확도를 넘어 임무 지속가능성 판단까지 시뮬레이터 안에서 다루는 지점이다.

### AIS 참조 궤적 추종(AIS-Referenced Trajectory Following)
- 원문 표현: "The USV waypoint follower is driven along a waypoint sequence derived from a real AIS track of a small Class B vessel, illustrating AIS-referenced guidance rather than a controller-tracking benchmark, since the track reflects an independently controlled vessel with its own disturbances and GNSS noise, not a ground-truth reference."
- 정의: 실제 AIS(자동선박식별장치)로 기록된 소형 선박의 실항적을 웨이포인트 시퀀스로 변환해 시뮬레이션 USV가 따라가게 하는 방식.
- 역할: 저자들은 이것이 "controller 추적 성능을 재는 벤치마크"가 아니라 "실제 항적을 참조로 삼는 유도(guidance)"임을 명시적으로 구분한다 — 실항적 자체가 GNSS 잡음과 그 선박 고유의 외란을 담고 있어 ground-truth로 쓸 수 없다는 한계를 스스로 인정한 지점이다.

## 4. 구조 및 흐름
1. **환경 설정**: Copernicus Marine Service의 MetOcean 제품(바람·파도·해류)을 경계조건으로 흡수해, 특정 날짜(D)의 시간표시(time-stamped) 필드를 동화(assimilate)시켜 Ekman 계수를 보정하고, D+1일의 물리 정합적(physics-consistent) 예측 해류를 생성 — O&M 운영의 안전성 분석·리스크 관리·일정 수립을 지원한다.
2. **에이전트 스폰**: Unity에 미리 구축된 다중 터빈 해상풍력 단지 씬(scene)에 UAV(X500)/USV(WAMV)/ROV(BlueROV2)/AUV(LRAUV) 에이전트를 스폰하고, 표 II에 정의된 O&M 프리미티브(발사/회수, 웨이포인트 통과, 정위치 유지, 블레이드면 점검 패스, 해저 통과 등)를 수행한다.
3. **항법**: Gazebo 통합 웨이포인트 팔로워 플러그인이 2D 좌표 시퀀스를 따라 폐루프 PID 헤딩 제어 + bang-bang 선속도 규제로 유도하며(웨이포인트 도달 허용오차 0.5m, 가속도 한계 0.5m/s²/0.01rad/s², 속도 포화 1~10m/s/0.05rad/s), ROS 2 서비스 인터페이스로 실행 중 임무 재계획이 가능하다.
4. **시각 탐지**: YOLO 기반 실시간 객체 탐지 프레임워크를 온보드에 통합해, BlueROV2(수중)와 X500 UAV(공중) 각각이 블레이드 점검 중 균열·부식 같은 구조적 이상을 탐지한다(그림 7).
5. **HITL**: 오퍼레이터는 Desktop/VR 인터페이스로 AIS 데이터 모니터링과 온보드 카메라의 정밀 제어(줌·재조준)를 수행하며, 배터리 플러그인이 발행하는 충전상태를 함께 보고 회수 여유를 판단한다. Leap Motion으로 VR 헤드셋 없이도 제스처 기반 카메라 제어가 가능하고, 같은 인터페이스가 바람 세기 실시간 조절 교육 모드도 지원한다.
6. **검증 시나리오**: 모노파일·천이피스(TP) 구조에 대해 표층(UAV 블레이드 오빗 스캔) · 해저(ROV 세굴 조사) · 수상(USV AIS 추종) 경로를 동시에 정의(그림 5)해, 통합 웨이포인트 팔로워 플러그인과 AIS 참조 궤적 추종을 실시간 에너지 모니터링과 함께 시스템 수준에서 평가했다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 기존 시뮬레이터들은 다중 도메인·HITL·현실적 환경 물리 세 가지를 동시에 제공하지 못한다 | 표 I(OceanSim/HoloOcean/MarineGym/Stonefish/MIMIRee/Northwind/ACOMAR/ROMEO 등 9개 플랫폼 비교)에서 LOTUSim-Energy만 "Domain: Underwater + Surface + Ground(+Air)", "VR/AR: ✓ + Multi-user", "Data Fusion: On-Going"을 모두 만족한다고 표시됨 |
| 해류 모델이 로봇 거동에 실질적으로 영향을 준다 | §V-E-1(Ocean Current 배치 사례)에서 능동 추진 중인 LRAUV가 Ekman 기반 수직 해상 유속장에 노출되면 "깊이 의존적 측방 표류와 회전 흐름이 지속적인 추진기 보정을 요구한다"고 명시 |
| AIS 참조 궤적 추종이 시뮬레이션-실측 정합성 검증에 쓰일 수 있다 | 그림 6에서 실제 AIS 10개 지점 궤적과 시뮬레이션 웨이포인트 팔로워 궤적을 위경도 좌표로 직접 비교한 플롯 제시 |
| 배터리 플러그인이 실시간 임무 판단에 실제로 연동된다 | 그림 8에서 LRAUV의 배터리 용량·방전을 플러그인이 실시간 모니터링하는 것을 시각적으로 제시하고 본문에서 "letting operators adapt inspection intensity to ensure reserve for safe recovery"라고 용도를 명시 |

## 6. 한계 및 부족한 점
- WebFetch가 아니라 arXiv PDF 원문(7페이지) 전체를 직접 읽어 확인했다 — 페이지 누락은 없다.
- 저자 스스로 명시한 future work: "물리 기반 열화 이미지 형성(degraded-image datasets)", "생물다양성 계획 제약을 위한 리스크 레이어 추가", "에너지 인지형 계획기·고장탐지의 sim-to-real 프로토콜 하에서의 벤치마킹" 세 가지를 결론에서 직접 언급한다.
- 표 II(대표 O&M 태스크 표)의 상당수 행이 "파란 음영이 아닌 행은 실제로 종단간(end-to-end) 벤치마크되지 않았고 하위 에이전트·센서 스택으로만 뒷받침된다"고 캡션에 명시돼 있다 — 즉 이 논문이 실제로 시스템 수준까지 검증한 태스크는 표 II 전체가 아니라 §VI에서 다룬 모노파일/TP 다중 도메인 점검 시나리오(표에서 파란 음영 3행)로 한정된다.
- AIS 참조 궤적 추종은 저자 스스로 "controller-tracking benchmark가 아니다"라고 명시하므로, 이 결과를 제어 정확도의 정량적 증거로 인용하면 안 된다 — 실항적 자체에 GNSS 잡음이 섞여 있어 ground truth가 아니다.
- YOLO 탐지 파이프라인의 정량적 정확도(mAP 등)는 본문에서 제시되지 않았고, 그림 7의 정성적 탐지 예시(부식·균열 박스)만 확인된다 — 모델 자체의 각주는 tinyurl 단축 링크로만 표기돼 있어 원본 모델 출처를 이 논문만으로는 특정할 수 없다.
- 표 II 각주는 UAV/USV/AUV/ROV/CTV 다섯 에이전트 타입과 RGB/IR/LiDAR/MBES/SSS/DVL/INS/UT/EO/AIS/GPS 등 다양한 센서 약어를 정의하지만, 각 센서의 시뮬레이션 충실도(예: MBES/SSS가 실제 음향 시뮬레이션인지 단순화된 스텁인지)는 본문에서 명시적으로 다루지 않는다.

## 7. 원문 기반 핵심 문장
> "Offshore maintenance requires operations in the air, the surface, and the subsea domain and include human supervision. This paper presents LOTUSim-Energy, a real-time maritime simulator designed for multi-domain human–drone interaction for offshore operation and maintenance. The platform unifies heterogeneous unmanned vehicles (Unmanned Aerial Vehicles: UAVs, Unmanned Surface Vehicles: USVs, Autonomous Underwater Vehicles: AUVs, Remotely Operated Vehicles: ROVs) within a distributed architecture coupling environmental forcing (wind, waves, currents) and provides immersive user interfaces for supervision (desktop or virtual reality). A structured offshore task library enables repeatable evaluation of autonomy stacks under realistic metocean disturbances. The simulator supports realistic physics, energy-aware battery modeling, and fault-detection pipelines as modular validation tools."
