# CASH: Capability-Aware Shared Hypernetworks for Flexible Heterogeneous Multi-Robot Coordination

## 메타데이터
- categories: Hypernetwork 기반 정책 아키텍처, 이종 다중로봇 협력, Zero-shot 팀 구성 일반화, Soft Weight Sharing
- domain: [[로보틱스·다중로봇]]
- source: Fu, Kevin*, Jain, Shalin*, Howell, Pierce, Ravichandar, Harish (* equal contribution). "Capability-Aware Shared Hypernetworks for Flexible Heterogeneous Multi-Robot Coordination." Conference on Robot Learning (CoRL), 2025.
- url: https://arxiv.org/abs/2501.06058
- year: 2025
- authors: Kevin Fu, Shalin Jain, Pierce Howell, Harish Ravichandar (Georgia Institute of Technology)
- venue: Conference on Robot Learning (CoRL) 2025

## 1. 핵심 요약
- 이종 다중로봇 팀을 위한 기존 신경망 구조는 "모든(또는 사전 지정된 일부) 로봇이 하나의 네트워크를 공유"하는 shared-parameter 설계(샘플 효율적이지만 행동 다양성 제한)와 "로봇별 별도 정책"을 쓰는 설계(다양성은 크지만 효율·일반화 저하) 사이에서 양자택일을 강요받아 왔다.
- CASH는 하이퍼네트워크(hypernetwork)를 이용한 soft weight sharing 구조로, 로봇의 capability(예: 속도, payload)가 팀 행동에 미치는 영향을 명시적으로 인코딩해 학습 후에도 각 로봇에 동적으로 적응하는 하나의 공유 정책을 학습한다.
- 이 명시적 capability 인코딩 덕분에 학습 때 보지 못한 로봇이나 팀 구성(unseen robots/team compositions)에 대해 재학습 없이 zero-shot으로 일반화할 수 있다.
- JaxMARL 시뮬레이션(Firefighting, Material Transport)과 Robotarium 하드웨어(Material Transport, Predator-Capture-Prey)에서 imitation learning(DAgger), value-based RL(QMIX), policy-gradient RL(MAPPO) 세 가지 학습 패러다임에 걸쳐 baseline 대비 학습 성능·샘플 효율·zero-shot 일반화 모두 우수하면서 학습 파라미터 수는 60-80% 더 적었다.

## 2. 문서 목적
- 해결하려는 문제: 이종 로봇 팀 정책 학습에서 shared-parameter 구조(효율적이나 표현력 부족)와 independent-parameter 구조(표현력은 크나 비효율·일반화 실패) 사이의 트레이드오프를 피하는 것.
- 기술적 목표: transfer/meta-learning과 기존 multi-robot task allocation 연구에서 영감을 받아, 로봇 capability를 하이퍼네트워크의 조건 입력으로 명시적으로 사용함으로써 공유 정책이 학습 후에도 로봇별로 다르게 적응하도록 만드는 것.
- 다루는 범위: CASH 아키텍처(RNN 인코더 + capability 조건부 하이퍼네트워크 + 적응형 디코더) 설계, 세 학습 패러다임(DAgger/QMIX/MAPPO)에서의 검증, JaxMARL 시뮬레이션과 Robotarium 실물 로봇 실험, unseen capability/team composition에 대한 zero-shot 일반화 평가.

## 3. 핵심 개념 상세

### Capability 벡터 (c_i)
- 원문 표현: "By explicitly encoding the impact of robot capabilities (e.g., speed and payload) on collective behavior, CASH enables zero-shot generalization to unseen robots or team compositions."
- 정의: 각 로봇 i의 capability는 학습된 임베딩이 아니라 손으로 지정한(hand-specified) 연속값 벡터 c_i ∈ ℂ이다. 태스크에 따라 속도, 물탱크 용량(firefighting), 운반 용량(material transport/mining), 센싱 반경·포획 반경(predator-capture-prey) 등 물리적으로 의미가 있는 수치 차원으로 구성된다.
- 역할: capability가 이산 로봇 ID나 클래스 라벨이 아니라 연속 벡터이기 때문에, 학습 구간 밖의 새로운 수치 조합(unseen capability)에도 하이퍼네트워크가 보간·외삽된 가중치를 생성할 수 있는 근거가 된다.

### Capability-Aware Shared Hypernetwork (CASH) 아키텍처
- 원문 표현: 저자들이 명시한 3개 모듈 — RNN 인코더, Hyper Adapter, Adaptive Decoder.
- 정의: (1) 관측 o_i^t를 선형층 → GRU → ReLU로 처리해 잠재 임베딩 z_i^t를 만드는 공유 RNN 인코더, (2) 로컬 관측 o_i^t·자기 capability c_i^t·팀의 나머지 capability C_{/i}^t 세 가지를 입력으로 받아 디코더 가중치를 생성하는 4층 하이퍼네트워크(Hyper Adapter, 각 ReLU 앞에 layer normalization 적용), (3) 생성된 가중치로 동작하는 태스크별 Adaptive Decoder(가치 추정에는 선형층, 행동 로짓에는 MLP).
- 역할: 정책 파라미터 자체를 capability의 함수로 생성함으로써(soft weight sharing), 하나의 네트워크가 로봇마다 다른 행동을 내면서도 파라미터 수는 독립 정책 대비 크게 절감한다.

### Zero-shot Generalization to Unseen Robots/Team Composition
- 원문 표현(재구성): 학습 시 capability는 정의된 범위 내에서 균일 샘플링되고(예: firefighting 학습 시 (capacity, acceleration) 범위 0.09-0.42 / 0.75-3.46), 테스트 시에는 이 학습 범위 밖의 극단값으로 capability를 외삽하면서 나머지 로봇들의 capability는 실행 가능성을 위해 고정한다.
- 정의: "unseen robot/team composition"이 의미하는 것은 새로운 로봇 종류나 새로운 태스크가 아니라, 학습 시 보지 못한 capability 수치 조합(예: 학습 범위 밖의 속도·용량 값)과 그 값을 가진 로봇이 포함된 새로운 팀 구성이다. 정책 구조나 관측·행동 공간은 그대로이고 capability 벡터의 값·조합만 바뀐다.
- 역할: 로봇 하드웨어가 교체되거나 팀 편성이 바뀔 때마다 재학습이 필요한 기존 방식과 달리, capability를 조건 변수로 명시함으로써 재학습 없이 정책을 새 하드웨어 구성에 적응시킬 수 있음을 보이는 핵심 실험 축이다.

### Baseline 비교군 (INDP / RNN-IMP / RNN-EXP)
- 원문 표현(재구성): capability-awareness는 env 설정 파일에서 on/off로 토글 가능하며, RNN-IMP(암묵적, capability 미사용)과 RNN-EXP(capability를 관측에 단순 concat)가 ablation으로 비교된다.
- 정의: INDP는 로봇별 독립 파라미터(일반화 불가), RNN-IMP는 capability 조건 없는 표준 공유 RNN, RNN-EXP는 capability를 관측 벡터에 명시적으로 이어붙인 공유 RNN이다.
- 역할: capability를 "하이퍼네트워크 조건 입력"으로 쓰는 것과 "관측에 단순 첨부"하는 것의 차이를 분리해, CASH의 이득이 단순히 capability 정보 노출이 아니라 하이퍼네트워크 기반 가중치 생성 메커니즘에서 온다는 것을 검증하는 대조군이다.

## 4. 구조 및 흐름
1. 태스크 정의: JaxMARL 기반 시뮬레이션 태스크(Firefighting: 3로봇이 2개 화재 진압, Material Transport/Mining: 4로봇이 운반 용량이 다른 상태로 자원 운반)와 Robotarium 하드웨어 태스크(Material Transport, Predator-Capture-Prey: 센싱 2대 + 포획 2대) 각각에 대해 로봇별 capability 범위를 정의한다.
2. 학습 데이터 구성: 학습 구간에서는 capability를 정의된 범위 내에서 균일 샘플링해 다양한 팀 구성으로 에피소드를 생성한다.
3. 정책 순전파: 각 timestep마다 RNN 인코더가 로컬 관측을 latent로 인코딩하고, Hyper Adapter가 (관측, 자기 capability, 팀 capability)를 입력받아 Adaptive Decoder의 가중치를 생성하며, Decoder가 행동 로짓 또는 가치를 출력한다.
4. 학습 패러다임 적용: 동일 CASH 아키텍처를 DAgger(모방학습), QMIX(value-based RL), MAPPO(policy-gradient RL) 세 파이프라인에 그대로 적용해 학습한다.
5. 평가: (a) 학습 분포 내 팀 구성에서의 성능·샘플 효율을 INDP/RNN-IMP/RNN-EXP와 비교하고, (b) 학습 범위 밖으로 capability를 외삽한 unseen 팀 구성에서 재학습 없이 zero-shot 성능을 측정하며, (c) Robotarium 실물 로봇으로 시뮬레이션 결과의 하드웨어 이전 가능성을 확인한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| CASH는 학습 성능·샘플 효율에서 shared-parameter/independent-parameter 계열 baseline을 모두 능가한다 | 두 시뮬레이션 태스크(Firefighting, Material Transport) x 세 학습 패러다임(DAgger/QMIX/MAPPO) 조합 전반에서 INDP/RNN-IMP/RNN-EXP 대비 우수한 성능과 효율을 보이면서 학습 파라미터는 60-80% 더 적음 |
| 하이퍼네트워크 기반 capability 조건화가 capability를 단순 관측에 첨부하는 것보다 낫다 | RNN-EXP(관측에 capability concat) 대비 CASH(하이퍼네트워크로 capability를 가중치 생성에 사용)가 더 우수한 성능을 보여, capability 노출 방식 자체(하이퍼네트워크 vs concat)가 이득의 핵심 요인임을 뒷받침 |
| CASH는 학습 때 보지 못한 capability 조합/팀 구성에 재학습 없이 일반화한다 | 학습 범위 밖으로 외삽한 capability(예: firefighting에서 학습 범위 0.09-0.42/0.75-3.46 밖 극단값)를 가진 unseen 팀 구성에서도 CASH가 baseline 대비 우수한 zero-shot 성능을 유지 |
| CASH의 이득은 시뮬레이션에 국한되지 않고 실물 로봇에서도 유지된다 | Robotarium 하드웨어 플랫폼에서 Material Transport, Predator-Capture-Prey 두 태스크로 실험을 수행해 시뮬레이션과 일관된 결과 확인 |

## 6. 한계 및 부족한 점
- arXiv(2501.06058, HTML v3)와 GitHub README, 논문 공식 랩 페이지(star-lab.cc.gatech.edu)를 교차 확인했으나 pypdf 등으로 PDF 본문 전체를 직접 파싱하지는 않았다. 정량적 수치(성공률, 파라미터 절감 폭 등 세부 표)는 초록·본문 요약 수준에서 확인했으며 모든 표·그림의 세부 수치까지 검증한 것은 아니다.
- 공식 GitHub 저장소(https://github.com/GT-STAR-Lab/CASH)는 JaxMARL의 fork이며, CASH 정책 구현(`jaxmarl/policies/policies.py`)과 시뮬레이션 환경(`simple_fire.py`, `simple_transport.py`), 세 baseline 학습 스크립트(DAgger/QMIX/MAPPO), 실험 재현용 `final_runs.sh`, plotting 스크립트를 포함해 시뮬레이션 실험은 완전히 재현 가능한 형태로 공개되어 있다.
- 다만 논문이 보고하는 Robotarium 하드웨어 실험(Material Transport, Predator-Capture-Prey)에 대응하는 코드는 저장소 트리에서 확인되지 않았다 — 즉 하드웨어 실험 재현 경로는 공개 저장소 범위 밖이며, 시뮬레이션 결과만 코드 수준에서 완전히 재현 가능하다.
- `final_runs.sh`에는 실행 전 "ENV_KWARGS를 mappo_homogeneous_rnn_mpe.yaml에 직접 복사-붙여넣기하라"는 수동 단계가 남아 있어, 완전 자동화된 원클릭 재현은 아니며 설정 파일 간 수동 동기화가 필요하다.

## 7. 원문 기반 핵심 문장
> "By explicitly encoding the impact of robot capabilities (e.g., speed and payload) on collective behavior, CASH enables zero-shot generalization to unseen robots or team compositions."
