# TAPAS: Throughput-adaptive Perception for Autonomous Systems

## 메타데이터
- categories: Scene Complexity 기반 FPS 추정, GRU 기반 RL 스케줄링 에이전트, Model-to-Cluster 동적 매핑, Reward Reasoning Model
- domain: [[엣지 실행·자원]]
- source: Vyas, Aman, Kodumagulla, Vasista, Taufique, Zain, Liljeberg, Pasi, Kanduri, Anil. "TAPAS: Throughput-adaptive Perception for Autonomous Systems." ACM/IEEE International Conference on Codesign of Embedded Systems (ESWEEK-CODES), 2026.
- url: https://arxiv.org/abs/2607.17317
- year: 2026
- authors: Aman Vyas, Vasista Kodumagulla, Zain Taufique, Pasi Liljeberg, Anil Kanduri (University of Turku, Finland)
- venue: ACM/IEEE International Conference on Codesign of Embedded Systems (ESWEEK-CODES)

## 1. 핵심 요약
- Autonomous system의 perception throughput 요구는 장면 복잡도(scene complexity)에 따라 실행 중 계속 변하지만, 기존 perception 전략은 고정 FPS와 정적 model-to-cluster 매핑을 가정해 처리량을 과다·과소 공급하거나 불필요한 에너지를 소비한다.
- TAPAS는 spatial entropy(Shannon's entropy)로 장면 복잡도를 정량화해 프레임별 FPS 목표를 추정하고, GRU 기반 RL 에이전트(PPO로 학습, Reward Reasoning Model로 보상 설계)로 CPU/GPU/DLA 등 이종 클러스터에 워크로드를 동적으로 재배치한다.
- Jetson Orin NX 플랫폼에서 KITTI 테스트 시퀀스 기준 93-100% throughput met rate를 유지하면서 76%까지 에너지를 절감했고, 학습에 쓰이지 않은 nuScenes 데이터에서도 97% throughput met rate와 64% 낮은 에너지로 일반화됨을 보였다.
- SOTA 대비(EE, OmniBoost, Band) CPU-only부터 CPU+GPU+DLA까지 모든 클러스터 가용성 조합에서 최대 76%/55%/35% 에너지 절감을 달성했고, 클러스터가 부분적으로(0-25%) 사용 불가능해져도 완만하게(graceful) 성능이 저하됨을 실증했다.

## 2. 문서 목적
- 해결하려는 문제: 장면 복잡도에 따라 필요한 perception throughput이 실행 중 변하는데도, 기존 perception 파이프라인은 설계 시점에 고정된 FPS와 정적 model-to-cluster 매핑만 사용해 자원과 에너지를 낭비하는 문제.
- 기술적 목표: scene complexity awareness(적절한 FPS 목표 추정)와 dynamic model-to-cluster mapping(최소 에너지로 목표 처리량 달성)을 긴밀히 결합한 throughput-adaptive perception 프레임워크를 설계하는 것.
- 다루는 범위: spatial entropy 기반 FPS 추정 메커니즘, GRU+PPO+RRM 기반 RL 스케줄링 에이전트 설계, Jetson Orin NX에서의 KITTI/nuScenes 평가, 하드웨어 가용성 저하에 대한 강건성 분석.

## 3. 핵심 개념 상세

### Spatial Entropy 기반 Throughput Estimator
- 원문 표현: "TAPAS uses spatial entropy computed from perception pipeline outputs using Shannon's entropy (Section III-C1) to estimate scene-specific FPS targets. This lightweight mechanism quantifies scene complexity by directly mapping entropy levels to FPS targets."
- 정의: 프레임별 object detection 출력에서 얻은 클래스 맵의 정규화 히스토그램에 Shannon entropy를 적용해 장면 복잡도를 수치화하고, 이를 이산화된 FPS 목표 단계로 매핑하는 경량 모듈.
- 역할: 실시간 비전 파이프라인에서 매 프레임 고정 주기로 처리하는 대신, 복잡한 장면에는 더 자주, 단순한 장면에는 덜 자주 처리하도록 처리 주기를 자체 산출하는 적응형 샘플링 전략의 한 구현이다.

### Dynamic Model-to-Cluster Mapping
- 원문 표현: "Configuring compute resources to meet variable FPS targets presents a complex design space exploration challenge due to application diversity ... and hardware diversity ... dynamic model-to-cluster mapping – to deliver the scene complexity-aware throughput target with the lowest energy consumption."
- 정의: 여러 perception 워크로드(모델)를 CPU/GPU/DLA 같은 이종 컴퓨트 클러스터에 실행 중에 재배치하는 스케줄링 결정.
- 역할: 하나의 SoC 안에 성능·에너지 특성이 다른 여러 가속기가 있을 때, 어떤 워크로드를 어떤 가속기에서 실행할지를 상황에 맞게 바꿔가며 처리량-에너지 트레이드오프를 조절하는 일반적인 이종 자원 스케줄링 기법이다.

### GRU 기반 RL 스케줄링 에이전트
- 원문 표현: "First, scene complexity exhibits temporal dependencies that memory-less agents ... cannot exploit. We address this using a Gated Recurrent Unit (GRU) agent (Section III-C3) that leverages variable FPS, entropy trajectories, and workload variations to perform model-to-cluster mapping."
- 정의: Proximal Policy Optimization(PPO)으로 학습되며, GRU의 은닉 상태를 통해 시간에 따른 장면 복잡도·워크로드 변화의 패턴을 반영해 model-to-cluster 매핑을 결정하는 순환형(recurrent) RL 에이전트.
- 역할: 순간 관측만으로는 포착하기 어려운 장면 복잡도의 시간적 상관관계를 반영해, 단발성 상태만 보는 memory-less 에이전트보다 더 안정적인 매핑 결정을 내리는 데 쓰인다.

### Reward Reasoning Model (RRM)
- 원문 표현: "Second, joint throughput-energy optimization involves conflicting objectives that simple weighted-sum or heuristic reward functions cannot resolve ... We address this through Reward Reasoning Model (RRM) ... that provides structured reasoning to balance throughput met rate and energy efficiency under variable FPS demands."
- 정의: throughput 충족률과 에너지 효율처럼 상충하는 다중 목표를 단순 가중합이 아니라 구조화된 추론으로 균형 잡아 보상을 산출하는 보상 설계 기법.
- 역할: 다목적 강화학습에서 흔히 발생하는 가중치 튜닝의 어려움을 완화하는 보상 모델링 접근으로, 상충하는 여러 성능 지표를 동시에 최적화해야 하는 다른 자원 스케줄링 RL 문제에도 일반적으로 적용될 수 있다.

### Heterogeneous Multi-core Processing (HMP)
- 원문 표현: "AS are increasingly employing Heterogeneous Multi-core Processings (HMPs) with asymmetric CPUs, GPUs, and custom deep learning accelerators."
- 정의: CPU, GPU, DLA(Deep Learning Accelerator) 등 성능·에너지 특성이 서로 다른 여러 연산 유닛을 하나의 SoC에 통합한 하드웨어 구조.
- 역할: 엣지·모바일 기기에서 단일 워크로드 클래스에 국한되지 않고 다양한 가속기 조합으로 처리량-에너지 트레이드오프를 조정할 수 있게 하는 하드웨어적 기반이다.

## 4. 구조 및 흐름
1. Design phase: HMP 플랫폼에서 perception pipeline을 여러 training sequence에 대해 프로파일링해 per-cluster latency, 시스템 에너지 소비, spatial entropy-FPS 관계를 수집한다.
2. Throughput estimator: 매 프레임 object detection 출력에서 spatial entropy(Shannon's formula)를 계산하고, 이를 이산화된 FPS 목표 단계(N_h, N_t 레벨)로 매핑한다.
3. RL environment 구성: 수집된 execution trace와 entropy-FPS 값으로 RL 환경을 구성하고, GRU 기반 에이전트를 PPO로 학습하며 RRM으로 throughput met rate와 에너지 효율을 함께 반영하는 보상을 설계한다.
4. Deployment phase: 런타임에 프레임마다 spatial entropy를 계산해 FPS 목표를 갱신하고, n-frame temporal stacking으로 만든 state를 GRU 에이전트에 입력해 model-to-cluster 매핑을 실시간으로 갱신한다.
5. 평가: Jetson Orin NX에서 CPU-only(C1)/CPU+GPU(C2)/CPU+GPU+DLA(C3) 조합과 클러스터 부분 장애(0-25% unavailability) 상황까지 포함해 throughput met rate와 정규화 에너지를 SOTA(EE, OmniBoost, Band) 대비 비교한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| Scene complexity 기반 가변 FPS 목표가 고정 FPS보다 에너지-처리량 균형이 우수하다 | KITTI seq 7에서 고정 15FPS 대비 23-69% 에너지 절감하면서 100% throughput met rate 달성; 고정 5/10 FPS는 각각 최대 75%, 35%의 throughput 목표를 놓침 |
| TAPAS는 Jetson Orin NX에서 SOTA 대비 큰 폭의 에너지 절감을 유지하며 throughput을 충족한다 | KITTI에서 93-100% throughput met rate로 최대 76% 에너지 절감; 학습에 쓰이지 않은 nuScenes에서도 97% throughput met rate, 64% 에너지 절감으로 일반화 |
| 클러스터 가용성이 줄어들거나 부분 장애가 있어도 TAPAS는 강건하게 동작한다 | CPU-only(C1)부터 CPU+GPU+DLA(C3)까지 전 구간에서 EE·OmniBoost·Band 대비 각각 최대 76%/55%/35% 에너지 절감; DLA 불가용은 영향이 미미하고, GPU가 0→25% 불가용해져도 최고난도 구간의 throughput met rate가 100%→86%로 완만히 저하 |

## 6. 한계 및 부족한 점
- pypdf로 arXiv 프리프린트(15페이지) 본문 전체를 직접 확인했다.
- 논문은 정확도 저하를 피하기 위해 알고리즘 노브(model approximation/quantization/pruning)를 배제하고 하드웨어 노브(cluster mapping)만 사용한다고 명시하며, 두 종류의 노브를 결합했을 때의 잠재적 추가 이득은 다루지 않는다.
- 가장 부하가 큰 구간(Region 4 등)에서는 최고 사양 매핑으로도 throughput 목표를 완전히 충족하지 못하는 경우가 실험적으로 확인된다.
- 저자가 명시한 향후 과제: "Future work will explore model approximation and DVFS for fine-grained energy optimization." — 즉 알고리즘 노브와 DVFS(동적 전압/주파수 조절)의 결합은 아직 다루지 않았다.
- 평가가 단일 플랫폼(Jetson Orin NX)과 특정 데이터셋(KITTI, nuScenes)에 한정되어 있어, 확인한 본문 범위 내에서는 다른 HMP 플랫폼으로의 일반화가 별도로 검증되지 않았다.

## 7. 원문 기반 핵심 문장
> "Addressing this challenge requires tightly coupled scene complexity awareness to estimate an appropriate FPS target and dynamic model-to-cluster mapping to deliver the required throughput at minimum energy."
