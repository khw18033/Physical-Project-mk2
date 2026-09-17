# CODEI: Resource-Efficient Task-Driven Co-Design of Perception and Decision Making for Mobile Robots Applied to Autonomous Vehicles

## 메타데이터
- categories: Occupancy Query 기반 인지 요구사항 정의, FNR/FPR 기반 센서·알고리즘 성능 모델링, ILP 기반 센서 선택·배치, Monotone Co-design 이론
- domain: [[로보틱스·다중로봇]]
- source: Milojevic, Dejan, Zardini, Gioele, Elser, Miriam, Censi, Andrea, Frazzoli, Emilio. "CODEI: Resource-Efficient Task-Driven Co-Design of Perception and Decision Making for Mobile Robots Applied to Autonomous Vehicles." IEEE Transactions on Robotics, 2025.
- url: https://arxiv.org/abs/2503.10296
- year: 2025
- authors: Dejan Milojevic, Gioele Zardini, Miriam Elser, Andrea Censi, Emilio Frazzoli (ETH Zürich, Empa, MIT)
- venue: IEEE Transactions on Robotics (DOI: 10.1109/TRO.2025.3552347)

## 1. 핵심 요약
- 로봇 설계는 안전·효율·자원(비용·에너지·연산·무게) 사용을 균형 있게 하는 하드웨어·소프트웨어의 과업 지향적(task-driven) 최적 선택 문제이며, 저자들은 이를 co-design 문제로 정식화한다.
- Occupancy query 개념을 도입해 sampling-based motion planner가 실제로 필요로 하는 인지 요구사항(perception requirement)을 정량적으로 도출한다.
- 센서+인지 알고리즘 조합(perception pipeline)의 성능은 기하학적 관계, 객체 속성, 센서 해상도, 환경 조건 등 다양한 요인에 따른 False Negative Rate(FNR)·False Positive Rate(FPR)로 모델링한다.
- 인지 요구사항과 인지 성능을 결합해 센서·알고리즘 선택·배치 문제를 weighted set cover 문제로 정식화하고 ILP(Integer Linear Programming) 근사로 풀며, 이를 로봇 바디·모션플래너·인지파이프라인·컴퓨팅 유닛 전체를 포괄하는 co-design 최적화의 inner optimization으로 사용한다.
- 도심 자율주행차(AV) 설계 사례 연구에서, 과업이 복잡할수록(시나리오 다양성↑, 속도↑, prior 폭↑) 더 많은 자원이 필요하며, 비용·무게를 최소화할 때는 카메라가, 에너지·연산 효율을 최소화할 때는 라이다가 선호됨을 확인했다.

## 2. 문서 목적
- 해결하려는 문제: 로봇 설계에서 하드웨어(센서, 컴퓨팅 유닛, 바디)와 소프트웨어(인지 알고리즘, 모션 플래너)를 개별적으로 최적화하지 않고 상호 의존성을 고려해 함께 선택해야 한다는 문제, 특히 인지 요구사항과 인지 성능을 연결하는 공통 언어의 부재.
- 기술적 목표: occupancy query를 매개로 모션 플래닝 요구사항을 인지 요구사항으로 변환하고, FNR/FPR로 표현된 인지 성능과 결합해 자원(비용·전력·연산·무게)을 최소화하는 센서·알고리즘·배치 선택을 자동화하는 것.
- 다루는 범위: occupancy query 정식화, 센서 선택·배치의 weighted set cover/ILP 정식화, monotone co-design 이론에 기반한 전체 로봇(바디+플래너+인지+컴퓨팅) outer optimization, 도심 AV 사례 연구를 통한 Pareto front 분석.

## 3. 핵심 개념 상세

### Occupancy Query
- 원문 표현: "Such planners generate a state hypothesis by posing a series of questions, such as 'Will there be a collision if I occupy a certain configuration at a certain time?'. These questions are referred to as occupancy queries or just queries and are represented as elements of the configuration space..."
- 정의: sampling-based motion planner가 특정 시각·환경에서 특정 configuration을 점유했을 때 충돌 여부를 묻는 질의로, configuration space·시간·환경의 곱 공간(Ψ := Q₀^R × R+ × E)의 원소로 정식화된다.
- 역할: 모션 플래너가 실제로 "무엇을 알아야 하는가"를 명시적인 질의 단위로 변환해, 플래너 종류에 무관하게 인지 시스템이 충족해야 할 요구사항(perception requirement)을 도출하는 인터페이스로 쓰인다.

### FNR/FPR 기반 인지 성능 모델링
- 원문 표현: "Sensor and algorithm performance are evaluated using False Negative Rate (FNR) and False Positive Rate (FPR) across various factors such as geometric relationships, object properties, sensor resolution, and environmental conditions."
- 정의: 특정 센서+인지 알고리즘 조합(perception pipeline)이 특정 class configuration·외형·환경 조건에서 객체를 놓칠 확률(FNR)과 오탐할 확률(FPR)을 신뢰구간으로 표현하는 확률적 성능 모델.
- 역할: 서로 다른 센서·알고리즘 조합을 단일 정확도 점수가 아니라 "어떤 조건에서 어떤 성능을 내는지" 조건부로 비교할 수 있게 하는 표준화된 척도이며, 실제 센서 데이터(nuScenes)와 사전학습 3D 탐지 모델(MMDetection3D)에 대한 이진분류·Gaussian process 기반 추정으로 산출된다.

### Weighted Set Cover 기반 ILP 센서 선택·배치
- 원문 표현: "By integrating perception requirements with perception performance, an Integer Linear Programming (ILP) approach is proposed for efficient sensor and algorithm selection and placement."
- 정의: 인지 요구사항(커버해야 할 class configuration 집합)을 최소 자원 비용으로 커버하는 센서+알고리즘+장착위치 조합을 찾는 문제를 weighted set cover 문제로 정식화하고 ILP로 근사해 푸는 방법.
- 역할: 후보 센서·알고리즘·장착 카탈로그가 주어졌을 때, 요구사항을 만족시키면서 비용·무게·전력·연산을 최소화하는 조합을 자동으로 찾아내는 조합 최적화 기법으로, 임베디드·로봇 하드웨어 설계에서 일반적으로 쓰인다.

### Monotone Co-design 이론 기반 Outer Optimization
- 원문 표현: "Our research is based on the monotone theory of co-design ... promoting the robot task as a functionality, and minimizing resource consumption in terms of monetary costs, power and computational needs, and mass."
- 정의: 로봇의 과업 수행 능력(functionality)을 늘리는 방향과 자원 소비(비용·전력·연산·무게)를 줄이는 방향이 서로 단조(monotone) 관계를 갖도록 정식화한 co-design 최적화 이론으로, 센서 선택(inner optimization) 위에 로봇 바디·모션플래너·컴퓨팅 유닛 선택까지 포함하는 outer optimization을 얹는다.
- 역할: 인지 파이프라인뿐 아니라 로봇 전체 하드웨어·소프트웨어 스택을 하나의 최적화 문제로 통합해, 부분 최적화가 아니라 전체 설계 공간에서 자원-성능 Pareto front를 탐색하는 이론적 틀로, 특정 로봇 종류에 국한되지 않는 일반적인 임베디드 시스템 설계 방법론이다.

## 4. 구조 및 흐름
1. 로봇(바디 B + 에이전트 A: 인지·상태추정·모션플래닝·제어)과 과업(scenario instance들의 집합)을 정의한다.
2. 에이전트가 사용하는 sampling-based motion planner(RRT*, lattice planner 등)가 생성하는 occupancy query 집합(task query)을 시뮬레이션으로 수집한다.
3. Task query를 collision·perceptual collision prediction·prior check를 거쳐 "인지 파이프라인이 탐지해야 하는 class configuration 집합"인 perception requirement로 변환한다(오프라인 후처리).
4. 후보 perception pipeline(센서+알고리즘)의 FNR/FPR을 실측 데이터·사전학습 모델로 추정해 perception performance로 모델링한다.
5. Perception requirement와 perception performance를 결합해 weighted set cover 문제로 정식화하고 ILP로 풀어 센서·알고리즘·장착위치·방향을 선택한다(inner optimization).
6. Inner optimization 결과를 monotone co-design 이론 기반 outer optimization에 포함시켜 로봇 바디·모션플래너·컴퓨팅 유닛까지 함께 선택하며, 비용·전력·연산·무게에 대한 Pareto front를 산출한다.
7. 도심 AV 설계 사례 연구에서 시나리오 수, 목표 속도, prior 지식 폭을 변화시키며 자원 요구량과 센서 선호도의 변화를 분석한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 과업 복잡도(시나리오 수, 속도, prior 폭)가 커질수록 로봇 설계에 필요한 자원이 늘어난다 | Fig. 29~33에서 scenario 수·평균속도 증가에 따라 price/mass/power/computation이 모두 증가하는 Pareto front를 확인 |
| 자원 우선순위에 따라 선호되는 센서 종류가 달라진다 | "to minimize computational requirements in A V design, lidar sensors emerge as the preferred choice due to their perception algorithms requiring fewer operations per second. Conversely, to reduce mass or cost, camera sensors are preferred..." |
| 복잡한 과업에는 결국 라이다가 필수적으로 포함된다 | "designs addressing the most complex task always include lidar sensors. This underscores the superior capability of lidar-equipped sensor pipelines due to their lower FNR and FPR across a wider range of class configurations." |
| 더 넓은 occupancy query 분포(긴 planning horizon, RRT* 같은 넓게 샘플링하는 플래너)는 더 높은 인지 성능 요구로 이어진다 | Fig. 29, 30에서 planning horizon·planner 종류에 따라 요구 자원이 달라짐을 실증; 최고 평균속도를 요구할 때는 RRT*가 전 자원지표(가격/무게/전력/연산)에서 유일하게 선택됨 |

## 6. 한계 및 부족한 점
- pypdf로 arXiv v2 PDF(20페이지) 상당 부분을 직접 확인했다.
- 저자가 명시한 향후 과제: "we aim to integrate additional agent architectures and motion planners beyond sampling-based... we plan to implement filtering and sensor fusion techniques that incorporate considerations of time and uncertainty into the detection and sensor selection process... we plan to conduct expanded case studies that include a variety of tasks and robots, not limited to AVs, and utilize state-of-the-art perception and decision-making software."
- 현재 방법은 객체 탐지를 이진(탐지/미탐지) 판정으로 단순화하고 FNR/FPR의 상한(worst-case)만 사용한다: "we assume that object detections from the perception layer are binary" — 시간적 연속성이나 불확실성 전파는 명시적으로 다루지 않는다.
- Configuration space를 평면(SE(2))으로 제한하는 등 계산 편의를 위한 단순화 가정이 다수 존재하며, 센서 장착 위치·방향 중 일부는 유한 후보로 제한된다.
- 사례 연구가 도심 자율주행차라는 단일 도메인·단일 과업 유형에 집중되어 있어, 저자 스스로도 다른 로봇·과업 유형으로의 확장을 향후 과제로 남겨두었다.

## 7. 원문 기반 핵심 문장
> "The findings highlight that the preference for specific sensors is influenced by the prioritization of resources. For designs prioritizing lower costs and weight, camera sensors are favored. Conversely, when minimizing power consumption and computing resources, lidar sensors are the preferred choice."
