# CoAlign: Robust Collaborative 3D Object Detection in Presence of Pose Errors

## 메타데이터
- categories: Agent-Object Pose Graph Optimization, Hybrid(Late+Intermediate) Collaboration, Uncertainty-aware 3D Detection, Multiscale Intermediate Feature Fusion
- domain: [[협력 인지]]
- source: Lu, Yifan, Li, Quanhao, Liu, Baoan, Dianati, Mehrdad, Feng, Chen, Chen, Siheng, Wang, Yanfeng. "Robust Collaborative 3D Object Detection in Presence of Pose Errors." IEEE International Conference on Robotics and Automation (ICRA), 2023.
- url: https://arxiv.org/abs/2211.07214
- year: 2023
- authors: Yifan Lu, Quanhao Li, Baoan Liu, Mehrdad Dianati, Chen Feng, Siheng Chen(교신저자), Yanfeng Wang (Shanghai Jiao Tong University; Nanjing University; Meta Reality Labs; University of Warwick; New York University; Shanghai AI Laboratory)
- venue: IEEE International Conference on Robotics and Automation (ICRA 2023)

## 1. 핵심 요약
- Multi-agent(V2X) 협업 3D object detection에서 각 에이전트의 localization 모듈이 추정한 6DoF pose에 오차가 있으면 feature/box가 서로 다른 좌표계로 정렬되어(spatial message misalignment) 협업 성능이 단일 에이전트보다 나빠질 수 있는 문제를 다룬다.
- CoAlign은 에이전트들이 각자 검출한 bounding box를 장면의 landmark로 삼아, 여러 에이전트-객체 간 상대 pose 일관성을 강제하는 "agent-object pose graph optimization"으로 feature transform·fusion 이전에 상대 pose를 먼저 보정하고, 이후 multiscale intermediate fusion으로 잔여 오정합을 완화하는 hybrid(late+intermediate) collaboration framework다.
- 이 pose graph 최적화는 학습 파라미터가 전혀 없는 고전적 weighted least-squares 문제로, g2o 라이브러리의 Levenberg-Marquardt solver로 풀리며, 학습·추론 어느 단계에서도 ground-truth pose 감독을 요구하지 않는다.
- PointPillars backbone 기준으로 OPV2V, V2X-Sim 2.0, DAIR-V2X 세 데이터셋에서 σt/σr = 0.0/0.0, 0.2m/0.2°, 0.4m/0.4°, 0.6m/0.6°의 Gaussian pose noise(훈련은 항상 σt=0.2m, σr=0.2° 고정)로 평가했고, DAIR-V2X에서는 동일 noise level의 Laplace 분포로 분포 불일치(generalization)까지 검증했다. 모든 noise level·데이터셋에서 기존 pose-robust 방법(V2VNet(robust), V2X-ViT, FPV-RCNN, MASH 등) 대비 SOTA 성능을 보였고, median relative pose error를 75% 줄였으며 적어도 12% 이상의 검출 성능 향상을 보고한다.

## 2. 문서 목적
- 해결하려는 문제: collaborative 3D detection에서 각 에이전트의 pose 추정치가 부정확할 때 발생하는 feature/box misalignment로 인해, 협업이 오히려 단일 에이전트 성능보다 저하될 수 있는 문제. 기존 방법(V2VNet(robust)의 pose regression, FPV-RCNN의 semantic keypoint correspondence 등)은 훈련 시 ground-truth pose 감독을 요구해 실용성이 떨어진다.
- 기술적 목표: ground-truth pose 감독 없이, 임의 수준(unknown, arbitrary)의 pose error에 강건하게 협업 3D detection 성능을 유지하는 hybrid collaboration framework를 설계하는 것.
- 다루는 범위: agent-object pose graph 모델링·최적화 설계(식 3), uncertainty 추정을 포함한 단일 에이전트 검출기, multiscale intermediate feature fusion, OPV2V/V2X-Sim 2.0/DAIR-V2X에서의 Gaussian·Laplace pose noise 평가와 모듈별 ablation.

## 3. 핵심 개념 상세

### Agent-Object Pose Graph Optimization
- 원문 표현: "we leverage an agent-object pose graph to represent the relations between agents and objects; and then, apply optimization over this graph to achieve pose alignment." / "Since our agent-object pose graph does not use any training parameters in the optimization process, this method has strong generalization capability to adapt to arbitrary levels of pose errors." / "This typical graph optimization (3) can be solved by popular Gaussian-Newton or Levenberg-Marquartdt algorithms."
- 정의: 각 에이전트가 공유한 pose ξ_j와 검출 bounding box로부터, agent 노드 집합 V(agent)와 (여러 에이전트가 보고한 유사 box들을 공간적으로 클러스터링해 얻은) object 노드 집합 V(object)로 이루어진 bipartite graph G(V(agent), V(object), E)를 구성한다. 에이전트가 특정 객체를 검출하면 해당 agent-object 쌍에 edge를 만들고, 그 edge는 j번째 에이전트 시점에서 관측된 k번째 객체의 상대 pose z_jk를 나타낸다. pose consistency error e_jk = z_jk⁻¹ ∘ (ξ_j⁻¹ ∘ χ_k) (χ_k는 object의 pose)가 0이 되도록, 모든 edge에 대해 e_jk^T Ω_jk e_jk의 합을 최소화하는 weighted least-squares 문제(식 3)를 g2o 라이브러리(dense solver + Levenberg-Marquardt, 최대 반복 1000회, SE(2) 상의 edge/vertex)로 푼다. 가중치 Ω_jk = diag(1/σx², 1/σy², 1/σθ²)는 각 box의 uncertainty 추정치로부터 얻는 information matrix다.
- 역할: 이 모듈은 raw point cloud를 직접 정합하는 ICP/registration이 아니라, 이미 검출된 object-level bounding box 대응(agent-object correspondence)만을 제약조건으로 쓰는 sparse graph optimization이다. 논문은 이를 graph-based SLAM과 명시적으로 비교한다: "The proposed agent-object pose graph is similar to the pose graph in graph-based SLAM; however, the former considers the pose of an object from the perspectives of multiple agents at the same time stamp, while the latter one considers the pose of the same agent across multiple time stamps." 즉 SLAM의 pose graph가 동일 에이전트의 여러 시각(timestamp)에 걸친 pose를 정합하는 반면, CoAlign의 pose graph는 같은 시각에 서로 다른 에이전트가 관측한 동일 객체의 pose를 정합한다는 점에서 구조는 유사하나 정합 축이 다르다. 학습 파라미터가 전혀 없는 classical solver이므로 학습 시 보지 못한 pose error 수준에도 재학습 없이 적용 가능하다고 저자는 주장한다.

### Hybrid(Late+Intermediate) Collaboration Framework
- 원문 표현: "we propose a novel hybrid collaboration framework CoAlign, which enables multiple agents to share both intermediate features and single-agent detection results." / "this hybrid collaboration can leverage those bounding boxes detected by agents to be the scene landmarks and correct the relative poses between agents."
- 정의: 논문은 선행연구를 early(raw observation 전송)·intermediate(feature 전송)·late(detection 결과 전송) collaboration으로 구분한 뒤, CoAlign을 F_i,B_i=f_detection(O_i) → {ξ'_j→i}=f_correction({B_j,ξ_j}) → M_j→i=f_transform(F_j,ξ'_j→i) → F'_i=f_fusion({M_j→i}) → B'_i=f_decoder(F'_i)의 5단계(식 2a~2e)로 정식화한다. 즉 late collaboration에서 얻는 detected bounding box(+uncertainty)를 pose correction의 landmark로 사용하고, 그렇게 보정된 pose로 intermediate feature를 정렬해 fusion하는 late+intermediate hybrid 파이프라인이다.
- 역할: pose correction 단계(2b)를 feature transform(2c)·fusion(2d) 앞에 명시적으로 배치함으로써, "관측된 객체를 이용해 pose를 먼저 재보정한 뒤 feature를 fusion한다"는 설계를 구체적인 수식 파이프라인으로 formalize한다.

### Uncertainty-aware Single-Agent Detection
- 원문 표현: "Since we later rely on those boxes to correct the pose errors, messy detection could cause even worse relative poses. The estimated uncertainty of each box can provide beneficial confidence information to rule out undesirable detection." 각 box는 b=(x̂,ŷ,ẑ,l̂,ŵ,ĥ,θ̂,σx²,σy²,σθ²)로 파라미터화된다.
- 정의: PointPillars(grid size 0.4m×0.4m)를 인코더로 사용하는 단일 에이전트 검출기가 box 좌표뿐 아니라 중심 위치의 Gaussian 불확실성(σx²,σy²)과 yaw 각도의 von-Mises 분포 concentration(1/σθ²)까지 함께 추정하도록, ground-truth delta 분포와의 KL divergence 기반 손실(L_x, L_θ)로 학습한다.
- 역할: 이 불확실성 추정치가 pose graph optimization의 edge information matrix Ω_jk로 직접 사용되어, 신뢰도가 낮은 검출이 pose 보정에 미치는 영향을 자동으로 줄인다. Ablation(Table III)에서 uncertainty 모듈 추가가 pose graph만 있을 때보다 noise가 클수록 더 안정적인 성능을 만든다는 것이 확인된다.

### Multiscale Intermediate Feature Fusion
- 원문 표현: "even after the relative pose correction, the misalignment between feature maps might still exist. To further mitigate the effect of pose noises, we adopt a multiscale fusion method, which fuses features at multiple spatial scales."
- 정의: pose 보정 후에도 남는 잔차 오정합을 완화하기 위해, residual downsampling 레이어(레이어 수 2, 채널 128/256)로 여러 공간 해상도의 feature F^(l)_j→i를 만들고, 각 스케일에서 에이전트 차원에 대한 attention 기반 fusion(Fuse(·))을 수행한 뒤 업샘플링·concat(Cat(·))해 최종 feature F'_i를 얻는 모듈.
- 역할: pose graph optimization이 "1차 보정"이라면, 이 모듈은 그 이후 남는 미세 오정합에 대한 학습 기반 "2차 완화" 역할을 한다. 더 세밀한 스케일은 정밀한 기하·의미 정보를, 더 거친 스케일은 pose error에 덜 민감한 정보를 제공한다.

## 4. 구조 및 흐름
1. 각 에이전트가 PointPillars 인코더로 자신의 관측 O_i에서 feature F_i와 uncertainty를 포함한 bounding box B_i를 얻는다(단일 에이전트 detection, 식 2a).
2. 각 에이전트는 자신의 pose ξ_i, 검출 box B_i, feature F_i를 다른 에이전트와 교환한다. i번째 에이전트는 수신한 모든 (pose, box) 쌍으로 bipartite agent-object pose graph G(V(agent), V(object), E)를 로컬에서 구성한다(공간적으로 유사한 box들을 클러스터링해 object 노드를 생성).
3. g2o 기반 weighted least-squares(Levenberg-Marquardt, dense solver, 최대 반복 1000회)로 pose consistency error(식 3)를 최소화해 보정된 상대 pose ξ'_j→i를 계산한다(식 2b; ego agent의 pose는 고정하고 나머지 agent·object pose를 갱신).
4. 보정된 pose로 다른 에이전트의 feature map을 ego 좌표계로 warp(transform)하고(식 2c), multiscale intermediate fusion으로 여러 공간 해상도에서 feature를 집계한다(식 2d).
5. 융합된 feature를 decoder에 통과시켜 최종 검출 결과 B'_i를 얻는다(식 2e). 학습은 검출 손실 L_total(분류·회귀·uncertainty 항 포함, Adam, lr 0.001/0.002, batchsize 4, epoch 30)로만 이루어지며 pose graph 최적화 자체는 학습 파라미터가 없는 별도 solver 단계다.
6. 평가: OPV2V/V2X-Sim 2.0/DAIR-V2X에서 σt/σr = 0.0/0.0, 0.2m/0.2°, 0.4m/0.4°, 0.6m/0.6°의 Gaussian pose noise(훈련은 항상 σt=0.2m, σr=0.2° 고정)와 DAIR-V2X에서 동일 level의 Laplace noise로 AP@0.5/0.7을 측정하고, F-Cooper·V2VNet·DiscoNet·MASH·FPV-RCNN·V2VNet(robust)·V2X-ViT와 비교하며 모듈별 ablation을 수행한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| agent-object pose graph optimization은 상대 pose error를 큰 폭으로 줄인다 | "the proposed agent-object pose graph optimization achieves 75% relative pose error reduction (measured at the median value)"; Fig.6 ablation에서 "The median errors are reduced to 25% of the original." |
| CoAlign은 ground-truth pose 감독 없이도 기존 pose-robust 방법들을 능가한다 | Table I: OPV2V AP@0.7에서 noise 0.0/0.2/0.4/0.6 전 구간 CoAlign 0.912/0.900/0.889/0.868로 V2X-ViT(0.856/0.851/0.841/0.823), V2VNet(robust)(0.854/0.848/0.837/0.826)보다 높음; "the proposed CoAlign achieves at least 12% performance improvement in the task of collaborative 3D object detection with pose error existence, compared with other methods." |
| pose graph, uncertainty, multiscale fusion 세 모듈이 모두 강건성에 기여한다 | Table III ablation(OPV2V, AP@0.7): pose graph만 추가 시 noise 0.0/0.2/0.4/0.6에서 0.907/0.490/0.275/0.239로 noise가 커질수록 급락하지만, uncertainty를 더하면 0.899/0.814/0.751/0.657로, multiscale fusion까지 결합하면 0.912/0.900/0.889/0.868로 가장 강건해진다. |
| 훈련 시 보지 못한 noise 분포(Laplace)에도 일반화된다 | Table II: DAIR-V2X에서 Gaussian noise(σt=0.2m, σr=0.2°)로만 학습했음에도 Laplace test noise 0.0~0.6(m/°) 전 구간에서 CoAlign(AP@0.7: 0.604/0.585/0.573/0.566)이 V2X-ViT(0.531/0.527/0.521/0.517), V2VNet(robust)(0.486/0.481/0.476/0.469) 등보다 높다. |

## 6. 한계 및 부족한 점
- pypdf로 arXiv 프리프린트(v3, 2023-03-03, 7페이지) 본문 전체를 직접 확인했다.
- box 검출은 yaw만 회전 파라미터로 사용해 pose를 2D로 단순화한다: "since box detection only has yaw angle for rotation measurement, we simplify each pose ξi = (xi,yi,θi) in 2D space." 따라서 pitch/roll이나 z축 pose error를 포함한 완전한 6DoF pose error에 대한 강건성은 본문에서 직접 검증되지 않는다.
- object 노드는 "spatially clustering similar boxes received from all the agents"로 얻는데, 이 클러스터링 자체가 잘못되면(서로 다른 물체가 하나로 묶이거나 동일 물체가 여러 노드로 나뉘면) pose graph correspondence 품질이 저하될 수 있으나, 클러스터링 오류에 대한 정량적 민감도 분석은 본문에서 확인되지 않는다.
- 평가는 LiDAR 기반 3D detection에 한정되며, 저자 스스로 "CoAlign does not rely on certain data modality and can be applied to camera-based 3D detection as well. In future works, we will extend our method on multimodal data."라고 명시해, 카메라 기반·멀티모달 적용은 검증되지 않은 향후 과제로 남아 있다.
- pose graph solver(g2o, Levenberg-Marquardt, 최대 반복 1000회)의 런타임 오버헤드나 에이전트 수 N에 따른 계산 복잡도 스케일링은 본문에서 정량적으로 보고되지 않는다(학습 시간은 "CoAlign converges within 10 hours on OPV2V dataset with one RTX 3090"으로만 언급되며 이는 detection 학습 시간이고 pose graph solver 자체의 추론 지연은 별도로 제시되지 않는다).
- V2X-Sim 2.0/OPV2V/DAIR-V2X 세 데이터셋 모두 차량 간(V2V) 또는 차량-인프라(V2I) 시나리오이며, 로봇 팔·이동형 다중 로봇 등 자율주행 이외 도메인에서의 검증은 본문 범위에 포함되지 않는다.

## 7. 원문 기반 핵심 문장
> "The proposed solution relies on a novel agent-object pose graph modeling to enhance pose consistency among collaborating agents. Furthermore, we adopt a multi-scale data fusion strategy to aggregate intermediate features at multiple spatial resolutions."

> "Since our agent-object pose graph does not use any training parameters in the optimization process, this method has strong generalization capability to adapt to arbitrary levels of pose errors."

> "The proposed agent-object pose graph is similar to the pose graph in graph-based SLAM; however, the former considers the pose of an object from the perspectives of multiple agents at the same time stamp, while the latter one considers the pose of the same agent across multiple time stamps."

> "we adopt the general graph optimization(g2o) library. Both edges and vertices are in SE(2). Here we select the dense solver for incremental equations and Levenberg-Marquartdt algorithms for iterative optimiztion with max iteration time 1000."
