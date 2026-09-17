# HEAL: An Extensible Framework for Open Heterogeneous Collaborative Perception

## 메타데이터
- categories: Pyramid Fusion 통합 특징 공간, Backward Alignment 신규 에이전트 정렬, Open Heterogeneous Collaborative Perception, BEV 기반 다중 에이전트 인지 융합
- domain: [[협력 인지]]
- source: Lu, Yifan, Hu, Yue, Zhong, Yiqi, Wang, Dequan, Wang, Yanfeng, Chen, Siheng. "An Extensible Framework for Open Heterogeneous Collaborative Perception." International Conference on Learning Representations (ICLR), 2024.
- url: https://arxiv.org/abs/2401.13964
- year: 2024
- authors: Yifan Lu, Yue Hu, Yiqi Zhong, Dequan Wang, Yanfeng Wang, Siheng Chen
- venue: International Conference on Learning Representations (ICLR 2024)

## 1. 핵심 요약
- 대부분의 기존 collaborative perception 연구는 모든 에이전트가 동일한 센서·모델을 쓰는 homogeneous 상황을 가정하지만, 실제로는 새로운 이종(heterogeneous) 에이전트 타입이 계속 등장하며 기존 에이전트와 협업할 때 domain gap이 발생한다.
- 논문은 이를 "open heterogeneous" 문제로 정의하고, 원문 표현대로 "how to accommodate continually emerging new heterogeneous agent types into collaborative perception, while ensuring high perception performance and low integration cost?"를 핵심 질문으로 제시한다.
- HEAL(HEterogeneous ALliance)은 (1) 초기 homogeneous 에이전트들로 multi-scale foreground-aware Pyramid Fusion network를 학습해 통합 특징 공간(unified feature space)을 먼저 구축하고, (2) 이후 새로운 이종 에이전트가 등장하면 이미 구축된 Pyramid Fusion·검출 head는 고정한 채 새 에이전트의 encoder만 개별적으로 학습시켜 통합 공간에 정렬(backward alignment)하는 2단계 프레임워크다.
- 더 다양한 센서 조합을 담은 대규모 시뮬레이션 데이터셋 OPV2V-H를 새로 공개했고, OPV2V-H·DAIR-V2X 두 데이터셋 실험에서 SOTA 방법들을 성능으로 능가하면서 3개의 신규 에이전트 타입을 통합할 때 학습 파라미터를 91.5% 절감했다.

## 2. 문서 목적
- 해결하려는 문제: collaborative perception 시스템에 새로운 센서 모달리티·모델을 가진 에이전트가 계속 추가될 때, 매번 전체 시스템을 이종 조합에 맞춰 재설계·재학습하지 않고도 높은 인지 성능과 낮은 통합 비용으로 확장할 수 있는 방법이 없다는 문제.
- 기술적 목표: 통합 BEV 특징 공간을 먼저 구축한 뒤, 신규 에이전트는 그 공간에 "정렬"만 시키는 방식으로 collaborative perception 프레임워크의 확장성(extensibility)을 확보하는 것.
- 다루는 범위: Pyramid Fusion 네트워크 설계, backward alignment 학습 절차, 신규 데이터셋 OPV2V-H 구축, OPV2V-H/DAIR-V2X 상에서의 성능·학습비용·강건성(pose noise, feature compression) 실험, ablation study.

## 3. 핵심 개념 상세

### Open Heterogeneous Collaborative Perception
- 원문 표현: "how to accommodate continually emerging new heterogeneous agent types into collaborative perception, while ensuring high perception performance and low integration cost?"
- 정의: 협업 인지 시스템에 참여하는 에이전트들의 센서 종류·모델 구조가 처음부터 고정되어 있지 않고, 시간이 지나며 이전에 본 적 없는 모달리티·모델을 가진 새 에이전트가 계속 유입되는 상황을 다루는 문제 설정.
- 역할: 기존 homogeneous collaborative perception 연구와의 차별점을 규정하는 논문의 핵심 문제 프레이밍이며, 이후 제안하는 2단계 학습 구조(Collaboration Base Training + backward alignment)의 존재 이유가 된다.

### Collaboration Base Training과 Pyramid Fusion Network
- 원문 표현(논문 자체 용어, 정의 부분): 초기 homogeneous 에이전트 집합을 "collaboration base"로 지정하고 이들로 feature-level collaborative perception network를 학습해 "a robust unified feature space for all agents"를 만든다고 서술한다.
- 정의: 여러 스케일(BEV 해상도)에서 ResNeXt 계열 레이어로 특징을 처리하고, 각 스케일마다 foreground estimator가 만든 confidence map을 softmax로 정규화해 융합 가중치로 쓰는 multi-scale foreground-aware fusion 네트워크. 손실 함수는 검출 손실에 각 스케일의 foreground map에 대한 focal loss를 더한 형태다.
- 역할: 이후 새 에이전트가 정렬해야 할 "기준 좌표계" 역할의 통합 특징 공간을 초기 homogeneous 에이전트들만으로 먼저 구축하는 1단계 학습이다. 이 통합 공간과 뒤이은 detection head는 2단계(backward alignment)에서 그대로 고정된다.

### Backward Alignment
- 원문 표현: "With the pretrained Pyramid Fusion module and the detection head established as the back-end and fixed, the training process naturally evolves into adapting the front-end encoder f_encoder[n1](·) to the back-end's parameters, thereby enabling new agent types to align with unified space."
- 정의: 1단계에서 학습이 끝난 Pyramid Fusion 네트워크와 검출 head를 "back-end"로 고정한 뒤, 새로운 이종 에이전트의 encoder(front-end)만 그 back-end의 파라미터에 맞춰 적응시키는 방향으로 학습을 진행하는 절차. 새 encoder가 만든 특징을 고정된 Pyramid Fusion·head에 통과시켜 나온 예측을 기존 검출 손실(및 foreground supervision)로 역전파하되, 업데이트되는 것은 새 encoder 파라미터뿐이다.
- 역할: 신규 에이전트가 참여할 때마다 전체 다중 에이전트 시스템을 함께 재학습하지 않고, 새 에이전트 하나만 단독으로(개별 학습) 통합 공간에 맞춰 넣을 수 있게 하는 HEAL의 핵심 확장 메커니즘이다. 논문은 이 방식이 "extremely low training costs and high extensibility"를 제공한다고 명시한다.

### BEV 기반 통합 특징 공간
- 정의: 서로 다른 센서(LiDAR, 카메라)와 모델이 만들어낸 특징을 같은 Bird's-Eye-View 격자 좌표계·채널 차원으로 투영해 공유하는 표현.
- 역할: 이종 encoder들이 서로 다른 원본 입력(포인트클라우드 vs 이미지)에서 출발하더라도 공통된 BEV 좌표·해상도([0.4m, 0.4m] 격자, 64채널)로 결과를 맞추게 함으로써 Pyramid Fusion·backward alignment가 동일한 인터페이스로 동작할 수 있게 하는 전제 조건이다. 단, 이는 곧 이 프레임워크가 BEV 특징을 낼 수 없는 모델(keypoint 기반 LiDAR 검출기 등)에는 추가 작업 없이 바로 적용되지 않는다는 한계로도 이어진다.

## 4. 구조 및 흐름
1. **1단계 (Collaboration Base Training)**: 초기 homogeneous 에이전트 집합(예: 64채널 LiDAR + PointPillars 에이전트들)으로 multi-scale foreground-aware Pyramid Fusion network와 검출 head를 end-to-end로 함께 학습해 통합 BEV 특징 공간과 그 위의 검출기를 확립한다.
2. **2단계 (Backward Alignment, 신규 에이전트 개별 통합)**: 이전에 없던 모달리티·모델을 가진 새 에이전트가 등장하면, 1단계에서 만든 Pyramid Fusion과 검출 head를 고정하고 새 에이전트의 encoder만 그 고정된 back-end에 맞춰 개별적으로(단일 에이전트 데이터만으로) 학습시킨다.
3. **모달리티/모델 조합**: 실험에서 사용한 에이전트 타입은 L_P(x)(x채널 LiDAR + PointPillars), L_S(x)(x채널 LiDAR + SECOND), C_E(x)(카메라, 높이 x px, Lift-Splat + EfficientNet 백본), C_R(x)(카메라, 높이 x px, Lift-Splat + ResNet50 백본) 네 계열이며, 예컨대 L_P(64), C_E(384), L_S(32), C_R(336) 같은 구체 조합이 실험에 쓰였다. 모든 encoder는 [0.4m, 0.4m] BEV 격자·2배 다운샘플·64채널 특징으로 출력을 맞춘다.
4. **데이터셋**: (a) OPV2V-H — 이 논문이 새로 구축한 대규모 시뮬레이션 데이터셋으로 OpenCDA/CARLA 기반이며, 에이전트당 3종 LiDAR(16/32/64채널), 4대 RGB 카메라(800×600), 4대 depth 카메라를 갖추고 프레임당 2~7개 에이전트가 등장한다(총 10,524 샘플, train/val/test = 6374/1980/2170). (b) DAIR-V2X — 실제 도로 데이터로, 차량(40채널 LiDAR)과 노변 장치(300채널 LiDAR) 각각에 카메라(1920×1080)가 달린 약 9K 프레임 규모다.
5. **평가**: 완전 이종(4개 에이전트 타입) 설정에서 HEAL을 no-fusion, late fusion과 F-Cooper, DiscoNet, AttFusion, V2X-ViT, CoBEVT, HM-ViT 등 기존 collaborative perception 방법과 비교하고, 학습 파라미터·FLOPs·메모리·추론 처리량 등 통합 비용도 함께 측정한다. 추가로 pose noise(Gaussian σ_p, σ_r)에 대한 강건성과, autoencoder 기반 32배 특징 압축 시의 성능 저하도 검증한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| HEAL은 완전 이종(4개 에이전트 타입) 설정에서 기존 SOTA를 성능으로 능가한다 | OPV2V-H Table 2에서 HEAL이 AP50=0.894/AP70=0.813으로, 최고 baseline인 HM-ViT(AP50=0.876/AP70=0.755) 대비 AP50 +2.1%p, AP70 +7.6%p 우세; no-fusion(AP50=0.748/AP70=0.606), late fusion(AP50=0.834/AP70=0.685)보다도 높음 |
| Backward alignment로 신규 에이전트를 통합하면 학습 비용이 크게 줄면서도 확장성이 높다 | 3개의 신규 에이전트 타입을 통합할 때 학습 파라미터 91.5% 절감(abstract 명시), OPV2V-H 실험에서 최종 파라미터 수 HEAL 7.15M vs HM-ViT 83.34M, FLOPs 79.5% 감소, 피크 메모리 89.8% 감소, 추론 처리량 2.88배 향상; DAIR-V2X(L_P(40)+L_S(40))에서도 AP50=0.770을 누적 파라미터 11.8M만으로 달성(HM-ViT의 53.9M 대비 78.1% 절감) |
| Pyramid Fusion의 multi-scale·foreground supervision 구조와 backward alignment 각각이 성능에 실질적으로 기여한다 | Ablation에서 AP70 기준 multiscale pyramid 도입 +0.050, foreground supervision 추가 +0.005, backward alignment 도입 +0.181로 최종 모델 AP70=0.813에 도달 — backward alignment의 기여가 가장 크게 보고됨 |
| HEAL은 pose noise·특징 압축 같은 실전 제약에서도 강건성을 유지한다 | Gaussian pose noise(σ_p, σ_r 변화)를 가한 설정에서도 HEAL이 SOTA 수준 성능을 유지하고, autoencoder로 특징을 32배 압축한 상태에서도 다른 baseline들보다 우수한 성능을 유지함 |

## 6. 한계 및 부족한 점
- WebFetch로 arXiv HTML 버전(arxiv.org/html/2401.13964)과 abstract 페이지를 여러 차례 나눠 조회해 확인했으며, 원문 PDF 전체를 한 번에 통째로 확인하지는 못했다(파일 크기 초과로 실패). 표·수식이 많은 절(정확한 손실 함수 전체 수식, 부록의 추가 ablation 등)은 부분적으로만 확인했다.
- 검출 head(f_head)의 구체적 아키텍처(anchor-based 여부 등)는 확인한 범위에서 논문이 명시적으로 특정하지 않았다 — "focal loss for classification and Smooth-L1 loss for regression"이라는 손실 구성만 확인되었고, head 구조 자체는 원문 확인 안 됨.
- 저자 소속 기관은 이번 조회 범위(arXiv abstract 페이지)에서 표시되지 않아 확인하지 못했다.
- 논문은 스스로 명시한 한계로 "The limitation of HEAL is that it requires BEV features, which requires extra effort for some models (e.g., keypoint-based LiDAR detection) to be compatible to the framework."만을 제시하며, 확인한 범위에서는 이 외의 별도 future work 절은 뚜렷하게 확인되지 않았다.
- **핵심 메커니즘이 특정 신경망 구조에 결합된 정도**: backward alignment 자체("새 front-end encoder만 학습하고 back-end를 고정해 통합 공간에 정렬한다"는 절차)는 아키텍처에 비교적 무관한 일반적 학습 패턴으로 보이지만, 그 정렬이 성립하는 전제는 모든 에이전트의 encoder가 동일한 BEV 격자 해상도·채널 수로 특징을 출력한다는 것이다. 즉 HEAL을 "설계 패턴"으로만 재사용하려면 (1) 통합 표현이 BEV 격자여야 하고 (2) 신규 encoder가 그 BEV 격자·채널 규격에 맞춰 출력하도록 설계돼야 한다는 구조적 제약이 따라온다. Pyramid Fusion 자체(ResNeXt 기반 multi-scale foreground fusion)와 backward alignment 절차, PointPillars/SECOND/Lift-Splat 등 구체 encoder 구현은 서로 분리 가능해 보이지만, "BEV 특징 공간으로의 정렬"이라는 전제는 완전히 아키텍처 독립적인 패턴이라기보다 특정 표현 형식(BEV)에 의존하는 절차이며, 저자도 이를 명시적 한계로 인정한다.

## 7. 원문 기반 핵심 문장
> "Collaborative perception aims to mitigate the limitations of single-agent perception, such as occlusions, by facilitating data exchange among multiple agents. However, most current works consider a homogeneous scenario where all agents use identity sensors and perception models. In reality, heterogeneous agent types may continually emerge and inevitably face a domain gap when collaborating with existing agents. In this paper, we introduce a new open heterogeneous problem: how to accommodate continually emerging new heterogeneous agent types into collaborative perception, while ensuring high perception performance and low integration cost? To address this problem, we propose HEterogeneous ALliance (HEAL), a novel extensible collaborative perception framework. HEAL first establishes a unified feature space with initial agents via a novel multi-scale foreground-aware Pyramid Fusion network. When heterogeneous new agents emerge with previously unseen modalities or models, we align them to the established unified space with an innovative backward alignment. This step only involves individual training on the new agent type, thus presenting extremely low training costs and high extensibility. To enrich agents' data heterogeneity, we bring OPV2V-H, a new large-scale dataset with more diverse sensor types. Extensive experiments on OPV2V-H and DAIR-V2X datasets show that HEAL surpasses SOTA methods in performance while reducing the training parameters by 91.5% when integrating 3 new agent types."
