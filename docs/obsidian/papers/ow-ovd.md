# OW-OVD: Unified Open World and Open Vocabulary Object Detection

## 메타데이터
- categories: [[Open World Object Detection]], [[Open Vocabulary Object Detection]], [[Visual Similarity Attribute Selection]], [[Hybrid Attribute-Uncertainty Fusion]]
- domain: [[Computer Vision]], [[Object Detection]]
- source: Xing Xi, Yangyang Huang, Ronghua Luo, Yu Qiu, "OW-OVD: Unified Open World and Open Vocabulary Object Detection," Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025, pp. 25454-25464.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Xi_OW-OVD_Unified_Open_World_and_Open_Vocabulary_Object_Detection_CVPR_2025_paper.html
- year: 2025
- authors: Xing Xi et al.
- venue: CVPR 2025 (IEEE/CVF Conference on Computer Vision and Pattern Recognition)

## 1. 핵심 요약
- 기존 연구는 Open World Object Detection(OWOD)과 Open Vocabulary Object Detection(OVD) 중 한쪽 과제만 다루었으나, 이 논문은 두 과제를 동시에 지원하는 최초의 탐지기 OW-OVD를 제안한다.
- YOLO-World 기반 표준 OVD 탐지기를 시작점으로 삼아, 미지 객체를 능동적으로 탐지하고 점진적 학습(incremental learning)으로 새 카테고리를 인식하는 OWOD 능력을 추가한다.
- 속성 선택을 위한 Visual Similarity Attribute Selection(VSAS)과 미지 객체 예측을 위한 Hybrid Attribute-Uncertainty Fusion(HAUF)이라는 두 가지 방법을 제안한다.
- M-OWODB, S-OWODB 두 OWOD 벤치마크에서 기존 SOTA 대비 U-Recall +15.3, U-mAP +15.5의 성능 향상을 달성했다.
- HAUF는 OVD의 표준 추론 과정을 변경하지 않아 zero-shot 탐지 능력을 그대로 보존한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 연구들이 OWOD(미지 객체 탐지·점진적 학습)와 OVD(임의 카테고리에 대한 zero-shot 탐지)를 개별적으로만 다루어, 두 과제를 동시에 만족하는 탐지기가 충분히 탐구되지 않은 문제.
- 기술적 목표: OVD 탐지기의 zero-shot 일반화 능력을 유지하면서, OWOD 탐지기처럼 미지 객체를 능동적으로 발견하고 incremental learning으로 성능을 점진적으로 개선할 수 있는 통합 탐지기(OW-OVD)를 만드는 것.
- 다루는 범위: attribute generation(LLM 기반 속성 문장 생성), VSAS를 통한 일반화 가능 속성 선택, HAUF를 통한 미지 객체 확률 추정, M-OWODB·S-OWODB 벤치마크에서의 known/unknown 성능 평가, PASCAL VOC 기반 증분 객체 탐지(10+10/15+5/19+1) 평가, ablation study.

## 3. 핵심 개념 상세
### Open World Object Detection
- 원문 표현: "Open World Object Detection (OWOD), unlike OVD, treats the identification of unannotated objects as a progressive process... During inference, it actively detects objects that are likely unknown and presents them to annotators."
- 정의: 탐지 과제를 일련의 서브태스크로 나누고, 각 단계에서 라벨링되지 않은 미지 객체를 능동적으로 탐지해 unknown으로 표시한 뒤, 주석자가 이를 선택·라벨링하여 새 카테고리로 추가하고 모델을 재학습(incremental learning)하는 과제.
- 역할: OW-OVD가 결합하는 두 과제 중 하나로, 미지 객체 능동 발견과 점진적 카테고리 확장 능력의 원천이다.

### Open Vocabulary Object Detection
- 원문 표현: "Open Vocabulary Object Detection (OVD) treats the detection problem as a region-to-text matching problem... OVD detectors can theoretically detect an unlimited number of categories."
- 정의: 사전학습된 텍스트 인코더(예: CLIP)로 클래스명을 텍스트 임베딩으로 변환하고 시각 임베딩과의 유사도(코사인 유사도 등)를 계산하여 매칭하는 방식으로, 탐지 가능한 카테고리 수에 제약이 없는 탐지 과제.
- 역할: OW-OVD의 기반 아키텍처(YOLO-World)가 수행하는 표준 추론 방식이며, 새 클래스의 텍스트 설명만 입력하면 재학습 없이 인식 가능한 zero-shot 능력의 원천이다.

### Visual Similarity Attribute Selection
- 원문 표현: "we propose the Visual Similarity Attribute Selection (VSAS) method, which identifies the most generalizable attributes by computing similarity distributions across annotated and unannotated regions."
- 정의: LLM으로 생성된 다수(예: Task 1에서 약 2000개)의 속성 문장 중, 주석된 영역(positive sample)과 비주석 영역(negative sample)에 대한 속성 유사도의 확률분포(D+, D-)를 계산하고 Jensen-Shannon Divergence(JSD)로 두 분포의 차이가 가장 작은, 즉 known과 unknown 영역 모두에 공통적으로 적용 가능한 속성을 반복적으로 선택하는 방법. 선택된 속성이 서로 지나치게 유사해지지 않도록 유사도 제약(similarity restriction, 시그모이드 기반 코사인 유사도 페널티)을 추가로 적용한다.
- 역할: 미지 객체 예측(HAUF)에 사용할 소수의 일반화된 속성 집합을 구성하여, 노이즈가 많은 LLM 생성 속성의 부정적 영향을 줄인다.

### Hybrid Attribute-Uncertainty Fusion
- 원문 표현: "we propose the Hybrid Attribute-Uncertainty Fusion (HAUF) method. This method combines attribute similarity with known class uncertainty to infer the likelihood of an object belonging to an unknown class."
- 정의: 선택된 속성과 시각 임베딩의 유사도 기반 배경 구분 확률(Pb), 기지 클래스에 대한 예측 엔트로피인 known class uncertainty(Pun), 그리고 기지 클래스에 대한 out-of-distribution 확률(1 - max(known confidence))을 결합하여 미지 객체일 가능성(Pu)을 산출하는 방법. 기존 FOMO 계열의 attribute 기반 linear scaling 방식과 달리 별도의 선형 계층을 두지 않고 known 예측과 병렬적으로 unknown을 추론한다.
- 역할: OVD의 표준 추론 로직(known 클래스 예측)을 변경하지 않으면서 unknown 객체 예측을 수행해, OW-OVD가 OVD의 zero-shot 능력과 OWOD의 미지 객체 탐지 능력을 동시에 유지하도록 한다.

## 4. 구조 및 흐름
1. YOLO-World 기반 표준 OVD 탐지기(vision backbone, feature pyramid, text encoder, Box Head, Contrastive Head)에서 시작한다.
2. Attribute generation: 기지(known) 클래스명을 LLM(GPT-3.5)에 입력해 색상·질감 등 관련 특징을 나열하게 하고, 이를 사전 정의된 템플릿 문장에 삽입한 뒤 텍스트 인코더로 attribute embedding을 생성한다.
3. VSAS: 학습 중 시각 임베딩을 매칭 점수 기준으로 positive/negative 샘플로 나누고, 각 속성에 대한 유사도 분포를 구축한 뒤 JSD와 유사도 제약을 이용한 반복 선택으로 가장 일반화 가능한 속성 집합을 도출한다.
4. HAUF: 선택된 속성과의 유사도(Pb), known class uncertainty(Pun), known class에 대한 OOD 확률을 결합해 unknown 확률(Pu)을 계산하며, 이는 OVD의 known 클래스 예측 경로와 별도로 병렬 수행된다.
5. M-OWODB·S-OWODB(COCO와 VOC를 혼합해 각각 4개 서브태스크로 구성한 벤치마크)에서 known mAP, U-Recall, U-mAP를 평가하고, 다음 태스크에서는 새로 주석된 카테고리로 fine-tuning하는 incremental learning을 수행한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| OW-OVD는 기존 SOTA OWOD 방법 대비 unknown 객체 탐지(U-Recall)에서 크게 앞선다 | S-OWODB Task 1에서 U-Recall 76.2 달성, 기존 최고인 SKDF(60.9) 대비 +15.3; M-OWODB Task 1에서 ORTH(24.6) 대비 +25.4(50.0) |
| SAM 등 시각 파운데이션 모델을 사용하는 방법 대비 더 엄격한 지표인 U-mAP에서도 우위를 보인다 | S-OWODB Task 1 U-mAP 23.0 vs MEPU-FS 7.5(+15.5); M-OWODB Task 1 U-mAP 8.6 vs SGROD 2.4(+6.2) |
| OVD의 zero-shot 능력 덕분에 증분학습에서 known 클래스 수 변화에 덜 민감하다 | PASCAL VOC 10+10/15+5/19+1 설정에서 OW-OVD는 각각 87.2/86.9/86.8 mAP로 설정 간 격차가 0.4에 불과한 반면, PROB는 10+10(66.5)과 19+1(72.6) 사이 격차가 6.1 |
| VSAS의 attribute selection·similarity restriction과 HAUF의 OOD 확률·known uncertainty·top attribute 요소가 모두 성능 향상에 기여한다 | Ablation(Table 4)에서 M-OWODB U-mAP가 All attr(4.3) → OOD prob(5.9) → Attr sel(6.9) → Sim restr(7.1) → Known uncer(7.4) → Top attr(8.6) 순으로 단계적으로 개선됨 |

## 6. 한계 및 부족한 점
- Ablation(Table 4)에서 전체 unknown 클래스명을 정답으로 제공한 상한 실험(Base+GT)의 U-mAP는 M-OWODB 23.8, S-OWODB 54.6인 반면, 실제 제안 방법(Top attr)의 U-mAP는 각각 8.6, 23.0에 그쳐 이론적 상한과 실제 성능 사이에 상당한 격차가 남아 있다.
- Attribute generation 단계가 LLM(GPT-3.5)의 출력 품질에 의존하며, Task 1에서만 약 2000개의 중복·유사 속성이 생성될 정도로 초기 속성 집합의 노이즈가 커, VSAS라는 별도의 선택 단계가 필수적으로 요구된다.
- 하이퍼파라미터(α, β, γ)를 M-OWODB(0.55, 0.2, 10)와 S-OWODB(0.75, 0.3, 10)에서 서로 다르게 설정해야 한다고 논문에서 명시하고 있어, 벤치마크별 튜닝이 필요하다.
- 공식 GitHub 저장소(README)에는 설치 방법, 의존성, 재현성 관련 세부 절차가 명시되어 있지 않다.

## 7. 원문 기반 핵심 문장
> We validated the effectiveness of OW-OVD through evaluations on two OWOD benchmarks, M-OWODB and S-OWODB. The results demonstrate that OW-OVD outperforms existing state-of-the-art models, achieving a +15.3 improvement in unknown object recall (U-Recall) and a +15.5 increase in unknown class average precision (U-mAP).
