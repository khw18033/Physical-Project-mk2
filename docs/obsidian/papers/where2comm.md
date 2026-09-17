# Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps

## 메타데이터
- categories: Spatial Confidence Map 기반 희소 통신, Confidence-aware Multi-head Attention Fusion, Request Map 기반 Multi-round 통신, Spatial-decouple 통신 그래프 구성
- domain: [[협력 인지]]
- source: Hu, Yue, Fang, Shaoheng, Lei, Zixing, Zhong, Yiqi, Chen, Siheng. "Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps." Advances in Neural Information Processing Systems (NeurIPS), 2022.
- url: https://arxiv.org/abs/2209.12836
- year: 2022
- authors: Yue Hu, Shaoheng Fang, Zixing Lei (Shanghai Jiao Tong University), Yiqi Zhong (University of Southern California), Siheng Chen (Shanghai Jiao Tong University, Shanghai AI Laboratory)
- venue: NeurIPS 2022 (36th Conference on Neural Information Processing Systems)

## 1. 핵심 요약
- Multi-agent collaborative perception은 통신을 통해 서로 다른 에이전트의 인지 정보를 보완하여 성능을 크게 높일 수 있지만, 그 대가로 perception 성능과 통신 대역폭 사이의 근본적인 trade-off가 발생한다. 기존 방법(When2com, V2VNet, DiscoNet, V2X-ViT)은 일단 두 에이전트가 협업하기로 하면 모든 공간 영역의 정보를 동일하게 공유한다고 암묵적으로 가정해 대역폭을 낭비한다.
- Where2comm은 이 문제를 풀기 위해 spatial confidence map을 제안한다. 이는 각 에이전트의 feature map 위에서 각 공간 위치가 "perceptually critical"한 정도(=해당 위치에 물체가 있을 confidence)를 나타내는 맵으로, 이를 이용해 어디를(where) 통신할지를 결정한다.
- Where2comm은 이 confidence map을 기반으로 3개의 핵심 모듈 — spatial confidence generator, spatial confidence-aware communication(메시지 패킹 + 통신 그래프 구성), spatial confidence-aware message fusion(confidence-aware multi-head attention) — 로 구성된 multi-round, multi-modality, multi-agent 프레임워크다.
- 카메라/LiDAR 두 모달리티, 차량/드론 두 종류의 에이전트, OPV2V·V2X-Sim·DAIR-V2X·자체 제작한 CoPerception-UAVs 등 4개 데이터셋에서 3D object detection으로 평가했으며, 기존 SOTA 대비 동일하거나 더 나은 성능을 극단적으로 적은(최대 100,000배 이상) 통신량으로 달성함을 보였다.

## 2. 문서 목적
- 해결하려는 문제: 협업 인지(collaborative perception)에서 "협업하는 두 에이전트는 모든 공간 영역의 정보를 동등하게 공유해야 한다"는 기존 방법들의 암묵적 가정이 초래하는 통신 대역폭 낭비 문제. 실제로는 배경 등 인지에 무관한 영역이 공유 정보의 상당 부분을 차지한다.
- 기술적 목표: "어디를 통신할지(where to communicate)"를 명시적으로 판단하는 spatial confidence map을 설계하고, 이를 message packing(무엇을 보낼지), communication graph construction(누구와 통신할지), message fusion(어떻게 융합할지)에 일관되게 활용하는 통신 효율적 협업 인지 프레임워크를 제시하는 것.
- 다루는 범위: spatial confidence map의 정의와 생성 방식, confidence 기반 sparse 메시지 패킹과 request map을 이용한 multi-round 상호 요청 메커니즘, confidence-aware sparse 통신 그래프 구성, confidence-aware multi-head attention 기반 메시지 융합, 4개 협업 인지 데이터셋(카메라/LiDAR, 차량/드론, 실세계/시뮬레이션)에서의 정량·정성 평가와 localization noise에 대한 강건성 분석.

## 3. 핵심 개념 상세

### Spatial Confidence Map
- 원문 표현: "The spatial confidence generator generates a spatial confidence map from the feature map of each agent. The spatial confidence map reflects the perceptually critical level of various spatial areas. Intuitively, for object detection task, the areas that contain objects are more critical than background areas. ... So we represent the spatial confidence map with the detection confidence map, where the area with high perceptually critical level is the area that contains an object with a high confidence score."
- 정의: k번째 통신 라운드의 feature map \(F_i^{(k)}\)에 대해, detection decoder와 동일한 구조의 generator \(\Phi_{generator}\)를 적용해 얻는 \(C_i^{(k)} = \Phi_{generator}(F_i^{(k)}) \in [0,1]^{H\times W}\) — 즉 "이 위치에 물체가 있을 detection confidence"를 값으로 갖는 픽셀 단위 맵이다. 파라미터 효율을 위해 이 generator는 최종 detection decoder의 classification 파라미터를 재사용한다.
- 역할: 이 맵은 receiver 쪽에서 "인지가 부족한 영역"을 표시하는 것이 아니라, **각 에이전트 자신의 feature map에서 물체가 있을 가능성이 높은(=다른 에이전트를 도울 만한 가치가 있는) 영역**을 표시한다. 즉 "송신자 관점에서 공유할 가치가 있는 영역"을 정량화하는 것이 핵심이며, 이후 message packing·communication graph·message fusion 세 모듈이 모두 이 맵을 공통 근거로 사용한다.

### Request Map과 Spatial Confidence-aware Communication (message packing)
- 원문 표현: "The request map of the ith agent is \(R_i^{(k)} = 1 - C_i^{(k)}\), negatively correlated with the spatial confidence map. ... the low confidence score indicates there could be missing information at that location. Requesting information at these locations from other agents could improve the current agent's detection accuracy."
- 정의: request map은 confidence map의 여집합(1 - C)으로, "이 에이전트가 스스로는 확신하지 못하는(=occlusion 등으로 정보가 부족할 수 있는) 영역"을 나타낸다. 전송되는 sparse feature map은 binary selection matrix \(M_{i \to j}^{(k)}\)로 결정되는데, k=0(최초 broadcast 라운드)에서는 \(\Phi_{select}(C_i^{(k)})\) — 즉 **송신자 자신의 confidence map만으로** 가장 값이 큰(top-b1, 대역폭 예산에 따라 결정) 영역을 고른다. k>0 라운드부터는 \(\Phi_{select}(C_i^{(k)} \odot R_j^{(k-1)})\) — 송신자의 confidence와 이전 라운드에 수신자가 보낸 request map을 원소별로 곱해, "송신자가 확신하면서 동시에 수신자가 요청한" 영역만 선택한다. 선택은 top-k(top-b1) 방식이며 필요 시 outlier 제거·문맥 반영을 위해 Gaussian filter를 추가로 적용한다.
- 역할: 전송 메시지는 \(P_{i\to j}^{(k)} = (R_i^{(k)}, Z_{i\to j}^{(k)})\)로, sparse feature \(Z_{i\to j}^{(k)} = M_{i\to j}^{(k)} \odot F_i^{(k)}\)의 non-zero 값과 인덱스만 전송해 통신량을 낮춘다. Request map은 다음 라운드에 "내가 더 필요로 하는 정보"를 상대에게 알리는 역할을 하고, 실제 전송되는 feature의 선택은 항상 송신자 자신의 confidence가 우선 기준이 된다.

### Spatial Confidence-aware Communication Graph Construction
- 원문 표현: "the necessity of communication between the ith and the jth agents is simply measured by the overlap between the information that the ith agent has and the information that the jth agent needs. ... if there is at least one patch is activated, then we regard the connection is necessary."
- 정의: 최초 라운드(k=0)는 협업을 개시하기 위해 fully-connected 그래프로 시작하고, 이후 라운드부터는 binary selection matrix \(M_{i\to j}^{(k)}\)에 활성화된(1인) 위치가 하나라도 있으면 그 연결을 유지하는 sparse graph \(A^{(k)}\)를 구성한다.
- 역할: 기존 방법들의 fully-connected 그래프(O(N²) 성장)나 When2com의 handshake 기반(해석하기 어려운 global feature 유사도) 방식과 달리, "누구와 통신할지"를 공간 단위로 세분화해(spatial-decouple partially connected) 불필요한 연결을 줄인다.

### Spatial Confidence-aware Message Fusion
- 원문 표현: "the key technical design is to include the spatial confidence maps of all the agents to promote cross-agent attention learning. ... \(W_{j\to i}^{(k)} = \text{MHAW}(F_i^{(k)}, Z_{j\to i}^{(k)}, Z_{j\to i}^{(k)}) \odot C_j^{(k)}\)"
- 정의: transformer 구조의 multi-head attention(MHA)을 공간 위치별로 독립 적용해 여러 에이전트의 feature를 융합하되, attention weight에 (1) 수신한 confidence map \(C_j^{(k)} = 1 - R_j^{(k)}\)과 (2) 센서 간 물리적 거리 기반 sensor positional encoding(SPE)을 추가 prior로 곱한다.
- 역할: confidence가 높은(=물체가 있을 가능성이 높은) feature가 융합 시 더 큰 가중치를 받도록 하며, ablation(Table 2)에서 MHA·SPE·spatial confidence map(SCM) 세 요소 모두 성능을 개선하고 세 요소를 모두 사용했을 때 OPV2V AP@0.50 기준 22.06% 향상됨을 보였다.

### Multi-round Curriculum Training
- 원문 표현: "To adapt to multi-round communication and dynamic bandwidth, we train the model under various communication settings with curriculum learning strategy. We first gradually increase the communication bandwidth and round; and then, randomly sample bandwidth and round to promote robustness."
- 정의: 단일 통신 라운드/고정 대역폭이 아니라 다양한 라운드 수·대역폭 조건에서 curriculum learning으로 학습해, 하나의 학습된 모델이 배포 시 다양한 통신 조건(대역폭 제약, 라운드 수)에 그대로 적응할 수 있게 한다.
- 역할: 손실 함수는 각 라운드 k별로 detection loss(CenterNet 계열 "Objects as Points" 방식)를 모든 에이전트에 대해 합산한 것이며, 이 학습 전략 덕분에 Fig. 3의 "하나의 Where2comm 모델"이 다양한 대역폭에서 곡선 전체를 그릴 수 있다.

## 4. 구조 및 흐름
1. Observation encoder: 각 에이전트의 센서 입력(RGB 이미지 또는 3D point cloud)을 bird's-eye view(BEV) feature map \(F_i^{(0)} \in \mathbb{R}^{H\times W\times D}\)로 인코딩한다. 카메라 입력은 CaDDN(Categorical Depth Distribution Network) 방식으로 픽셀별 깊이 분포를 추정해 2D 이미지 feature를 3D voxel 공간으로 lift한 뒤 BEV로 collapse하고, LiDAR 입력은 3D point를 BEV map으로 discretize한다. 모든 에이전트가 동일한 global BEV 좌표계를 공유한다.
2. Spatial confidence generator: 매 통신 라운드 시작 시 현재 feature map으로부터 confidence map \(C_i^{(k)}\)을 생성한다.
3. Spatial confidence-aware communication: confidence map(및 이전 라운드에 받은 request map)으로 sparse selection matrix를 만들어 압축 메시지(sparse feature + request map)를 패킹하고, 어느 에이전트와 통신할지 sparse graph를 구성해 메시지를 주고받는다.
4. Spatial confidence-aware message fusion: 수신된 메시지들을 confidence-aware multi-head attention으로 융합해 다음 라운드의 feature map \(F_i^{(k+1)}\)을 얻는다. 이 과정을 지정된 통신 라운드 수(K)만큼 반복한다.
5. Detection decoder: 최종 라운드의 feature map을 class(c), 위치(x,y), 크기(h,w), 회전각(cosα, sinα) 7차원 회전 박스로 디코딩한다.
6. 평가에 사용된 구체적 detector 백본은 데이터셋마다 다르며 단일 고정 아키텍처를 강제하지 않는다:
   - **OPV2V**(카메라, vehicle-to-vehicle, OpenCDA+CARLA 시뮬레이션, 12K frame/230K 3D box, 40m×40m 범위): CADDN 기반 detector.
   - **V2X-Sim**(LiDAR, vehicle-to-everything, SUMO+CARLA 시뮬레이션, 10K frame/501K 3D box, 64m×64m 범위): v1.0은 MotionNet 기반, appendix에서 추가 평가한 v2.0은 PointPillars 기반 detector.
   - **DAIR-V2X**(LiDAR, 유일한 실세계 데이터셋, 차량+인프라 2-agent, 원 데이터셋의 카메라 시야 외 라벨 누락 문제를 저자들이 360도 범위로 재라벨링, 201.6m×80m 범위): PointPillars 기반 detector.
   - **CoPerception-UAVs**(카메라, 저자들이 AirSim+CARLA로 co-simulation한 자체 제작 드론 스웜 데이터셋, 131.9K aerial image/1.94M 3D box, 200m×350m 범위): 자신들의 이전 연구 DVDET 기반이며, appendix에는 "CenterNet backbone with DLA-34"로 구체화되어 있다.
7. 비교 baseline: No Collaboration(단일 에이전트, 통신 없음), Late Fusion(검출된 3D box를 직접 교환), When2com(CVPR 2020, handshake 기반 sparse graph), V2VNet(ECCV 2020, fully-connected graph + GNN 기반 multi-round message passing), DiscoNet(NeurIPS 2021, knowledge distillation + MLP 기반 per-location attention), V2X-ViT(ECCV 2022, fully-connected graph + self-attention per-location, heterogeneous multi-agent attention). Where2comm 자신은 confidence-aware sparse feature map + request map을 메시지로, confidence-aware sparse graph를 통신 그래프로, confidence-aware multi-head attention을 융합 방식으로 사용해 세 구성요소 모두에서 기존 방법과 구별된다(논문 Table 1의 구성요소 비교표).

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| Spatial confidence map은 "receiver가 인지 부족한 영역"이 아니라 "sender가 스스로 확신하는(=물체가 있을 가능성이 높은) 영역"을 표시하며, 이를 이용한 선택적 공유가 성능-통신량 trade-off를 근본적으로 개선한다 | \(C_i^{(k)} = \Phi_{generator}(F_i^{(k)})\)는 detection confidence 자체이고, k=0 라운드의 selection은 \(\Phi_{select}(C_i^{(k)})\)만으로 결정된다(수신자의 요청 없이 송신자 confidence만 사용). request map \(R=1-C\)은 다음 라운드에 "내가 요청하는 영역"을 표현하는 별도 신호이며, k>0에서도 실제 선택은 \(C_i \odot R_j\)로 송신자 confidence가 항상 게이팅 조건에 포함된다 |
| Where2comm은 기존 SOTA와 동일하거나 더 나은 성능을 훨씬 적은 통신량으로 달성한다 | Section 5.2: "achieves the same detection performance of previous state-of-the-arts with extremely less communication volume: 5128 times less on CoPerception-UAVs, more than 100K times less on OPV2V, 55 times less on V2X-Sim, 105 times less on DAIR-V2X." 또한 동일 통신량 기준으로는 "improves the SOTA performance by 7.7% on DAIR-V2X, 6.62% on CoPerception-UAVs, 25.81% on OPV2V, 1.9% on V2X-Sim"(AP@0.50 기준) |
| Abstract에 명시된 대표 수치: OPV2V에서 100,000배 이상 낮은 통신량으로도 DiscoNet·V2X-ViT를 능가 | "it achieves more than 100,000× lower communication volume and still outperforms DiscoNet and V2X-ViT on OPV2V" (Abstract). Fig. 3 caption에는 CoPerception-UAVs에서 "5,000 times less communication volume"으로 When2com을 능가한다는 별도 수치도 제시됨 |
| Multi-round 통신(request map을 통한 상호 요청)은 라운드가 늘어날수록 성능-대역폭 trade-off를 지속적으로 개선한다 | Fig. 4: 통신 라운드를 1→3으로 늘렸을 때 CoPerception-UAVs/OPV2V/V2X-Sim 세 데이터셋 모두에서 동일 대역폭 대비 성능이 꾸준히 향상됨을 보임 |
| Confidence map과 confidence-aware attention은 localization noise에 대한 강건성도 높인다 | 0~0.6m 표준편차의 Gaussian localization noise 실험에서 Where2comm이 When2com/V2VNet/DiscoNet보다 전 구간에서 우수했고, V2VNet은 noise 0.4m 이상, DiscoNet은 0.5m 이상에서 "No Collaboration"보다도 성능이 나빠졌지만 Where2comm은 그렇지 않았다 |
| 메시지 융합의 세 구성요소(MHA, SPE, SCM)가 각각 독립적으로 기여한다 | Table 2 ablation: OPV2V AP@0.50 기준 baseline 34.96 → MHA 추가 38.75 → +SPE 39.82 → +SCM(spatial confidence map) 47.30(22.06% 개선) |

## 6. 한계 및 부족한 점
- pypdf로 arXiv 프리프린트(2209.12836, 24페이지, appendix 포함) 본문 전체를 직접 추출해 확인했다.
- 저자들이 명시한 한계: "The current work focuses on perceptually critical spatial areas. In future, we plan to expand a similar idea to the temporal dimension and determine critical time stamps." — 즉 "언제(when) 통신할지"에 해당하는 시간 축의 선택적 통신은 다루지 않고 향후 과제로 남겼다.
- 저자들은 error bar를 보고하지 않았다: NeurIPS 체크리스트에서 "Did you report error bars? [No] We have not repeated experiments many times to get error bars since experiments of 3d object detection on large scale datasets is time-consuming."라고 명시적으로 밝히고 있어, 논문의 수치들은 단일 실행 결과다.
- DAIR-V2X는 원래 카메라 시야 밖 물체에 라벨이 없는데, 저자들이 이를 360도 범위로 직접 재라벨링(relabel)했다고 밝혀 — 이 재라벨링이 다른 논문들의 DAIR-V2X 평가와 완전히 동일한 라벨 기준이 아닐 수 있다는 점은 본문에서 별도로 검증되지 않는다.
- 평가는 3D object detection이라는 단일 perception task에 한정되며(세그멘테이션 등 다른 task는 다루지 않음), 네 데이터셋 모두 카메라/LiDAR 두 모달리티와 차량/드론 두 에이전트 유형 조합에 한정되어 있다.
- 통신량 지표(log2 scale, 압축 없는 raw float32 기준)는 "extra data/feature/model compression을 고려하지 않는다"고 명시("To compare communication results straightforward and fair, we do not consider any extra data/feature/model compression.")고 있어, 실제 추가 압축 기법과 결합했을 때의 통신량은 별도로 검증되지 않았다.
- 정성적 시각화(Fig. 6, 13, 14)는 소수의 대표 사례(occlusion 상황)에 대한 예시이며, 확인한 본문 범위 내에서 confidence map의 오작동 사례(예: false positive 영역에 높은 confidence가 부여되어 잘못된 정보가 공유되는 경우)에 대한 정량 분석은 제시되지 않는다.

## 7. 원문 기반 핵심 문장
> "To tackle this bottleneck issue, we propose a spatial confidence map, which reflects the spatial heterogeneity of perceptual information. It empowers agents to only share spatially sparse, yet perceptually critical information, contributing to where to communicate."
