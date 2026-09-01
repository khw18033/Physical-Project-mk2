# Open World Object Detection in the Era of Foundation Models

## 메타데이터
- categories: [[RWD Benchmark]], [[Attribute-based Unknown Detection]], [[Foundation Model 기반 Open World Object Detection]]
- domain: [[Open World Object Detection]], [[Object Detection]]
- source: Zohar, O., Lozano, A., Goel, S., Yeung, S., Wang, K.-C., Open World Object Detection in the Era of Foundation Models, arXiv preprint arXiv:2312.05745, 2023
- url: https://arxiv.org/abs/2312.05745
- year: 2023
- authors: Orr Zohar et al.
- venue: arXiv preprint (arXiv:2312.05745)

## 1. 핵심 요약
- 기존 Open World Object Detection(OWD) 벤치마크는 COCO 기반의 known/unknown 클래스 분할을 사용하는데, foundation model은 사전학습 과정에서 이미 이런 클래스를 광범위하게 접했기 때문에 "unknown"의 정의 자체가 무너지며, 단순한(naive) foundation model 통합 방법만으로도 기존 벤치마크가 거의 포화(saturate)된다는 것을 실증했다.
- 이를 근거로 항공, 수술 등 실제 응용 도메인을 포함하는 5개 데이터셋으로 구성된 새로운 벤치마크 RWD(Real-World Object Detection)를 제안한다.
- known 클래스와 unknown 클래스가 속성(attribute)을 공유한다는 점을 활용해, known 클래스의 속성을 기반으로 unknown 객체를 식별하는 FOMO(Foundation Object detection Model for the Open world)를 제안한다.
- FOMO는 RWD 벤치마크에서 baseline 대비 약 3배(~3x) 높은 unknown object mAP를 달성했으나, 저자들은 여전히 개선 여지가 크다고 명시한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 OWD의 엄격한 벤치마크·태스크 정의가 foundation model의 활용을 사실상 배제하고 있으며, foundation model을 도입했을 때 기존 벤치마크가 더 이상 유효한 평가 수단이 되지 못하는 문제.
- 기술적 목표: foundation model을 OWD에 도입하기 위한 새로운 벤치마크(RWD)와, known 클래스와 unknown 클래스 간 공유 속성을 이용해 unknown 객체를 식별하는 방법(FOMO)을 제시하는 것.
- 다루는 범위: OWD 벤치마크 정의의 재검토, RWD 벤치마크 5개 데이터셋 구성, attribute 생성·선택·정제로 이어지는 FOMO 파이프라인, 기존 OWODB와 RWD 각각에서의 baseline 대비 성능 비교.

## 3. 핵심 개념 상세
### RWD Benchmark
- 원문 표현: "we introduce a new benchmark that includes five real-world application-driven datasets, including challenging domains such as aerial and surgical images, and establish baselines"
- 정의: Aquatic(수중 생물), Aerial(항공/위성 영상), Game(게임 스크린샷), Medical(손 X-ray), Surgery(신경외과 도구) 5개 실제 응용 도메인 데이터셋으로 구성된 Open World Object Detection 평가 벤치마크. Task 1은 클래스 빈도 상위 50%를 known, 하위 50%를 unknown으로 분할하고, Task 2는 모든 클래스를 공개해 기존/신규 known 성능을 평가한다.
- 역할: 사전학습된 foundation model이 이미 노출되었을 가능성이 높은 COCO 기반 기존 OWODB 벤치마크의 한계를 보완하고, foundation model 시대에 걸맞은 도전적이고 실제 응용에 가까운 평가 기준을 제공한다.

### Attribute-based Unknown Detection
- 원문 표현: "we introduce a novel method, Foundation Object detection Model for the Open world, or FOMO, which identifies unknown objects based on their shared attributes with the base known objects"
- 정의: known 클래스와 unknown 클래스가 공유하는 클래스-무관(class-agnostic) 속성(attribute) 정보를 이용해, known 클래스에 대한 분류 확신도(p_OOD)와 속성 일치도(p_ID)를 결합한 점수(p_unk = p_OOD · p_ID)로 unknown 객체 여부를 판단하는 방식.
- 역할: known 클래스 레이블만으로 학습하면서도, known과 unknown이 공유하는 속성 구조를 활용해 명시적인 unknown 레이블 없이 unknown 객체를 식별하는 FOMO의 핵심 판별 메커니즘이다.

### Foundation Model 기반 Open World Object Detection
- 원문 표현: "existing benchmarks are insufficient in evaluating methods that utilize foundation models, as even naive integration methods nearly saturate these benchmarks"
- 정의: CLIP 기반 사전학습 모델인 OWL-ViT(B/16, L/14)을 Objects365, Visual Genome 등에서 검출 미세조정한 상태로 활용하여 OWD 태스크를 수행하는 접근. FOMO는 여기에 GPT-3.5로 생성한 클래스별 속성을 텍스트 인코더로 임베딩하고, 시각 임베딩과의 정합을 위해 attribute selection(가중치 W 학습)과 attribute refinement(속성 임베딩 갱신) 단계를 추가한다.
- 역할: 특정 폐쇄형 클래스 집합에 의존하던 기존 OWD 방법론과 달리, 대규모 사전학습 지식을 가진 foundation model을 OWD 파이프라인에 통합하는 구조를 제시하며, FOMO가 이 통합을 구체적으로 구현한 사례다.

## 4. 구조 및 흐름
1. Attribute Generation: LLM(GPT-3.5)에 known 클래스 이름을 입력해 클래스별 속성 목록 A = {A1, A2, ..., An}을 생성한다.
2. Attribute Selection: 속성 임베딩 행렬 E_att를 구성하고, BCE 손실과 L1 정규화로 가중 행렬 W(K x N)를 학습해 각 클래스당 상위 N̂개 속성만 선택한다.
3. Attribute Refinement: W를 고정한 채 속성 임베딩 E_att를 L2 손실로 업데이트하여 시각 임베딩과 텍스트 기반 속성 임베딩 간 모달리티 갭을 줄인다.
4. Unknown Object Inference: known 클래스에 대한 OOD 확률(p_OOD = 1 - max_C(SoftMax_C(Ws)))과 속성 기반 ID 확률(p_ID = max_A(Sigmoid(s)))을 곱해 p_unk를 산출하고, 이를 기준으로 unknown 객체를 판별한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 기존 OWD 벤치마크(OWODB)는 foundation model 평가에 부적합하다 | 단순한 foundation model 통합 baseline(BASE-ZS+LLM-L/14)만으로도 U-Recall 79.0, known mAP 65.7을 기록해 기존 벤치마크가 거의 포화됨을 실험으로 제시 |
| FOMO는 RWD 벤치마크에서 baseline보다 unknown 객체 탐지 성능이 크게 우수하다 | RWD 5개 데이터셋 평균 unknown mAP에서 BASE-FS-L/14의 5.0 대비 FOMO-L/14가 15.2를 기록, 논문 본문에서 "FOMO has ~3x unknown object mAP compared to baselines on our benchmark"로 명시 |
| known과 unknown 클래스 간 공유 속성을 활용하는 접근이 유효하다 | Aquatic(2.4→18.2), Game(8.2→30.4), Medical(1.1→9.4), Surgery(3.6→12.0) 등 데이터셋별 unknown mAP가 baseline 대비 전반적으로 상승 |

## 6. 한계 및 부족한 점
- foundation model을 통합하면 unknown의 정의 자체가 모호해진다는 점을 저자들이 직접 인정한다: "the definition of an unknown becomes fuzzy when we integrate such models as they have been pre-trained on large datasets that can contain any objects".
- FOMO의 baseline들은 훈련 과정에서 이미 어느 정도의 지도(supervision)를 받았기 때문에 PROB, OW-DETR 같은 기존 OWD 방법과 직접 비교가 불가능하다: "it is impossible to directly compare our baselines to previous OWD methods such as PROB and OW-DETR. Unlike these methods, our baselines undoubtedly received some supervision during training".
- 텍스트 기반 속성 임베딩과 시각 임베딩 간 모달리티 갭 문제, 그리고 저데이터(few-shot, 특히 1-shot) 환경에서의 성능 민감도가 미해결 과제로 남아 있다.
- 저자들은 "FOMO ... indicate a significant place for improvement"라고 명시하며, foundation model을 상대적으로 작은 detection 데이터셋으로 학습시키면서 그 잠재력을 온전히 활용하는 방법이 향후 연구 과제로 남아 있음을 밝힌다.

## 7. 원문 기반 핵심 문장
> "We exploit the inherent connection between classes in application-driven datasets and introduce a novel method, Foundation Object detection Model for the Open world, or FOMO, which identifies unknown objects based on their shared attributes with the base known objects. FOMO has ~3x unknown object mAP compared to baselines on our benchmark."
