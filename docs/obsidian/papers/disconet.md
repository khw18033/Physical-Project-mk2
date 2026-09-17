# Learning Distilled Collaboration Graph for Multi-Agent Perception

## 메타데이터
- categories: Matrix-valued 협력 그래프(DiscoGraph), Teacher-Student Knowledge Distillation 학습, Intermediate Collaboration 기반 특징 공유, V2X-Sim 시뮬레이션 데이터셋
- domain: [[협력 인지]]
- source: Li, Yiming, Ren, Shunli, Wu, Pengxiang, Chen, Siheng, Feng, Chen, Zhang, Wenjun. "Learning Distilled Collaboration Graph for Multi-Agent Perception." Advances in Neural Information Processing Systems (NeurIPS) 34, 2021.
- url: https://arxiv.org/abs/2111.00643
- year: 2021
- authors: Yiming Li (New York University), Shunli Ren (Shanghai Jiao Tong University), Pengxiang Wu (Rutgers University), Siheng Chen (Shanghai Jiao Tong University), Chen Feng (New York University), Wenjun Zhang (Shanghai Jiao Tong University)
- venue: NeurIPS 2021 (Advances in Neural Information Processing Systems 34)

## 1. 핵심 요약
- Multi-agent(V2V) LiDAR 3D object detection에서 성능-대역폭 trade-off를 개선하기 위해, 학습 가능(trainable)하고 pose-aware하며 셀 단위 해상도를 갖는 matrix-valued edge weight를 사용하는 "distilled collaboration graph(DiscoGraph)"를 제안한다.
- 학습 시에는 모든 에이전트의 raw point cloud를 하나의 holistic-view 좌표계로 합쳐 early collaboration을 수행하는 teacher 모델과, 각 에이전트가 자신의 단일 시점(single-view) point cloud만 보고 DiscoGraph를 통해 intermediate collaboration(feature 교환)을 수행하는 student 모델을 함께 두고, student의 "협력 이후(post-collaboration)" feature map이 teacher의 대응 feature map을 따라가도록 KL-divergence 기반 knowledge distillation loss로 정규화한다.
- teacher와 student는 서로 다른 두 개의 개별 학습된 네트워크지만 인코더/디코더/헤더의 아키텍처 자체는 사실상 동일한 backbone(MotionNet 계열 encoder-decoder)을 공유한다. teacher가 구조적으로 더 크거나 다른 네트워크가 아니라, "입력 범위(holistic-view vs single-view)"와 "협력 시점(early vs intermediate)"만 다른 privileged-information 버전이다.
- 저자들이 CARLA+SUMO로 직접 구축한 V2X-Sim 1.0(nuScenes 포맷을 따르는 LiDAR 기반 다중 에이전트 3D object detection 데이터셋, 에이전트 2-5대, 10,000 프레임)에서 평가했으며, 추론 시 student만 사용하는 DiscoNet은 When2com/Who2com/V2VNet 대비 더 높은 AP를 얻었고, feature를 최대 64배 압축해도 성능 저하가 크지 않아 우수한 performance-bandwidth trade-off를 보였다.
- Knowledge distillation은 전적으로 오프라인 학습 단계에서만 수행되는 학습 레시피이며, 추론 시에는 teacher가 완전히 제거되고 student(DiscoNet)만 단독 배포된다. 온라인/지속 학습(continual learning) 요소는 본문에서 다루지 않는다.

## 2. 문서 목적
- 해결하려는 문제: intermediate collaboration(중간 feature만 공유하는 방식)은 early collaboration(raw 데이터 전체 공유)보다 대역폭 효율적이지만, 협력 전략(누가 무엇을 누구와 공유할지)을 잘못 설계하면 feature abstraction·fusion 과정에서 정보 손실이 발생해 성능 개선이 제한된다는 문제.
- 기술적 목표: early collaboration(성능은 최고 수준이지만 대역폭 비용이 큰 가상적 상한)의 지식을 teacher로 삼아, intermediate collaboration(대역폭 효율적) student를 knowledge distillation으로 학습시켜, student가 적은 대역폭으로도 teacher 성능에 근접하도록 만드는 것.
- 다루는 범위: DiscoGraph의 3단계 협력 프로세스(neural message transmission → attention(matrix-valued edge weight) → aggregation) 설계, teacher-student knowledge distillation 학습 프레임워크와 손실 함수, V2X-Sim 1.0 데이터셋 구축 절차, LiDAR 기반 차량(vehicle) 3D detection에서의 정량·정성 평가 및 ablation.

## 3. 핵심 개념 상세

### DiscoGraph (Distilled Collaboration Graph)
- 원문 표현: "we propose a distilled collaboration graph (DiscoGraph) to model the collaboration among agents. In DiscoGraph, each node is an agent with real-time pose information and each edge reflects the pair-wise collaboration between two agents. The proposed DiscoGraph is trainable, pose-aware, and adaptive to real-time measurements."
- 정의: 노드 집합 V(각 노드는 실시간 pose를 가진 에이전트)와 학습 가능한 edge 집합 E_Π로 구성된 완전연결 양방향 그래프. 각 방향의 edge weight는 서로 다른 값을 갖는다(같은 두 에이전트라도 j→i와 i→j의 weight가 다름).
- 역할: neural message transmission(S1, 각 에이전트가 BEV 기반 feature map을 다른 에이전트에 전송) → neural message attention(S2, edge encoder Π가 자신의 feature와 수신한 feature를 채널 방향으로 concat한 뒤 1×1 conv 4개로 매트릭스 형태의 edge weight를 산출, 셀별 softmax로 정규화) → neural message aggregation(S3, 정규화된 weight로 feature map을 가중합)의 3단계로 구성되며, 이 전체 과정 M_{G_Π}가 협력 이후 feature map H^s_i를 만든다.

### Teacher-Student Knowledge Distillation Framework
- 원문 표현: "we propose a teacher-student framework to train DiscoGraph via knowledge distillation. The teacher model employs an early collaboration with holistic-view inputs; the student model is based on intermediate collaboration with single-view inputs. Our framework trains DiscoGraph by constraining post-collaboration feature maps in the student model to match the correspondences in the teacher model."
- 정의: teacher는 모든 M개 에이전트의 point cloud를 global coordinate에서 합친 holistic-view point cloud X = A(ξ1∘X1, ..., ξM∘XM)를 각 에이전트의 pose로 되돌려 student와 동일한 좌표계·해상도로 crop한 뒤, 별도로 먼저 detection loss만으로 학습된다("we train the teacher model separately"). student는 teacher가 학습을 마친 상태에서 detection loss와 KD loss를 함께 최소화하며 학습된다.
- 손실 함수: L_s = Σ_i (L_det(Y^s_i, Ŷ^s_i) + λ_kd·L_kd(H^s_i, H^t_i) + λ_kd·L_kd(M^s_i, M^t_i)), 여기서 L_kd는 셀 단위(¯K×¯K개) feature 벡터에 softmax를 취한 뒤 KL divergence를 합산한 값이며 λ_kd = 10^5로 설정. 즉 KD 대상은 "협력 이후" 인코더 출력 feature map(H)과 디코더 출력 feature map(M)이며, 최종 detection 출력(분류/회귀 결과) 자체는 KD가 아니라 일반 detection loss로만 감독된다.
- 역할: "Intuitively, the feature map of the teacher model {H^t_i} would be the desired output of the collaboration graph process M_{G_Π}(·). Therefore, we constrain all the post-collaboration feature maps in the student model to match the correspondences in the teacher model through knowledge distillation." — 이 정규화는 student의 encoder Θ^s와 edge-weight encoder Π를 함께 역전파로 조정하여, "어떻게 협력해야 teacher 수준의 표현이 나오는지"를 간접적으로 학습시킨다.

### Matrix-valued Edge Weight
- 원문 표현: "we propose a matrix-valued edge weight in DiscoGraph, where each element reflects the inter-agent attention at a specific spatial region, allowing an agent to adaptively highlight the informative regions." / "previous works generally consider a scalar-valued edge weight to reflect the overall collaboration strength between two agents; while we consider a matrix-valued edge weight W_{j→i} ∈ R^{¯K×¯K}."
- 정의: When2com·Who2com·V2VNet 등 기존 방법은 두 에이전트 사이의 협력 강도를 스칼라 하나로 표현하는 반면, DiscoGraph는 32×32(¯K×¯K) 크기의 매트릭스로 표현해 BEV feature map의 각 셀(공간 위치)마다 독립적인 attention 값을 갖는다.
- 역할: 에이전트가 자기 시야에서 정보가 부족한 특정 공간 영역만 선택적으로 다른 에이전트에게 강하게 요청하고, 이미 확보된 영역에는 낮은 attention을 부여하도록 만든다(Fig. 5에서 가려지거나 먼 영역에서 다른 에이전트의 weight가 밝게, 자기 자신의 weight는 어둡게 나타남을 시각적으로 확인).

### V2X-Sim 1.0 데이터셋
- 원문 표현: "we build V2X-Sim 1.0, a new large-scale multi-agent 3D object detection dataset in autonomous driving scenarios based on CARLA and SUMO co-simulation platform." / "V2X-Sim 1.0 follows the same storage format of nuScenes."
- 정의: SUMO(교통 흐름 시뮬레이션)와 CARLA(자율주행 시뮬레이터)를 co-simulation으로 결합해 만든 LiDAR 기반 다중 에이전트 3D object detection 데이터셋. Town05(격자형 다차선 도심 지도)에서 500대 차량을 스폰해 5분 로그를 기록하고, 서로 다른 교차로에서 100개 scene을 추출했다. 각 scene은 20초(100프레임, 0.2초 간격)이며 scene마다 2-5대(M=2,3,4,5)의 차량을 협력 에이전트로 무작위 선정한다. 총 10,000 프레임이며 8,000/900/1,100 프레임을 train/val/test로 분할(training 23,500 샘플, test 3,100 샘플). LiDAR는 32채널·20Hz 회전·최대 탐지거리 70m로 시뮬레이션되었다.
- 역할: "there is no public dataset to support the research on multi-agent 3D object detection in self-driving scenarios"라는 공백을 메우기 위해 저자들이 직접 제작한 벤치마크이며, 논문의 모든 정량 평가(Table 1-3, Fig. 4-7)가 이 데이터셋 위에서 이루어진다. car(vehicle) 카테고리 3D detection만 보고하고, bicycle/person 검출은 후속 과제로 남겨두었다.

### Backbone: MotionNet 기반 Encoder-Decoder
- 원문 표현(Appendix II): "We use the main architecture of MotionNet [32] as our backbone, which uses an encoder-decoder architecture with skip connection. The input BEV map's dimension is (c,w,h) = (13, 256, 256)."
- 정의: student/teacher 모두 point cloud를 [-32,32]×[-32,32]×[-3,2]m 영역에서 0.25m(가로/세로)×0.4m(높이) voxel로 양자화해 256×256×13 크기의 BEV pseudo-image로 만든 뒤, 4단계 conv block(채널 13→32→64→128→256→512, 해상도 256→128→64→32→16)으로 이루어진 인코더에 통과시킨다. 인코더 최종 출력(32×32×256 근방)이 feature map F_i이며, skip connection을 가진 대칭 구조의 디코더가 이를 다시 원 해상도로 복원한다. edge encoder(Π)는 concat된 512채널 입력을 1×1 conv 4개(512→128→32→8→1)로 축소해 매트릭스 edge weight를 산출한다.
- 역할: teacher와 student는 이 동일한 backbone 구조를 각각 독립적으로(가중치 공유 없이) 학습하며, 차이는 오직 입력이 holistic-view(teacher)인지 single-view(student, DiscoGraph 협력 포함)인지에 있다. 즉 teacher는 "구조적으로 더 큰 네트워크"가 아니라 "raw 데이터 접근 범위가 더 넓은 동일 구조의 네트워크"다.

## 4. 구조 및 흐름
1. **Student 파이프라인**: 각 에이전트 i의 point cloud X_i를 BEV map B_i로 변환 → 공유 encoder Θ^s로 feature map F^s_i 추출 → feature compression(1×1 conv autoencoder, 채널 방향 압축, 전송 대역폭 절감) → DiscoGraph의 협력 프로세스(S1 message transmission, S2 matrix-valued edge weight 계산, S3 가중 aggregation)로 협력 후 feature map H^s_i = Σ_j W_{j→i}⊙F^s_{j→i} 생성 → 공유 decoder Ψ^s(skip connection 포함 4단계 up-sampling) → header Φ^s(분류/회귀 두 branch)로 detection 출력.
2. **Teacher 파이프라인(학습 시에만 존재)**: 모든 에이전트의 point cloud를 global coordinate로 합쳐 holistic point cloud 생성 → 각 에이전트 pose 기준으로 되돌려 student와 동일한 좌표계·해상도로 crop해 정합 → teacher encoder Θ^t → feature H^t_i 추출(이 경우 별도 "협력 그래프" 과정이 없음, 이미 raw 단계에서 모든 정보가 합쳐졌기 때문) → decoder/header로 detection 출력. teacher는 detection loss만으로 별도 사전 학습된다.
3. **Student 학습**: 학습된 teacher를 고정한 상태에서, student를 (a) 자기 local ground-truth에 대한 detection loss와 (b) teacher의 H^t_i, M^t_i를 타깃으로 하는 KD loss(셀별 KL divergence, λ_kd=10^5)를 합산해 공동 학습한다. 이 KD loss가 encoder Θ^s와 edge-weight encoder Π를 함께 정규화한다.
4. **추론(inference)**: teacher는 완전히 폐기되고, 각 에이전트에는 공유 student(=DiscoNet) 가중치만 배포된다. 에이전트들은 feature map을 1회만 교환("DiscoNet only requires one round, suffering less from latency", When2com은 최소 2라운드, V2VNet은 3라운드 필요)해 detection을 수행한다.
5. **평가**: V2X-Sim 1.0 test set에서 AP@IoU 0.5/0.7(car 카테고리)로 no-collaboration lower-bound, early-collaboration upper-bound(teacher와 동일 구성), When2com, Who2com, V2VNet과 비교한다. feature compression autoencoder(최대 64배 압축)로 performance-bandwidth trade-off를 분석하고, edge weight 종류(scalar vs matrix)와 KD 유무에 대한 ablation, 그리고 edge weight 시각화를 통한 정성 평가를 수행한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| DiscoNet(intermediate collaboration)은 기존 intermediate collaboration SOTA보다 우수하다 | Test set AP@0.5/0.7: DiscoNet 60.3/53.9 vs V2VNet 56.8/50.7(+6.2%/+6.3%) vs pose-aware When2com 45.7/41.7(+31.9%/+29.3%); early collaboration(teacher/upper-bound) 63.3/60.2, no-collaboration(lower-bound) 45.8/42.3로 collaboration 자체의 효과(+38.2%/+42.3%)도 함께 확인 |
| Matrix-valued edge weight와 knowledge distillation이 성능 향상의 핵심 요인이다 | Ablation(Table 3): DiscoGraph w/ KD 60.3/53.9 vs w/o KD 57.2/52.3(KD로 +3.1/+1.6 AP, +5.4%/+3.1%); 동일 KD 조건에서 scalar weighted-average는 56.7/50.9로 DiscoGraph보다 낮음. 여러 decoder 레이어(H^s_i, M^s_i{1-4})에 KD 정규화를 적용할수록 성능이 점진적으로 향상(Table 2) |
| Feature compression을 적용해도 성능 저하가 크지 않아 우수한 performance-bandwidth trade-off를 달성한다 | 16배 압축한 DiscoNet(16)이 58.5/53.0으로 비압축 V2VNet(56.8/50.7)보다 여전히 높음; 64배 압축한 DiscoNet(64)는 V2VNet 대비 통신량 192배 절감하면서도 AP@0.5/0.7 모두 우세(Fig. 4) |
| Knowledge distillation은 추론 비용 증가 없이 학습 비용만 소폭 증가시킨다 | KD 적용 시 epoch당(2,000 iteration) 학습 시간이 ~1200s→~1500s로 증가하지만, "during inference, DiscoNet does not need the teacher model anymore and can work alone without extra computations" |

## 6. 한계 및 부족한 점
- pypdf로 arXiv v2 프리프린트(본문+부록 포함 17페이지, arXiv:2111.00643v2)를 직접 읽고 확인했다.
- 저자가 명시한 한계: "DiscoNet has a limitation by assuming accurate pose for each agent, which could be improved by method like [33]" — 모든 에이전트의 pose가 정확히 주어진다고 가정하며, pose 오차 보정은 이 논문의 범위 밖이다.
- 평가가 저자들이 직접 만든 단일 시뮬레이션 데이터셋(V2X-Sim 1.0, CARLA+SUMO 기반)에 한정되며, 확인한 본문 범위 내에서 실세계(real-world) 데이터셋에서의 검증은 다루지 않는다.
- 3D detection 대상은 vehicle(자동차) 카테고리 하나만 보고한다: "we report the results of vehicle detection and leave the bicycle and person detection as the follow-up works."
- 정확한 pose와 잘 동기화된 관측을 가정한다: "we assume each agent is provided with an accurate pose and the perceived measurements are well synchronized" — 통신 지연·패킷 손실·비동기 상황에 대한 강건성은 별도로 다루지 않는다.
- Knowledge distillation은 전적으로 오프라인 학습 단계에서만 수행된다. teacher는 학습 완료 후 완전히 폐기되고, 배포 이후의 온라인 재학습·지속 학습(continual adaptation) 메커니즘은 본문에서 제시되지 않는다.
- Table 1의 원문 레이아웃(체크마크로 Early/Intermediate/Late collaboration 열을 표시)이 PDF 텍스트 추출 과정에서 일부 행의 방법명이 빈칸으로 깨졌으나, 본문 서술의 개선율 수치(예: early collaboration의 +38.2%/+42.3%, late collaboration이 upper-bound를 오히려 저해한다는 서술)와 대조해 표의 수치 자체는 교차검증했다.

## 7. 원문 기반 핵심 문장
> "Our framework trains DiscoGraph by constraining post-collaboration feature maps in the student model to match the correspondences in the teacher model."
