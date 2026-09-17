# SCOUT: Semantic scene COverage via Uncertainty-guided Traversal

## 메타데이터
- categories: 불확실성 인지 3D Scene Graph, Uncertainty-Guided Viewpoint Planning, Open-vocabulary 객체 라벨 Posterior, Active Exploration
- domain: [[로보틱스·다중로봇]]
- source: Mao, Junyu, Ayoubi, Sara, Sharma, Vishnu D., Hadžić, Ilija, Andrews, Matthew. "SCOUT: Semantic scene COverage via Uncertainty-guided Traversal." 2026 ICRA Workshop on Uncertainty in Open World Robotics.
- url: https://arxiv.org/abs/2606.06721
- year: 2026
- authors: Junyu Mao, Sara Ayoubi, Vishnu D. Sharma, Ilija Hadžić, Matthew Andrews
- venue: 2026 ICRA Workshop on Uncertainty in Open World Robotics (arXiv:2606.06721, cs.RO/cs.AI, submitted 2026-06-04)

## 1. 핵심 요약
- 로봇이 장시간 운용될 때 공간을 단순히 "방문"하는 것을 넘어 점진적으로 "이해"해야 한다는 문제의식에서, SCOUT은 능동적 로봇 이동(active traversal)과 확률적 3D scene graph 구축을 결합한 프레임워크를 제안한다.
- 입력은 posed RGB-D 관측과 사전 LiDAR 스캔으로 만든 외부 2D occupancy map(자유/점유 셀)이며, 이로부터 각 노드가 fused 3D geometry(중심·bounding box)와 open-vocabulary 라벨 집합에 대한 posterior belief, 그리고 그 belief의 Shannon entropy를 유지하는 uncertainty-aware 3D scene graph를 점진적으로 구축한다. 기하(geometry)는 확률적 posterior가 아니라 관측 포인트를 누적한 fused 추정값이며, posterior belief는 오직 open-vocabulary 라벨에만 적용된다는 점이 이 논문의 핵심 구분이다.
- Uncertainty-Guided Traversal(UGT) 플래너는 각 후보 viewpoint에 대해 "(가중 semantic certainty gain + 가중 geometric coverage gain) ÷ travel cost" 형태의 비율 점수로 다음 관측 지점을 선택하며, 이를 통해 모호한 기존 객체를 재방문하거나 아직 보지 못한 자유공간으로 확장한다.
- Gazebo 시뮬레이션의 simple/challenging 두 시나리오(각 13개 객체)에서 offline lawnmower 궤적 베이스라인 대비 node/edge precision·recall이 대부분 항목에서 더 높았으나(예: simple 시나리오 node F1 1.00 vs 0.82), edge recall(특히 next-to 관계)과 challenging 시나리오에서의 수렴은 아직 제한적이다. 공식 코드/프로젝트 페이지는 확인되지 않는다.

## 2. 문서 목적
- 해결하려는 문제: 기존 능동 탐색(active SLAM/exploration) 연구는 대체로 기하학적 커버리지(미탐 영역 채우기)만 최적화하고, semantic scene graph 연구는 대체로 offline·decoupled 파이프라인(먼저 다 관측한 뒤 그래프를 나중에 구성)을 가정한다. 두 흐름을 결합해 "어디를 봐야 의미적으로 더 확실해지는가"까지 고려하는 online 능동 탐색이 부족하다는 문제.
- 기술적 목표: (1) 관측이 들어올 때마다 점진적으로 갱신되는 확률적(불확실성을 명시하는) 3D scene graph를 만들고, (2) 그 불확실성 자체를 이용해 다음 viewpoint를 선택하는 closed-loop 능동 탐색 플래너(UGT)를 설계하는 것.
- 다루는 범위: 노드별 open-vocabulary 라벨 posterior의 정의와 갱신(association + Bayesian fusion), on/inside/belong/next-to 4종 edge의 기하학적 판정, viewpoint utility 함수의 정확한 정의(가시성·novelty 기반 certainty gain, FOV 기반 coverage gain, A* 기반 travel cost), Gazebo 2-시나리오 실험과 lawnmower 베이스라인 비교, 한계·향후 과제.

## 3. 핵심 개념 상세

### 입력 모달리티: Posed RGB-D + Prior 2D Occupancy Map
- 원문 표현(패러프레이즈, HTML 본문 근거): "UGT consumes the current graph 𝒢_t together with an a priori 2D occupancy map ℳ from prior LiDAR scanning, with free and occupied cells."
- 정의: 입력은 (a) 매 스텝 들어오는 posed RGB-D 프레임과 (b) 탐색 시작 전에 별도의 LiDAR 스캔으로 미리 만들어 둔 2D occupancy grid(자유 셀 ℳ_free, 점유 셀 ℳ_occ)이다. 이 prior map은 로봇이 이번 탐색 중에 스스로 만드는 것이 아니라 외부에서 사전에 주어지는 정적 지도이며, 실행 가능한 viewpoint 필터링과 A* 기반 이동 비용 계산에 사용된다.
- 정정 포인트: "prior map"은 semantic 정보나 3D 지도가 아니라 LiDAR 기반 2D occupancy map(자유/점유 이진 정보)에 한정된다. 즉 traversal의 지리적 제약(어디로 갈 수 있는가)만 제공하고, semantic scene graph 구축 자체는 RGB-D + open-vocabulary 스택이 담당한다.

### 불확실성 인지 3D Scene Graph: 노드·엣지·belief 갱신
- 정의: 각 노드 o_i ∈ 𝒪_t는 (1) fused 3D geometry(중심 + bounding box, 누적된 3D support point로부터 계산되는 결정론적 추정값), (2) 라벨 어휘 ℒ에 대한 posterior p_i^t(c), (3) 그 posterior의 Shannon entropy H_i^t = −∑_c p_i^t(c) log p_i^t(c), (4) 과거 관측 방위 이력 ℋ_i를 유지한다.
- "geometry posterior"와 "label posterior"의 정확한 의미: 이 논문에서 확률적 posterior가 붙는 대상은 오직 open-vocabulary 라벨(클래스) 분포뿐이다. 기하는 posterior가 아니라 관측된 3D 포인트를 누적·융합(fusion)한 point estimate로 관리된다. 즉 "geometry posterior"라는 표현은 이 논문의 실제 정의와 정확히 일치하지 않으며, 정확히는 "fused geometry + label posterior"로 구분해야 한다.
- Belief 갱신 과정: 매 프레임 Grounding DINO + SAM + CLIP으로 구성된 open-vocabulary 스택이 관측 d(CLIP 시각 임베딩 f^vis, 텍스트 임베딩 f^text 포함)를 추출한다. 새 관측은 공간 유사도 S_sp, 시각 유사도 S_vis, 텍스트 유사도 S_text를 가중치 λ_sp, λ_vis, λ_text(합 1)로 결합한 유사도로 기존 노드와 연계(association)되거나 새 노드를 생성한다. 프레임 로컬 belief q_i^t(c)는 CLIP cosine 유사도를 softmax한 값이며, 최종 posterior는 곱셈적 Bayesian 갱신으로 계산된다:
  p_i^t(c) = [p_i^{t-1}(c) · q_i^t(c)] / ∑_{c'} p_i^{t-1}(c') · q_i^t(c')
- Edge: on(물리적 지지), inside(포함, directed), belong(부분-전체, directed), next to(인접, undirected) 4종을 갱신된 3D bounding box의 기하학적 분류로 판정한다(학습된 관계 예측기가 아니라 규칙 기반 기하 분류).

### Uncertainty-Guided Traversal(UGT) 플래너와 실제 viewpoint 점수식
- 실제 공식(HTML 본문 Section II-A2, 동료가 말한 "certainty gain + coverage gain − travel cost"와는 다름):
  S_final(v) = (w_cert · S_cert(v) + w_cov · S_cov(v)) / S_travel(v),  w_cert + w_cov = 1
  즉 세 항은 뺄셈이 아니라 "가중합을 이동비용으로 나누는 비율(gain-to-cost ratio)" 구조다.
- S_cert(v) (semantic certainty gain): 노드별 가시성 Vis(v,i)(레이캐스팅으로 얻는, o_i가 최초로 보이는 광선의 비율)와 novelty Nov(v,i)(기존 관측 방위와의 최소 각도차 Δθ(v,i)를 사인함수로 재매핑, 기본 θ⋆=π/4에서 최대)를 곱해 관측 강도 Obs(v,i)=Vis(v,i)·Nov(v,i)를 얻는다. 불확실성 감소는 지수 포화 형태 ΔH(v,i) = H_i^t(1 − e^{−α·Obs(v,i)})로 모델링되고, G_cert(v) = ∑_i ΔH(v,i)를 전체 scene entropy 합으로 정규화해 S_cert(v) = G_cert(v) / ∑_i H_i^t를 얻는다.
- S_cov(v) (geometric coverage gain): S_cov(v) = |(FOV(v) ∩ 𝒯) \ 𝒞_t| / |𝒯|. 즉 목표 셀 집합 𝒯 중 아직 관측되지 않은(𝒞_t에 없는) 셀을 이번 FOV로 새로 커버하는 비율.
- S_travel(v) (travel cost): 현재 로봇 pose에서 v까지 occupancy map ℳ 위에서 A*로 계산한 최단경로 거리.
- 결론적으로 "Semantic Certainty Gain + Geometric Coverage Gain − Travel Cost"라는 동료의 서술은 틀렸다: 실제로는 (가중 certainty + 가중 coverage)를 travel cost로 나누는 비율식이며 뺄셈 항이 아니다.

## 4. 구조 및 흐름
1. 로봇이 posed RGB-D 프레임을 획득하면 open-vocabulary 스택(Grounding DINO + SAM + CLIP)이 객체 후보와 임베딩을 추출한다.
2. 공간·시각·텍스트 유사도 가중합으로 기존 scene graph 노드와 연계하거나 신규 노드를 생성하고, geometry는 fusion으로, 라벨은 곱셈적 Bayesian posterior로 갱신한다. 갱신된 bounding box들 간 기하 분류로 on/inside/belong/next-to edge를 만든다.
3. UGT 플래너가 현재 그래프 𝒢_t와 사전 2D occupancy map ℳ을 입력받아 후보 viewpoint마다 S_cert, S_cov, S_travel을 계산하고 S_final = (w_cert·S_cert + w_cov·S_cov)/S_travel이 최대인 viewpoint를 다음 목표로 선택한다.
4. 로봇이 선택된 viewpoint로 이동(내비게이션 스택 사용)해 새 관측을 얻고 1단계로 되돌아가는 closed loop를 반복하며, 관측 예산(이 논문 실험은 트라이얼당 최대 50프레임)을 소진하거나 종료 조건에 도달할 때까지 지속한다.
5. 평가: Gazebo 시뮬레이션에서 SCOUT과 lawnmower(오프라인 2D map 기반 고정 스윕 궤적 + 사후 그래프 구성) 베이스라인을 simple/challenging 두 시나리오, 시나리오·방법당 3회 트라이얼로 비교한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| Online 능동 탐색(SCOUT)이 offline decoupled 파이프라인(lawnmower)보다 노드 수준 인식 정확도가 높다 | Simple 시나리오: node precision/recall 1.00/1.00(SCOUT) vs 0.86/0.79(lawnmower). Challenging 시나리오: 0.93/0.94(SCOUT) vs 0.72/0.74(lawnmower) |
| SCOUT이 관계(edge) 인식에서도 대체로 우세하지만 recall은 여전히 낮다 | Simple: edge precision/recall 1.00/0.62(SCOUT) vs 0.86/0.48(lawnmower). Challenging: 0.67/0.39(SCOUT) vs 0.54/0.27(lawnmower). Ground-truth edge 수는 simple 11 on+11 next-to, challenging 11 on+18 next-to |
| 불확실성 기반 재방문이 가려진(occluded) 객체 처리에 기여한다 | Challenging 시나리오는 마주보는 배치에 90° 회전과 부분 폐색(시계가 머그 뒤, 스테이플러가 머그 뒤, 장난감이 캔 뒤)을 포함하도록 설계되었고, 이 조건에서도 SCOUT의 node recall(0.94)이 lawnmower(0.74)를 상회 |

## 6. 한계 및 부족한 점
- WebFetch로 arXiv HTML 전문(https://arxiv.org/html/2606.06721v1)과 PDF를 확인했다. PDF는 텍스트 스트림 추출이 불완전해 저자 소속·acknowledgment는 확인하지 못했다.
- Edge recall이 낮다: 특히 simple 시나리오에서도 next-to 관계의 62% 정도만 회수하며, 저자들은 이를 근접성(proximity) 임계값 튜닝 문제로 돌린다.
- 객체 연계(association) 오류: challenging 시나리오에서 동일 선반의 서로 다른 두 관측을 병합하지 못해 중복 엔티티와 연쇄적 false positive가 발생했다고 저자가 명시한다.
- 수렴 문제: challenging 시나리오에서는 "prescribed frame limit(예산 50프레임)에 도달할 때까지 수렴하지 않았다"고 명시 — 최대 entropy가 예산 내에 임계값 아래로 떨어지지 않았다.
- 불확실성 모델의 범위 제한: 현재 uncertainty는 객체(노드) 가설에만 부착되고 관계형 edge는 구조적 context로만 다뤄지며, edge에 uncertainty를 부착하는 것은 향후 과제로 명시된다.
- 내비게이션 정밀도: 내비게이션 스택의 pose/orientation 허용오차 때문에 로봇이 요청된 정확한 viewpoint에 항상 도달하지 못해 폐색 객체 관측에 여러 번 시도가 필요했다고 보고한다.
- 평가 범위: Gazebo 시뮬레이션의 2개 소규모 시나리오(각 13개 객체), 베이스라인은 lawnmower 1종뿐이며 실물 로봇 배치는 아직 수행되지 않았다(향후 과제로 명시).
- 공식 코드/프로젝트 페이지: arXiv 페이지, HTML 전문, "SCOUT semantic scene coverage uncertainty traversal code" 웹 검색 모두에서 공개 저장소나 프로젝트 페이지를 찾지 못했다. 논문은 코드 대신 보충 영상 링크(https://bit.ly/4mJgI5T)만 제공한다. 동료의 "코드 없음" 판단은 직접 확인 결과와 일치한다. (검색 중 이름이 같은 무관한 GitHub 저장소 robot-learning-freiburg/scout — "Relational Semantic Reasoning on 3D Scene Graphs for Open World Interactive Object Search" 논문의 코드 — 가 발견되었으나 이 논문과는 다른 프로젝트다.)

## 7. 원문 기반 핵심 문장
> "Robots that operate over extended periods should not merely visit space; they should progressively understand it."

> "[SCOUT] incrementally builds an uncertainty-aware 3D scene graph whose nodes maintain fused geometry and posterior beliefs over open-vocabulary object labels, while edges encode structural relations such as on, inside, belong, and next to."

> "An uncertainty-guided planner selects viewpoints by balancing expected semantic certainty gain, geometric coverage gain, and travel cost, enabling robots to revisit ambiguous objects and explore unseen areas."

> "S_final(v) = (w_cert S_cert(v) + w_cov S_cov(v)) / S_travel(v)" (Section II-A2)

> "UGT consumes the current graph 𝒢_t together with an a priori 2D occupancy map ℳ from prior LiDAR scanning, with free and occupied cells."

> "Future work will focus on comprehensive evaluations, improving the efficiency and convergence of the system, and running validations in real-world robotic deployments."
