# ROAM: Riemannian Optimization for Active Mapping with Robot Teams

## 메타데이터
- categories: Consensus-Constrained Riemannian Optimization, 분산 시맨틱 옥트리 매핑, SE(3) 궤적 위 정보이론적 탐색 계획, 1-hop 통신 기반 완전분산 다중로봇 시스템
- domain: [[로보틱스·다중로봇]], [[3D 인지]]
- source: Asgharivaskasi, Arash, Girke, Fritz, Atanasov, Nikolay. "Riemannian Optimization for Active Mapping With Robot Teams." IEEE Transactions on Robotics (T-RO), Vol. 41, pp. 1077-1097, 2025.
- url: https://arxiv.org/abs/2404.18321 (DOI: https://doi.org/10.1109/TRO.2025.3526295)
- year: 2025 (T-RO 게재; arXiv v1은 2024-04-28)
- authors: Arash Asgharivaskasi, Nikolay Atanasov (UC San Diego, ECE), Fritz Girke (Technical University of Munich)
- venue: IEEE Transactions on Robotics (T-RO), Vol. 41, pp. 1077-1097, 2025
- code: https://github.com/ExistentialRobotics/ROAM (BSD License)

## 1. 핵심 요약
- ROAM은 로봇 팀의 분산 능동 매핑(distributed active mapping)을 **하나의 공통 틀**, 즉 "그래프 위 노드 변수가 리만 매니폴드에 속하고 합의(consensus) 제약이 있는 최적화 문제"로 정식화한다. 매핑은 카테고리 분포(확률 심플렉스) 공간, 플래닝은 SE(3) 궤적 공간이라는 서로 다른 매니폴드 위에서 **동일한 분산 리만 경사하강 알고리즘**(Algorithm 1)을 두 번 인스턴스화한 것이 논문의 핵심 아이디어다.
- 각 로봇은 매 반복마다 (a) 이웃과의 측지 거리를 줄이는 합의(consensus) 갱신과 (b) 로컬 목적함수(관측 로그우도, 또는 정보이득+충돌회피 점수) 경사 갱신을 번갈아 적용하며, 두 갱신 모두 지수사상(exponential map)으로 매니폴드 위에 재사영(retract)한다. 합의 갱신의 경사가 이웃 노드 항의 합으로 정확히 분해되기 때문에 **1-hop 통신만으로** 전역 합의·최적성 보장(Theorem 1)이 성립한다.
- 중앙 매핑/플래닝 노드가 전혀 없으며(no central estimation and control node), 시뮬레이션(Unity, Husky 6대)과 실환경(ClearPath Jackal 2대 + F1/10 레이싱카 1대) 양쪽에서 검증되었다.
- 실환경에서는 로봇 온보드 컴퓨터만으로 분산 시맨틱 옥트리 매핑 평균 2.44 Hz, 분산 플래닝 반복당 평균 0.014초의 실시간 성능을 달성했고, 통신이 끊겨도 로컬 계획이 계속되며 재연결 시 자동으로 맵 불일치(discrepancy)가 0으로 수렴했다.

## 2. 문서 목적
- 해결하려는 문제: 기존 분산 다중로봇 능동 매핑 방법들은 선형-가우시안 관측모델과 유클리드 로봇 상태(예: 위치벡터)라는 단순화된 가정에 의존한다. 시맨틱 맵(카테고리 확률분포)이나 SE(3) 로봇 자세 궤적처럼 본질적으로 비유클리드·비선형인 도메인에서는 이런 방법을 직접 쓸 수 없고, 중앙집중식 해법에 의존해야 했다.
- 기술적 목표: 통신 그래프의 각 노드(로봇) 상태가 일반적인 리만 매니폴드에 속하는 경우에 대해, 합의 제약이 있는 분산 최적화 문제를 정식화하고, **오직 단일-hop 통신만으로 합의(consensus)와 최적성(optimality) 보장을 동시에 갖는** 범용 알고리즘을 개발하는 것.
- 다루는 범위: (1) 일반 리만 매니폴드에 대한 분산 최적화 알고리즘과 그 수렴·최적성 증명, (2) 확률 심플렉스 위에서의 분산 시맨틱 옥트리 맵 추정으로의 적용, (3) SE(3) 궤적 매니폴드 위에서의 정보이론적 협력 탐색 계획으로의 적용, (4) 오픈소스 구현 및 시뮬레이션·실환경 검증.

## 3. 핵심 개념 상세

### Consensus-Constrained Riemannian Optimization (Problem 1 / Algorithm 1)
- 원문 표현: *"Find a joint state x that maximizes... F(x) = 1/|V| Σ_i f_i(x_i), s.t. x_i∈M, ∀i∈V, and φ(x)=0"*, 여기서 φ(x) = Σ_{{i,j}∈E} A_ij d²(x_i,x_j) (aggregate distance function).
- 정의: 통신 그래프 G(V,E)의 각 에이전트 i가 컴팩트 리만 매니폴드 M 위의 상태 x_i를 가지며, 로컬 목적함수 f_i의 합을 최대화하되 이웃 간 측지 거리 제곱합 φ가 0(=완전 합의)이 되도록 제약한 문제.
- Algorithm 1의 두 스텝: **consensus step** — x̃_i(k) = Exp_{x_i(k)}(-ε · grad_{x_i}φ(x)|_{x=x(k)}), 이때 grad_{x_i}φ(x) = -2 Σ_{j∈N_i} A_ij Exp⁻¹_{x_i}(x_j)로 정확히 분해되므로 **이웃 N_i와의 1-hop 통신만 필요**. **local step** — x_i(k+1) = Exp_{x̃_i(k)}(α(k) · grad f_i(x_i)|_{x_i=x̃_i(k)}), 이는 순수 로컬 계산으로 통신이 불필요.
- Theorem 1 (수렴·최적성 보장): M이 컴팩트, f_i가 geodesically concave, 인접행렬 A가 row-stochastic, d²가 geodesically convex, step size가 Robbins-Monro 조건을 만족하고, 매니폴드 곡률에 대한 조건(Assumption 2, 측지선 루프의 길이로 net tangent vector를 상계)이 성립하면, ε∈(0,2/L) (L=4(1+ρ))에서 (1) 모든 로봇 상태가 하나의 합의 구성으로 수렴하고, (2) 참 최적값 F(x*)가 반복 중 F(x(k)) 최댓값의 극한에 대한 하한이 됨을 증명한다(부록 A: φ의 geodesic L-smoothness → 수렴 → 최적성 순으로 전개).

### 매핑 인스턴스화 — 확률 심플렉스 위의 분산 시맨틱 옥트리 매핑 (Problem 2 / Algorithm 2)
- 매니폴드와 표현: 각 맵 셀의 카테고리 분포 p_n ∈ 𝒫_𝒞 (semantic class 집합 𝒞={0,...,C}, 0=free space)를 log-odds 벡터 h_n∈ℝ^(C+1)로 표현(소프트맥스 σ로 일대일 대응). 합의항 φ(h_{1:|V|}) = Σ_{{i,j}∈E} A_ij‖h_j-h_i‖² 는 log-odds 공간의 유클리드 거리를 사용한다.
- 목적함수(원문): *"f_i(h_i) = Σ_c σ_{c+1}(h_i) log(q^i_t(c)/σ_{c+1}(h_i))"*, 여기서 q^i_t(c)는 로봇 i가 시각 t까지 얻은 관측 z^i_{1:t}={(r^i_{t,b}, y^i_{t,b})}(레이별 거리 r과 물체 카테고리 y로 이뤄진 시맨틱 포인트클라우드)로부터 계산된 역관측모델(inverse observation model)의 누적값이다. 즉 각 로봇의 목적은 자신의 RGB-D 관측 로그우도 기대값을 최대화하는 베이지안 셀 단위 추정이며, 셀 독립 가정(Lemma 1)으로 전체 맵 문제가 셀별 문제로 분해된다.
- Algorithm 2: consensus step에서 이웃 로봇의 log-odds와의 차이를 평균화(h̃_i = h_i + ε_m Σ_{j∈N_i} A_ij(h_j-h_i)), 이어서 로컬 관측 gradient(소프트맥스 기반)를 적용하는 로컬 step은 다중클래스 로그오즈 형태의 베이즈 규칙 갱신과 동등하다. 통신·저장 효율을 위해 이 갱신 규칙을 정규 그리드 대신 **옥트리(octree)의 리프 노드에** 그대로 적용해 무손실 압축(lossless octree compression)을 달성한다.
- "map uncertainty" 자체는 매핑 단계보다 플래닝 단계(아래)에서 명시적으로 정보이득 형태로 등장한다.

### 플래닝 인스턴스화 — SE(3) 궤적 매니폴드 위의 정보이론적 협력 탐색 계획 (Problem 3 / Algorithm 3) — 이것이 "Riemannian Optimization" 각도의 핵심
- 매니폴드: 각 로봇의 T-스텝 미래 궤적을 SE(3) 곱 매니폴드 SE(3)^(|V|×T) 위 점으로 표현. 두 포즈 간 거리는 SE(3) 로그사상(Lie algebra twist ξ)에 스케일 대각행렬 Γ를 적용한 이차형식 d²(X_t^i, X_{t'}^j) = ξ^⊤Γξ.
- **map uncertainty가 계획 방향을 결정하는 정확한 메커니즘**: 임의의 후보 포즈 V에서 관측 z를 얻었을 때 현재 맵 확률분포 p_t(m) 대비 기대 정보이득을 Shannon mutual information I(m;z|V,p_t(m))로 정량화한다. 여기에 장애물까지 거리장(distance field) D의 로그를 안전항으로 더한 점수 s_i(V) = I(m;z|V,p_t(m)) + γ_c·log D(V,p_t(m))를 정의하고, 포즈 X 주변 측지구(geodesic ball, 반지름 ξ_max) 안의 샘플 포즈들 V에 대한 s_i(V)의 거리 가중 볼록결합으로 **미분 불가능한 mutual information을 미분 가능한 score f(X,p_t(m))로 보간**한다(원거리 센서·옥트리 조합에서 MI가 포즈에 대해 미분 불가능하기 때문). 즉 map uncertainty(엔트로피/상호정보량)를 SE(3) 매니폴드 위에서 리만 경사로 따라가는 것이 "탐색 방향"을 만든다.
- 다중로봇 협력항: 서로 다른 로봇·시각의 포즈 쌍에 대한 센서 시야(FoV) 중첩 벌점 q(X_{i,τ}, X_{j,τ'})를 로컬 목적함수에서 빼서(γ_q로 가중) 중복 관측을 억제한다. 로컬 목적함수 f_i는 "정보+안전" 항과 "중복관측 벌점" 항의 합.
- Algorithm 3(협력 계획): 각 로봇은 **팀 전체 |V|개 로봇 궤적의 로컬 사본**을 자신의 로컬 맵 기준으로 유지·계획한다(frontier-based exploration으로 초기화). consensus step은 SE(3) 위 오른쪽 섭동(perturbation, 왼쪽 Jacobian J_L 사용)으로 이웃의 해당 포즈들과의 측지 거리를 줄이고, local step은 f(정보+안전)와 q(중복관측)의 리만 경사를 로컬로 적용한다. 결과적으로 전역 해는 "자신의 정보이득·안전 극대화"와 "동료와의 중복관측 회피" 사이의 파레토 최적점이다.
- 곡률로 인한 한계: SE(3)이 양의 곡률을 가지므로 φ가 지역 최소값을 가질 수 있어(Appendix A.3 of [68] 인용), 초기 궤적 차이가 크면 Algorithm 1/Theorem 1은 **지역적** 합의·최적성만 보장한다(f_i도 locally concave에 불과).

### 완전 분산 구조와 로봇 간 협력 메커니즘 (중앙 노드 부재 확인)
- 원문 표현: *"Both multi-robot mapping and planning are performed in the absence of a central estimation and control node and only involve peer-to-peer communication among neighboring robots."*
- 협력은 두 계층에서 순수 peer-to-peer로 이루어진다. **매핑**: 각 로봇이 자신의 옥트리 로그오즈 맵을 t_m^pub(=5초)마다 이웃에게 브로드캐스트하고, 수신 맵을 로컬 버퍼에 쌓았다가 t_m^int(=5초)마다 Algorithm 2의 합의 스텝으로 흡수한다. **플래닝**: "Distributed Ledger Synchronization"(Algorithm 4)으로 각 로봇이 팀 전체의 "계획 준비 상태"를 이진 벡터(ledger)로 이웃과 공유하고, 준비된 로봇 비율이 thresh_p(=0.4) 이상이면 전역 뷰포인트 계획(Algorithm 3, k_p=20회 반복)을 동시에 시작한다. 반복마다 로컬 플랜을 브로드캐스트하며 합의를 이룬 뒤, 저수준 궤적 최적화(A* 기반 충돌회피 경로, 속도 제어기)는 순수 로컬 계산으로 처리한다. 실환경에서는 **multi-master ROS 아키텍처**(로봇마다 독립 ROS master)로 Wi-Fi 상에서 ledger·로컬 플랜·로컬 옥트리 맵·추정 포즈만 교환하며, 통신 두절 시 각 로봇이 로컬 맵만으로 계속 계획하다가 재연결 시 자동으로 맵 합의를 회복한다(실환경 실험에서 discrepancy φ가 0으로 급락하는 것으로 관측).

### x86-64 / ARM 지원 검증
- GitHub README 원문 그대로 인용: *"ROAM is implemented as two ROS packages, can be built on x86-64 and ARM-based processors"* — **동료의 주장은 사실로 확인된다.** README는 이 한 문장으로 두 아키텍처 지원을 명시할 뿐, 별도의 CI 매트릭스나 아키텍처별 빌드 스크립트, 상세 의존성 목록은 제공하지 않는다. 논문 본문에는 x86/ARM이라는 용어 자체가 등장하지 않으며, 이 claim은 README(리포지토리 문서)에만 있는 정보다. 실환경 실험 하드웨어 구성(Jackal의 NVIDIA GTX 1650 탑재 온보드 PC는 x86 계열, F1/10의 NVIDIA Xavier NX는 ARM 기반 Jetson 계열 SoC)은 두 아키텍처를 실제로 함께 운용했음을 간접적으로 뒷받침한다.

## 4. 구조 및 흐름
1. **문제 정식화 (Sec. II, Problem 1)**: 통신 그래프 위 컴팩트 리만 매니폴드 상태 + 합의(consensus) 제약을 갖는 일반 최적화 문제 정의.
2. **분산 알고리즘 (Sec. III, Algorithm 1 + Theorem 1)**: consensus step과 local step을 번갈아 적용하는 리만 경사하강을 제안하고, 1-hop 통신만으로 합의 수렴·최적성 하한을 증명.
3. **매핑 인스턴스화 (Sec. IV, Problem 2 / Algorithm 2)**: 확률 심플렉스(log-odds 표현) 위에서 시맨틱 옥트리 맵을 분산 추정.
4. **플래닝 인스턴스화 (Sec. V, Problem 3 / Algorithm 3, 4)**: SE(3) 궤적 공간 위에서 Shannon mutual information 기반 협력 탐색 계획을 수행하고, ledger 기반 동기화(Algorithm 4)로 전역 계획 라운드를 조율.
5. **소프트웨어 스택 (Fig. 5)**: RGB-D → 시맨틱 분할 → 시맨틱 포인트클라우드 → 시맨틱 옥트리 맵 ↔ (이웃 로봇과) → 멀티로봇 로컬라이제이션 → 전역 분산 플래너(뷰포인트) → 로컬 궤적 플래너(A*) → 속도 제어기.
6. **검증 (Sec. VI)**: (a) 시뮬레이션 — Unity 야외 마을 환경, ClearPath Husky 6대, 3개 네트워크 토폴로지(Full/Hierarchical/Ring) × 3개 플래닝 변형(Collaborative/Egocentric/Frontier) 비교. (b) 실환경 — 실내 지하 공간(로비-복도-실험실), ClearPath Jackal 2대 + F1/10 레이싱카 1대.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| 리만 매니폴드에서도 1-hop 통신만으로 합의 수렴 + 최적성 하한이 보장된다 | Theorem 1과 그 증명(Appendix A: φ의 geodesic L-smoothness → x(k)의 합의 수렴 → F(x*)에 대한 하한) |
| 완전 분산(Collaborative) 계획은 성긴 네트워크(Hierarchical/Ring)에서도 완전연결(Full)+비협력(Egocentric) 조합에 필적하는 성능을 낸다 | 시뮬레이션 결과(Fig. 10, 11): Collaborative+Hierarchical/Ring의 coverage·normalized map entropy가 Egocentric+Full과 유사한 궤적을 보임 |
| 저사양 온보드 컴퓨팅만으로 실시간 분산 매핑·계획이 가능하다 | 실환경: 평균 2.44 Hz 분산 시맨틱 옥트리 매핑, 평균 0.014초/반복 분산 플래닝, Wi-Fi 기반 소비자급 통신 인프라로 1450초간 3대 로봇 실내 탐사 수행 |
| 통신 단절에도 로컬 안전·탐사가 유지되고 재연결 시 자동으로 맵 합의를 회복한다 | 실환경 t≈500~1200s 구간의 의도적 신호 감쇠/차폐로 인한 간헐적 단절 동안 로봇들이 로컬 맵만으로 독립 탐사를 지속했고, 복귀 후 맵 discrepancy φ(h_{1:3})가 급격히 0으로 수렴(Fig. 17) |
| 옥트리 기반 시맨틱 맵 통신은 대역폭 효율적이다 | 시뮬레이션에서 평균 97 Bytes/sec의 대역폭으로 1 m²(voxel 0.2×0.2×0.2 m³) 커버리지를 유지 |

## 6. 한계 및 부족한 점
- pypdf로 IEEE T-RO/arXiv 버전(20페이지) 본문 전체와 부록(Theorem 1 증명)을 직접 확인했다.
- SE(3) 매니폴드의 양의 곡률로 인해 합의 함수 φ가 지역 최소값을 가질 수 있어, 초기 로컬 궤적들이 서로 크게 다르면 Algorithm 1이 전역이 아닌 지역 합의로 수렴할 수 있다고 저자가 명시한다. 또한 플래닝의 로컬 목적함수 f_i는 locally concave에 불과해 Theorem 1은 플래닝 문제에 대해서는 지역적 최적성만 보장한다.
- 시뮬레이션 실험은 로봇 포즈를 알고 있다고 가정하고("we assume known robot poses") 완벽한 시맨틱 분할("perfect semantic segmentation")을 사용해, 실제 로컬라이제이션·분할 오차의 영향은 실환경 실험에서만 간접적으로 드러난다.
- 실환경 실험은 실내 소규모 공간(로비+복도+실험실)에서 3대 로봇으로 제한되어, 시뮬레이션의 6대·야외 대규모 환경과 직접 비교 가능한 정량 지표(coverage, entropy 등)가 동일 축척으로 제시되지는 않는다.
- 저자가 명시한 향후 과제: "further research effort is needed to study faster variants of ROAM using Nesterov accelerated and second-order gradient methods"(가속·2차 경사법 미탐구), 그리고 "analyzing the distance to consensus as well as sub-optimality bounds for ROAM in the case of non-convex distance measures and non-concave objective functions"(비볼록/비오목 조건에서의 이론적 보장은 미해결).
- x86-64/ARM 지원 claim은 GitHub README 한 문장으로만 명시되어 있으며, 논문 본문에는 아키텍처별 벤치마크나 빌드 검증 내용이 없다.

## 7. 원문 기반 핵심 문장
> "We develop a distributed Riemannian optimization algorithm that relies only on one-hop communication to solve the problem with consensus and optimality guarantees."

> "We show that multi-robot active mapping can be achieved via two applications of our distributed Riemannian optimization over different manifolds: distributed estimation of a 3-D semantic map and distributed planning of SE(3) trajectories that minimize map uncertainty."

> "Both multi-robot mapping and planning are performed in the absence of a central estimation and control node and only involve peer-to-peer communication among neighboring robots."

> "ROAM enables fully distributed collaborative active mapping of an unknown environment without the need for central estimation and control."

> (GitHub README) "ROAM is implemented as two ROS packages, can be built on x86-64 and ARM-based processors"

> (실환경 실험 결과) "With all the mapping and planning computations carried out using the on-board robot computers, we obtain an average frame rate of 2.44Hz for distributed semantic octree mapping, and an average distributed planning iteration time of 0.014s."
