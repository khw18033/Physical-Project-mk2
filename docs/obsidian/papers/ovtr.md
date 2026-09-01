# OVTR: End-to-End Open-Vocabulary Multiple Object Tracking with Transformer

## 메타데이터
- categories: [[Category Information Propagation]], [[Attention Isolation]], [[Dual-branch Decoder]], [[Multimodal Alignment]]
- domain: [[Multiple Object Tracking]], [[Open-Vocabulary 인지]]
- source: Jinyang Li, En Yu, Sijia Chen, Wenbing Tao, "OVTR: End-to-End Open-Vocabulary Multiple Object Tracking with Transformer", ICLR 2025.
- url: https://arxiv.org/abs/2503.10616
- year: 2025
- authors: Jinyang Li et al.
- venue: ICLR 2025

## 1. 핵심 요약
- OVTR은 학습에 사용되지 않은 카테고리(novel category)까지 일반화하는 open-vocabulary multiple object tracking을 end-to-end Transformer 구조로 수행하는 최초의 tracker라고 밝히고 있다.
- 동작(motion), 외관(appearance), 카테고리 정보를 하나의 query 기반 파이프라인에서 동시에 모델링하며, tracking-by-detection과 별도의 open-vocabulary detector를 결합하는 기존 tracking-by-OVD 방식과 달리 detector에 대한 의존과 후처리를 없앴다.
- Category Information Propagation(CIP), Attention Isolation, Dual-branch Decoder, 이미지-텍스트 교차주의 기반 multimodal alignment를 핵심 구성요소로 제시하고, TAO 데이터셋에서 novel category 기준 OVTrack 대비 TETA를 향상시켰다고 보고한다.
- 경량화 버전인 OVTR-Lite는 category isolation 전략과 KL divergence 연산을 제거해 추론 속도를 크게 높이면서도 경쟁력 있는 정확도를 유지한다고 보고한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 open-vocabulary MOT은 tracking과 open-vocabulary detection(OVD)을 프레임 단위로 독립적으로 수행해 결합("cobbled together")하는 구조이며, 매 프레임 독립적인 분류로 카테고리 인식이 불안정하고 이전 프레임의 예측을 재활용하지 못한다. 또한 appearance 기반 연관(association)은 OVMOT의 다양한 환경에 적응하기 어렵고, 방대한 object embedding 사전 추출로 인한 전처리 시간 소모가 크다.
- 기술적 목표: 분류(classification)와 추적(tracking)이 서로 협력하도록 하나의 query 기반 end-to-end Transformer 프레임워크에서 카테고리 정보를 다중 프레임에 걸쳐 전파하고, 이를 통해 anchor 생성이나 대규모 사전 embedding 추출 같은 hand-designed 전처리 없이 open-vocabulary tracking을 수행하는 것.
- 다루는 범위: 아키텍처 설계(인코더의 이미지-텍스트 교차주의 융합, 이중 분기 decoder), CIP 및 attention isolation을 통한 다중 프레임 카테고리 정보 관리, TAO 데이터셋에서의 novel/base category 평가, KITTI 데이터셋으로의 전이 평가, OVTR-Lite를 통한 속도-정확도 trade-off 분석을 포함한다.

## 3. 핵심 개념 상세
### Category Information Propagation
- 원문 표현: "We leverage the iterative nature of the query-based method and propose the category information propagation (CIP) strategy to aggregate tracked object information, thereby reinforcing category priors throughout multi-frame predictions."
- 정의: 현재 프레임의 track query 출력을 다음 프레임 decoder의 입력으로 재사용해 카테고리 정보를 프레임 간에 누적·전파하는 전략이다. 위치 정보(P)와 콘텐츠 정보(C)를 분리해 전파하며, 수정된 형태로 `C^(t+1)_tr = FFN(FFN(O_r, O^(*t)_img), C^t_*)` 식으로 갱신된다고 설명된다.
- 역할: 매 프레임 독립적으로 분류를 수행하던 기존 tracking-by-OVD 방식의 카테고리 불안정 문제를 완화하고, query 기반 방법의 반복적 구조를 활용해 다중 프레임에 걸친 카테고리 사전(prior)을 강화한다.

### Attention Isolation
- 원문 표현: Category Isolation Strategy, Content Isolation Strategy
- 정의: 서로 다른 query 간의 불필요한 정보 간섭을 self-attention 단계에서 차단하는 두 가지 마스킹 전략이다. Category Isolation Strategy는 각 query 쌍의 카테고리 점수 분포 차이를 KL divergence로 계산해 임계값(τ_isol)을 초과하면 self-attention에서 해당 관계를 마스킹하며, Content Isolation Strategy는 첫 프레임의 detect query와 이후 프레임의 track query 사이의 콘텐츠 격차로 인한 간섭을 억제하기 위해 decoder의 첫 번째 layer에만 적용된다.
- 역할: 카테고리가 다른 query끼리, 그리고 성격이 다른 detect query와 track query끼리 서로의 표현을 오염시키지 않도록 격리해 open-vocabulary 인식과 추적이 조화롭게 동작하도록 보장한다.

### Dual-branch Decoder
- 원문 표현: OFA Branch (Object Feature Alignment), CTI Branch (Category Text Interaction)
- 정의: decoder를 두 개의 분기로 구성한 구조다. OFA Branch는 정렬된 query를 CLIP 이미지 embedding에 맞추어 CLIP 이미지 인코더의 지식을 증류하고 box head로 instance-level 특성을 보장하며, alignment loss `L_align = (1/n·d) Σ(F_align - V_gt)²`로 학습된다. CTI Branch는 텍스트 교차주의(text cross-attention)를 포함해 CLIP 텍스트 embedding과 상호작용하며 open-vocabulary 분류에 특화된 카테고리 정보를 추출한다.
- 역할: 하나의 분기가 시각적 정렬과 일반화 능력을, 다른 분기가 텍스트 기반 카테고리 인식을 담당하도록 역할을 분리해 open-vocabulary 인식과 깊이 있는 멀티모달 상호작용을 동시에 달성한다.

### Multimodal Alignment
- 원문 표현: "We integrated image-to-text and text-to-image cross-attention modules for feature fusion"
- 정의: 인코더 단계에서 이미지-텍스트, 텍스트-이미지 양방향 교차주의 모듈로 이미지 특성과 텍스트 특성을 사전 융합하고, decoder의 OFA Branch 출력 F_align을 ground-truth CLIP embedding V_gt와 직접 정렬하는 메커니즘이다.
- 역할: 이미지와 텍스트 두 모달리티가 서로를 강화하도록 만들고, OFA Branch의 정렬된 query가 암묵적으로 같은 카테고리의 텍스트 embedding과도 정렬되게 함으로써 별도의 대규모 사전 embedding 추출 없이도 open-vocabulary 분류 성능을 확보한다.

## 4. 구조 및 흐름
1. 인코더에서 backbone 이미지 특성과 CLIP 텍스트 특성을 추출하고, image-to-text/text-to-image 교차주의로 두 모달리티를 사전 융합한다.
2. Decoder에서 새로운 객체를 위한 detect query와 이전 프레임에서 이어지는 track query를 입력으로 받아 OFA Branch(이미지 정렬)와 CTI Branch(텍스트 상호작용)로 각각 처리한다.
3. Attention Isolation의 Category Isolation Strategy와 Content Isolation Strategy가 decoder의 self-attention에서 서로 다른 카테고리 및 detect/track query 간 간섭을 마스킹한다.
4. 현재 프레임의 track query 출력이 Category Information Propagation을 통해 다음 프레임 decoder의 입력으로 전달되며, bipartite matching으로 detect query가 track query로 전환되는 과정이 반복된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| OVTR은 tracking-by-OVD 방식보다 novel category 인식과 추적을 더 잘 결합한다 | TAO validation set(novel)에서 TETA 31.4(OVTrack 27.8), ClsA 5.4(OVTrack 1.5)로 ClsA가 약 3배 이상 향상 |
| 대규모 사전 embedding 추출 없이도 open-vocabulary 분류를 달성할 수 있다 | 논문은 OVTrack이 99.4M개의 image embedding을 필요로 하는 반면 OVTR은 1,732개만 사용한다고 보고 |
| 학습된 표현이 다른 도메인/데이터셋으로 전이 가능하다 | KITTI Car 카테고리 전이 평가에서 MOTA 71.8(OVTrack 69.8, +2.0), IDF1 78.3(OVTrack 75.6, +2.7), ID switch 378건(OVTrack 594건)으로 보고 |
| Category isolation 및 KL divergence 계산을 제거해도 성능 저하가 크지 않다 | OVTR-Lite는 TAO validation(novel) TETA가 OVTR 31.4 대비 30.1로 소폭 하락하지만 여전히 OVTrack(27.8)을 상회하며, 논문 Table 9 기준 FPS가 3.4에서 12.4로 상승(공식 GitHub README에는 18.6 FPS로 기재) |

## 6. 한계 및 부족한 점
- 논문 원문에서 확인한 범위 내에는 별도의 "Limitation" 절이 명시적으로 존재하는지 확인되지 않았다.
- KITTI 전이 평가에서 보행자(pedestrian)/사이클리스트 구분이 open-vocabulary 설정과 맞지 않아 false positive가 늘어나는 문제가 언급된다.
- Attention Isolation의 Category Isolation Strategy는 query 쌍마다 KL divergence를 계산해야 하므로 이 연산이 추론 속도에 영향을 주며, 이 때문에 해당 연산을 제거한 OVTR-Lite가 별도로 제시된다.
- OVT-B 데이터셋과 같이 주석 frame rate가 높은 조건에서는 OVTR이 OVTrack+와 유사한 수준(TETA 45.5)에 머무는 것으로 보고된다.

## 7. 원문 기반 핵심 문장
> Open-vocabulary multiple object tracking aims to generalize trackers to unseen categories during training, enabling their application across a variety of real-world scenarios.
