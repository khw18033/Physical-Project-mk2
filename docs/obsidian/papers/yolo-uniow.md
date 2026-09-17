# YOLO-UniOW: Efficient Universal Open-World Object Detection

## 메타데이터
- categories: Wildcard Learning, Adaptive Decision Learning (AdaDL), Open-World Object Detection (OWOD), Open-Vocabulary Object Detection (OVD)
- domain: [[객체 탐지·분할]]
- source: Liu, Lihao, Feng, Juexiao, Chen, Hui, Wang, Ao, Song, Lin, Han, Jungong, Ding, Guiguang. "YOLO-UniOW: Efficient Universal Open-World Object Detection." arXiv:2412.20645, 2024.
- url: https://arxiv.org/abs/2412.20645
- year: 2024 (arXiv 게재 2024-12-30, v1)
- authors: Lihao Liu, Juexiao Feng, Hui Chen, Ao Wang, Lin Song, Jungong Han, Guiguang Ding (Tsinghua University, Tencent ARC Lab)
- venue: arXiv preprint — 정식 학회/저널 게재 여부는 arXiv 페이지·저장소에서 확인되지 않아 미확인으로 남긴다.

## 1. 핵심 요약
- 기존 open-vocabulary detector(YOLO-World 등)는 이미지-텍스트 조기 융합(cross-modality fusion)에 의존해 클래스 텍스트 수가 늘어날수록 추론 속도가 급격히 저하되고, 사전 정의된 vocabulary 밖의 unknown 객체는 아예 탐지하지 못한다.
- YOLO-UniOW는 Universal Open-World Object Detection(Uni-OWD)이라는 통합 설정을 제안하고, (1) Adaptive Decision Learning(AdaDL)으로 무거운 조기 융합을 제거하고 CLIP latent space에서의 경량 정렬로 대체하며, (2) Wildcard Learning으로 vocabulary 밖 객체를 "unknown"으로 탐지하고 incremental learning 없이 vocabulary를 동적으로 확장한다.
- YOLOv10을 기반 detector로 채택해 LVIS minival에서 L 모델 기준 34.6 AP·30.0 AP_r·69.6 FPS(V100, forward-only)를 보고했고, S/M/L 세 크기 모두에서 YOLO-World(v2) 대비 속도-정확도 균형이 개선되었다고 주장한다.
- 모든 속도 측정은 V100 GPU·PyTorch(TensorRT 미사용) 기준이며, 논문·저장소 어디에도 Jetson·Raspberry Pi·CPU 등 비-V100/엣지 디바이스 지연시간 벤치마크는 존재하지 않는다(§6 참고).

## 2. 문서 목적
- 해결하려는 문제: open-vocabulary detection의 조기 융합 비용 문제와, open-world detection에서 "unknown" 객체를 별도 supervision 없이 탐지해야 하는 문제를 하나의 효율적인 모델로 동시에 해결.
- 기술적 목표: (i) YOLOv10 기반 detector에 텍스트 인코더의 LoRA 기반 decision-boundary 보정을 결합해 조기 융합 없이도 open-vocabulary 성능을 유지하는 것, (ii) wildcard embedding을 self-supervised로 학습시켜 vocabulary 밖 객체를 "unknown"으로 분리하고 새 카테고리 발견 시 재학습 없이 vocabulary에 편입시키는 것.
- 다루는 범위: AdaDL 설계, Wildcard Learning(Known/Wildcard Learning + Unknown Filtering) 설계, LVIS minival(OVD) 및 M-OWODB/S-OWODB/nu-OWODB(OWOD) 벤치마크 평가, 공식 저장소의 학습·평가 스크립트와 사전학습 가중치 제공 현황.

## 3. 핵심 개념 상세

### Adaptive Decision Learning (AdaDL)
- 원문 표현: "we propose a adaptive decision learning strategy (AdaDL) to eliminate the heavy early-layer fusion operation ... we introduce efficient parameters into the text encoder by incorporating Low-Rank Adaptation (LoRA) into all query, key, value and output projection layers."
- 정의: CLIP 텍스트 인코더의 Q/K/V/output projection 레이어에 LoRA(저랭크 행렬 ΔW)를 삽입해, 사전학습 가중치 W0는 고정한 채 이미지-텍스트 상호작용 정보만 저랭크 행렬에 흡수시키는 방식. 보정된 텍스트 임베딩은 추론 시 오프라인으로 미리 계산·저장해두어 텍스트 인코더 자체의 추론 비용을 제거한다.
- 역할: YOLO-World의 RepVL-PAN 같은 이미지-텍스트 조기 융합 없이도 두 모달리티의 decision boundary를 정렬시켜, 텍스트 클래스 수가 늘어나도 추론 속도가 크게 저하되지 않게 한다. YOLOv10의 one-to-many/one-to-one 두 head에 대해 공통 텍스트 표현으로 정렬하는 "multimodal dual-head match"도 함께 적용된다.

### Wildcard Learning (요구사항 (a) 정밀 검증)
- 원문 표현(문제 정의): "the detector should identify their bounding boxes B_unk and assign them the generic label 'unknown' with a wildcard T_w, such that: D(I, T_w) → {(b, unknown) | b ∈ B_unk}"
- 원문 표현(학습 절차): "we directly leverage a wildcard embedding to unlock generic power of open-vocabulary model ... we fine-tune its text embedding on the pretraining dataset for a few epochs. During this process, all ground-truth instances are treated as belonging to the same 'object' class ... we utilize this well-tuned wildcard embedding T_obj to teach an 'unknown' wildcard embedding T_unk. The 'unknown' wildcard is trained in a self-supervised manner without relying on ground-truth labels of 'unknown' class."
- 정밀 메커니즘 (콜백: 콜백 확인 결과, "OOD 객체를 unknown으로 처리한다"는 요약보다 훨씬 구체적인 2단계 절차임):
  1. **Wildcard 임베딩 초기화**: 범용 텍스트 "object"를 CLIP 텍스트 인코더(+AdaDL 보정)에 통과시켜 wildcard 임베딩 T_w를 만든다.
  2. **1단계 — Well-tuned wildcard(T_obj) 학습**: OVD 사전학습 데이터(Objects365+GoldG)에서 모든 GT 박스를 하나의 "object" 클래스로 취급해 T_obj를 3 epoch, lr 1e-4로 미세조정한다. 이 단계는 지도학습(GT 사용)이며, "object"라는 wildcard가 이미지 내 모든 물체 영역에 대해 일반적인 "objectness"를 포착하도록 만든다.
  3. **2단계 — Unknown wildcard(T_unk) 학습(자기지도)**: T_obj의 예측을 의사 라벨(pseudo label) 후보로 사용한다. 선택 함수 Φ(s,u) = 1 if (u < σ1) ∧ (s > σ2) else 0 을 적용해, known-class GT와의 최대 IoU(u)가 임계값 σ1=0.5보다 낮고 T_obj에 대한 분류 점수(s)가 σ2=0.01보다 높은 예측만 "진짜 unknown 후보"로 선별한다(즉 알려진 객체와 겹치지 않으면서도 "물체스러운" 영역). T_unk의 soft target은 T_obj의 유사도 점수(s_obj)를 그대로 distillation하듯 사용한다.
  4. **손실 함수**: L = L_k(s_k, o_k) + Φ(s_obj, u_obj)·L_unk(s_unk, s_obj) — known 클래스는 일반 BCE, unknown은 Φ로 게이팅된 BCE. 박스 회귀 손실은 포함되지 않고(분류 헤드에서만 계산) box 자체는 이미 학습된 detector의 회귀 출력을 그대로 사용한다.
  5. **Known 클래스 처리와 catastrophic forgetting 회피**: 각 known 클래스 텍스트 임베딩은 downstream task마다 개별적으로 미세조정된 뒤 동결(freeze)된다. exemplar replay 없이도 이전 task의 임베딩이 보존되므로 별도 replay buffer 없이 catastrophic forgetting을 피한다고 주장한다.
  6. **추론 시 중복 제거(Unknown Filtering)**: F(P_unk) = {p_u ∈ P_unk | IoU(p_u, p_k) < τ, ∀p_k ∈ P_k}, τ=0.99. Confident known 예측(score>0.2)과 IoU가 높은 unknown 예측을 제거해 known 객체가 unknown으로 중복 검출되는 것을 막는다.
  7. **Vocabulary 동적 확장**: unknown으로 검출된 객체 중 새 카테고리가 사람 또는 다운스트림 절차로 확인되면 해당 클래스명을 vocabulary V에 추가하고, 다음 task에서는 known 클래스로 취급한다 — 이때 추가되는 것은 새 텍스트 임베딩이며 기존 known 임베딩은 동결 상태이므로 재학습(replay 기반 incremental learning) 없이 확장된다는 것이 논문이 말하는 "dynamic vocabulary expansion without incremental learning"의 정확한 의미다.
- 역할: OOD 객체를 "특정 룰로 배경과 구분"하는 것이 아니라, CLIP 잠재공간에서 학습된 별도의 "unknown" 텍스트 임베딩이 기존 head 구조·유사도 계산 방식을 그대로 재사용해 known 클래스와 대칭적으로 동작하도록 만드는 것이 핵심이다. 완전한 비지도 학습이 아니라 well-tuned wildcard(T_obj, 지도학습으로 GT 사용)를 교사로 삼아 unknown wildcard를 자기지도 학습시키는 2단계 teacher-student 구조임에 유의해야 한다.

## 4. 구조 및 흐름
1. **Open-Vocabulary Pretraining**: YOLOv10을 detector로, CLIP 텍스트 인코더 + LoRA(AdaDL)를 텍스트 경로로 사용해 Objects365+GoldG 데이터로 사전학습한다. Multimodal dual-head match로 one-to-one/one-to-many 두 head를 공통 텍스트 표현에 정렬시킨다(조기 융합 없음).
2. **Wildcard 초기화 및 well-tuned wildcard 학습**: "object" 텍스트로 T_w를 초기화하고, 동일 사전학습 데이터에서 모든 GT를 단일 "object" 클래스로 취급해 T_obj를 미세조정한다.
3. **Open-World Fine-tuning**: T_obj의 예측을 의사 라벨로 삼아 Φ 선택 함수로 필터링한 뒤 T_unk를 자기지도로 학습하고, known 클래스 임베딩은 태스크별로 미세조정 후 동결한다.
4. **추론**: known 클래스는 일반 유사도 기반 분류로 예측하고, unknown은 T_unk 유사도로 예측한 뒤 IoU 기반 필터링(τ=0.99)으로 known과 중복되는 unknown 예측을 제거한다.
5. **평가**: OVD는 LVIS minival(zero-shot), OWOD는 M-OWODB(COCO+PASCAL VOC, 4-task 순차), S-OWODB(COCO, superclass 분리), nu-OWODB(nuScenes 기반 자율주행 시나리오)에서 known mAP(PK/CK 분리)와 unknown Recall/WI/A-OSE(참고용)로 측정한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| AdaDL은 조기 융합 없이도 YOLO-World류 모델보다 속도-정확도 균형이 우수하다 | Table 1: YOLO-UniOW-S/M/L(7.5M/16.2M/29.4M params)가 YOLO-Worldv2-S/M/L(13M/29M/48M) 대비 더 적은 파라미터로 동등하거나 더 높은 LVIS AP와 FPS를 달성(예: S 모델 26.2 AP vs YOLO-Worldv2-S 22.7 AP, 98.3 FPS vs 87.3 FPS) |
| Wildcard Learning은 추가 exemplar replay 없이 unknown 탐지와 known 성능 유지를 동시에 달성한다 | 논문 5장(Sec 3.3)에서 known 임베딩을 태스크별로 독립 미세조정 후 동결해 catastrophic forgetting을 방지한다고 서술하며, M-OWODB/S-OWODB/nu-OWODB에서 SOTA를 달성했다고 보고(단, 본 조사는 해당 결과 테이블(Tab.2 이하)의 수치까지 페이지 단위로 재검증하지는 않았다 — §6 참고) |
| **(콜백 검증) S 모델은 7.5M 파라미터, LVIS minival AP 26.2, V100 FPS 98.3** | Table 1 원문 행 그대로 확인됨: "YOLO-UniOW-S YOLOv10-S O365,GoldG 7.5M 26.2/27.4 24.1/26.0 24.9/25.6 27.7/29.3 98.3 119.3" — 콜백이 제시한 세 수치(7.5M, 26.2, 98.3)는 **정확히 일치**한다. 단, AP는 one-to-one head(26.2, NMS 불필요) / one-to-many head+NMS(27.4) 두 값이 함께 보고되며, 콜백이 인용한 26.2는 그중 one-to-one(기본) 값이다. FPS 98.3은 후처리 포함 전체 파이프라인 속도이고, 후처리 제외 forward-only 속도(FPS_f)는 119.3으로 별도 보고된다. |
| 모든 속도 수치는 V100 단일 GPU 기준이며 다른 하드웨어 벤치마크는 없다 | 논문 Table 1 캡션: "All speed measurements are conducted on a V100 GPU using PyTorch without TensorRT." 본문 14페이지 전체를 텍스트로 검색한 결과 Jetson/Raspberry Pi/CPU/T4/A100 등 V100 이외 하드웨어의 지연시간·FPS 수치는 어디에도 등장하지 않는다. "edge and mobile devices"라는 표현은 3.2절 도입부에 설계 동기로만 한 번 언급될 뿐 실측 벤치마크가 아니다. 공식 GitHub README의 성능 표 역시 V100 수치만 제공한다. |
| 공식 저장소는 OWOD 학습·평가 스크립트와 사전학습 가중치를 실제로 제공한다 | 저장소 루트에 `run_ovod.sh`(OVD)와 `run_owod.sh`(OWOD) 셸 스크립트가 존재하며, README의 Training & Evaluation 절은 "For open-world model training and evaluation, please follow the steps provided in `run_owod.sh`"라며 텍스트 특징 추출 → wildcard 미세조정 → 태스크별 학습 → 평가의 5단계 절차를 설명한다. S/M/L 각각의 OVD 사전학습 체크포인트(.pth)가 HuggingFace 링크로 제공되고, OWOD 미세조정 시작점을 앞당기기 위한 사전계산된 wildcard 특징(`object_tuned_s.npy`, `object_tuned_m.npy`)도 함께 배포된다. |
| 저장소에 ONNX export 관련 미해결 이슈가 실제로 존재한다 | GitHub Issue #27 "onnx导出"(2025-09-22 오픈, 2026-09-07 확인 시점 기준 **Open** 상태, 댓글·메인테이너 응답 없음): 사용자가 YOLO-World 방식을 따라 ONNX export를 시도했으나 (1) 텍스트 reparameterization을 배제하면 export 과정에서 에러가 발생하고, (2) reparameterization을 포함하면 export는 되지만 추론 결과가 `NoneType`으로 나온다고 보고. 즉 두 가지 export 경로 모두 실패하는 구체적 결함이 미해결로 남아 있다. |

## 6. 한계 및 부족한 점
- 본 조사는 arXiv PDF(2412.20645, pypdf로 전체 14페이지 텍스트 추출) 중 Abstract, 서론(1장), 방법론(3장 AdaDL·Wildcard Learning), 실험 설정과 Table 1(LVIS 성능표)을 직접 대조 확인했다. OWOD 정량 결과 표(Table 2 이후, M-OWODB/S-OWODB/nu-OWODB 상세 수치)는 페이지 존재만 확인했고 표 내 개별 숫자까지 재검증하지는 않았다 — 해당 부분의 구체 수치를 인용할 필요가 있다면 별도 확인이 필요하다.
- **콜백이 제기한 "7.5M 파라미터라고 해서 Raspberry Pi 5에서 빠르다는 보장은 없다"는 우려는 검증 대상이 아니라 타당한 주의사항으로 그대로 받아들여야 한다.** 논문·저장소 어디에도 Raspberry Pi(또는 임의의 ARM/엣지 SoC) 실측 벤치마크가 없으므로, "빠르다/느리다"를 판단할 근거 자체가 존재하지 않는다. 파라미터 수(7.5M)와 V100에서의 FPS(98.3)는 실제로 측정된 값이지만, 이는 고성능 데이터센터 GPU 환경에서의 결과이며 CPU-bound 또는 저전력 ARM 환경에서의 성능(특히 CLIP 텍스트 인코더 경로, LoRA 보정 오버헤드, YOLOv10 백본의 저전력 최적화 여부)을 시사하지 않는다. 따라서 Pi 5 등 엣지 배포를 계획한다면 별도의 실측이 필요하며, 이 논문의 결과를 그 근거로 사용할 수 없다.
- ONNX export 이슈(#27)는 저장소에 공식 export 스크립트/문서가 있는지 여부와 무관하게 사용자가 YOLO-World 방식을 자체적으로 적용하다 겪은 문제로 보고되어, 공식적으로 지원되는 export 경로의 부재 또는 미흡함을 시사한다. 다만 이슈가 1건뿐이고 댓글이 없어 재현 범위나 메인테이너의 공식 입장은 확인되지 않는다.
- "Wildcard Learning이 진정한 self-supervised"라는 논문의 표현은 엄밀히는 절반만 맞다: unknown wildcard(T_unk) 학습 자체는 GT "unknown" 라벨 없이 이루어지지만, 그 교사 역할을 하는 well-tuned wildcard(T_obj)는 GT 박스(모든 객체를 "object"로 취급)를 사용하는 지도학습으로 먼저 만들어진다. 즉 완전히 라벨-프리한 과정이 아니라 "기존 known-class GT를 재활용한 지도학습 교사 → unknown에 대한 자기지도 증류"라는 2단계 구조다.
- 벤치마크 성능(LVIS AP, FPS)은 저자 자체 실험 환경(V100, PyTorch, TensorRT 미사용)에 한정되며, 다른 하드웨어·양자화·컴파일 최적화(TensorRT, ONNX Runtime 등) 적용 시의 결과는 논문에 없다.
- 이 프레임워크(perception-framework)의 원칙(§0 CLAUDE.md)에 비추면, YOLO-UniOW는 특정 모델 구조(YOLOv10+CLIP)에 결합된 연구 구현체이므로 그대로 core dependency로 채택하기보다 AI Runtime Provider 뒤의 교체 가능한 provider 후보로만 검토해야 하며, ONNX export 미비는 실행 프로파일(AI-B-01)의 "runtime/format 호환성 미검증" 항목으로 기록해야 한다.

## 7. 원문 기반 핵심 문장
> "we propose a wildcard learning approach that enables the model to detect objects not present in the vocabulary and label them as 'unknown' rather than ignoring them. Specifically, we directly leverage a wildcard embedding to unlock generic power of open-vocabulary model."

> "we utilize this well-tuned wildcard embedding T_obj to teach an 'unknown' wildcard embedding T_unk. The 'unknown' wildcard is trained in a self-supervised manner without relying on ground-truth labels of 'unknown' class."

> "All speed measurements are conducted on a V100 GPU using PyTorch without TensorRT." (Table 1 캡션 — 논문·저장소 전체에서 확인되는 유일한 하드웨어 기준이며, 엣지 디바이스 벤치마크는 존재하지 않는다.)
