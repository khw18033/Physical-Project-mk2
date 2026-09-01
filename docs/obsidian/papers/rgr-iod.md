# Revisiting Generative Replay for Class Incremental Object Detection

## 메타데이터
- categories: [[Image-Level Generative Replay]], [[Similarity-based Cross Sampling]], [[Pseudo-Labeling]], [[Mixed-Domain Training]]
- domain: [[Class Incremental Object Detection]], [[Generative Replay]]
- source: Shizhou Zhang, Xueqiang Lv, Yinghui Xing, Qirui Wu, Di Xu, Yanning Zhang, "Revisiting Generative Replay for Class Incremental Object Detection," Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025, pp. 20340-20349.
- url: https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Revisiting_Generative_Replay_for_Class_Incremental_Object_Detection_CVPR_2025_paper.html
- year: 2025
- authors: Zhang et al.
- venue: CVPR 2025 (IEEE/CVF Conference on Computer Vision and Pattern Recognition)

## 1. 핵심 요약
- Class Incremental Object Detection(CIOD)에서 catastrophic forgetting을 완화하기 위해, 복잡한 장면을 정밀하게 제어 생성하는 별도의 생성 모델을 학습시키는 대신 기존의 표준 Stable Diffusion(SD) 모델을 그대로 활용해 image-level replay 데이터를 생성하는 방법(RGR)을 제안한다.
- 저작자들은 CIOD에서 지식 망각이 localization(bounding box 회귀)보다 classification 서브태스크에서 두드러진다는 관찰에서 출발해, 인스턴스 단위의 정밀한 레이아웃 제어 없이도 image-level 생성과 pseudo-labeling만으로 충분히 효과적인 replay가 가능함을 보인다.
- Old task 이미지에는 이전 detector, new task 이미지에는 현재 stage만으로 학습한 detector를 각각 적용해 pseudo-label을 부여하고, Similarity-based Cross Sampling(SCS)으로 old/new task 간 혼동되기 쉬운 어려운 샘플을 선별해 false alarm을 줄이면서 이전 지식을 보존한다.
- PASCAL VOC 2007과 MS COCO 2017의 다양한 single-step 및 multi-step incremental 설정에서 기존 state-of-the-art(BPF 등) 대비 우수한 성능을 달성했다.

## 2. 문서 목적
- 해결하려는 문제: Class Incremental Object Detection에서 이전에 학습한 클래스에 대한 catastrophic forgetting을 완화하는 문제, 특히 복잡한 다중 인스턴스 장면을 다루는 detection 맥락에서 생성적 replay를 어떻게 실용적으로 적용할지의 문제.
- 기술적 목표: 별도의 고비용 생성 모델이나 인스턴스 단위 레이아웃 제어 없이 표준 SD 모델을 이용한 image-level generative replay와 유사도 기반 cross sampling만으로 old/new task 지식을 균형 있게 유지하는 detector 학습 파이프라인을 구축하는 것.
- 다루는 범위: 이미지 레벨 생성 replay(IGR) 모듈, pseudo-labeling 기반 bounding box 결정, Similarity-based Cross Sampling(SCS) 모듈, 현재 stage 학습을 위한 synthetic/real 데이터 결합 및 손실 함수 설계, PASCAL VOC/MS COCO에서의 단일·다단계 incremental 실험과 ablation. Faster R-CNN 계열 two-stage detector(ResNet-50 backbone)를 중심으로 다룬다.

## 3. 핵심 개념 상세
### Image-Level Generative Replay
- 원문 표현: "Image-level generative replay for all previous and new tasks. The SD model generates image-level replay data directly, primarily featuring a single object per image, using a text prompt such as 'a realistic clear photo of [cls]'"
- 정의: 표준 Stable Diffusion 모델에 "A realistic clear photo of [cls]" 형태의 텍스트 프롬프트를 입력해 old task와 new task 클래스 각각에 대해 이미지 한 장에 주로 단일 객체가 등장하는 image-level 합성 이미지를 생성하는 모듈.
- 역할: 별도 도메인 적응이나 기하학적 제약 없이도 old task의 지식을 보존하고, new task용 합성 이미지는 실제 이미지와 합성 이미지 간 domain gap을 줄이는 데 사용된다. 생성된 이미지는 이전 detector(old task) 또는 stage-wise detector(new task)를 통해 pseudo-label이 부여되며, 신뢰도가 임계값 τ 이상인 bounding box를 가진 이미지만 최종 선택된다.

### Similarity-based Cross Sampling
- 원문 표현: "Similarity-based Cross Sampling (SCS) mechanism to select valuable data which contain instances that are prone to misclassified but can be accurately localized."
- 정의: old task 합성 이미지에는 new task만으로 학습된 detector Mst를, old task 합성 이미지의 pseudo-label에는 이전 detector Mt-1을 각각 교차 적용해 두 예측 간 최소 IoU(IoU_min)를 계산하고, 이 값이 임계값 η보다 큰 즉 old/new task 간 혼동 가능성이 높은 이미지를 우선적으로 replay에 포함시키는 샘플링 기법.
- 역할: 오분류되기 쉽지만 localization은 정확한 어려운 샘플을 선별해 new task에 대한 false alarm(오탐)을 크게 낮추면서 old task 지식 보존을 강화한다. 또한 old task는 합성 데이터, new task는 실제 데이터에 치우치는 domain bias 문제를 완화하기 위해 new task의 일부 합성 데이터(Dgen-t)도 real 데이터와 함께 학습에 포함하는 mixed-domain 방식을 취한다.

### Pseudo-Labeling
- 원문 표현: "To determine bounding box positions necessary for detector training, a pseudo-labeling approach is used: the old detector Mt-1 handles the generated images for old tasks, and a stage-wise detector Mst... processes images for the new task."
- 정의: 합성 이미지 및 현재 task의 실제 이미지에 대해 정답 bounding box가 없는 상황에서, 이전 detector(Mt-1) 또는 현재 stage detector(Mst)의 예측을 대체 정답(pseudo-label)으로 사용하는 방법. 현재 task 실제 데이터(Dt)에는 old detector Mt-1을 적용해 미표기(old task) 클래스에 대한 missing annotation 문제를 완화하며, 예측 bbox와 실제 ground truth 간 최대 IoU가 임계값 γ(기본 0.5)를 넘으면 오분류된 pseudo-label로 간주해 걸러낸다.
- 역할: CIOD에서 현재 task 클래스만 라벨링되어 이전 task 객체가 배경으로 잘못 취급되는 missing annotation 문제를 완화하고, 합성 이미지의 bounding box 위치를 결정하는 핵심 수단이 된다.

### Mixed-Domain Training
- 원문 표현: "unlike traditional CIOD training which typically focuses on a single real image domain, our CIOD framework leverages a mixed-domain approach in each incremental stage Tt."
- 정의: old task용 합성 이미지(Dgen-(1:t-1)), new task용 일부 합성 이미지(Dgen-t), 그리고 현재 task의 실제 이미지(Dt)를 함께 결합해 각 incremental stage의 detector를 학습시키는 방식이며, 손실 함수는 synthetic loss와 real loss의 가중합(L = Lsynth + Lreal)으로 구성되고 synthetic loss 내에서도 classification 항에 상대적으로 더 큰 가중치를 부여한다.
- 역할: old task 데이터가 합성 데이터 위주이고 new task 데이터가 실제 이미지 위주인 데이터 불균형에서 모델이 클래스 의미가 아닌 도메인(합성/실제) 차이에 치우쳐 학습되는 것을 방지하고, 합성 데이터의 부정확한 회귀 지식이 학습을 저해하지 않도록 조정한다.

## 4. 구조 및 흐름
1. Image-Level Generative Replay(IGR): SD 모델이 old task 및 new task 클래스에 대해 "A realistic clear photo of [cls]" 프롬프트로 image-level 합성 이미지를 생성한다.
2. Pseudo-Labeling: old task 합성 이미지는 이전 detector Mt-1로, new task 합성 이미지는 현재 stage만으로 학습된 detector Mst로 각각 예측을 수행해 bounding box와 confidence score를 얻고, confidence가 임계값 τ 이상인 이미지만 confidence-based sampling으로 선별한다.
3. Similarity-based Cross Sampling(SCS): old task 합성 이미지에는 Mst를, new task 합성 이미지(또는 그 반대 조합)에는 Mt-1을 교차 적용해 두 예측 간 최소 IoU를 계산하고, 임계값 η를 넘는 즉 old/new task 간 유사도가 높은(혼동 가능성이 큰) 샘플을 우선 선택한다.
4. Current Stage Training: 현재 task 실제 데이터 Dt에는 Mt-1로 pseudo-labeling을 수행하고(오분류된 라벨은 ground truth와의 최대 IoU가 γ 초과 시 제거), old/new task 합성 이미지(Dgen-(1:t))와 실제 데이터 Dt를 결합해 가중 손실 L = Lsynth + Lreal로 현재 stage detector Mt를 학습시킨다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| CIOD의 지식 망각은 localization보다 classification 서브태스크에서 두드러진다 | PASCAL VOC 5-5(4 tasks) 설정의 forgetting curve(Fig. 1)에서 mAP는 크게 하락하지만 class-agnostic 방식으로 측정한 objectness AP(oAP)는 상대적으로 유지됨을 보였고, "aeroplane" 클래스 AP가 0으로 떨어져도 해당 객체는 여전히 정확히 localize됨을 확인 |
| 표준 SD 모델만으로도 image-level generative replay가 CIOD에서 state-of-the-art 성능을 낼 수 있다 | PASCAL VOC 2007 단일 단계 설정(19-1, 15-5, 10-10, 5-15)에서 BPF 대비 mAP 1.3~2.9%p 향상, 다단계 설정(10-5, 5-5, 10-2, 15-1)에서 3.1~8.0%p 향상, MS COCO 2017(40+40, 70+10)에서도 BPF 대비 AP 0.4~1.2%p 향상 달성(Tab. 1-3) |
| Similarity-based Cross Sampling(SCS)이 false alarm 감소와 지식 보존에 기여한다 | Ablation(Tab. 4)에서 IGR만 사용한 (b) 대비 SCS를 추가한 (c)에서 VOC 10-10/15-5/10-5 설정 모두 전체 mAP가 추가로 0.2~0.7%p 상승했고, Fig. 5에서 "dog"-"cat", "bus"-"train"처럼 유사 카테고리 간 forgetting이 특히 완화됨을 확인 |

## 6. 한계 및 부족한 점
- Stable Diffusion 자체가 "정확한 spatial arrangement"가 요구되는 상황, 즉 object detection에서의 정밀한 객체 위치 지정에는 한계가 있다고 명시되어 있어(SD's generative capabilities encounter difficulties in scenarios demanding exact spatial arrangements), 이 때문에 인스턴스 단위 복잡 장면 생성 대신 image-level(주로 단일 객체) 생성 방식을 택했다.
- 합성 데이터는 주로 단일 인스턴스로 구성되어 있어 충분한 bounding box 회귀 지식을 제공하지 못한다고 저자들 스스로 언급하며(synthetic data often consists of simple single-instance images, such data may not provide sufficient regression knowledge), 이를 보완하기 위해 실제 이미지에 의존하고 손실 함수에서 classification 항에 더 큰 가중치를 부여하는 방식으로 대응했다.
- VOC 5-5(4 tasks) 설정의 1-5(old task) 성능(61.2)은 비교 대상 BPF(60.6)와 큰 차이가 없는 등, 특정 다단계 설정에서는 old task 성능 개선폭이 제한적으로 나타난다(Tab. 2).
- 논문 내에 별도의 "Limitations" 절은 없으며, 위 내용은 본문(Introduction, Method, 결과 해석)에서 저자가 직접 언급한 제약 사항이다.

## 7. 원문 기반 핵심 문장
> Our method utilize a standard Stable Diffusion model to generate image-level replay data for all old and new tasks. Accordingly, the old detector and a stage-wise detector are conducted on the synthetic images respectively to determine the bounding box positions through pseudo-labeling. Furthermore, we propose to use a Similarity-based Cross Sampling mechanism to select valuable confusing data between old and new tasks to more effectively mitigate catastrophic forgetting and reduce the false alarm rate for the new task.
