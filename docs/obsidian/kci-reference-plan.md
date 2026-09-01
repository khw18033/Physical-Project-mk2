# KCI 연구용 기존 논문 선정 및 활용 계획

## 1. 문서 목적

이 문서는 KCI 확장 연구에서 실제로 사용할 기존 연구를 먼저 확정하기 위한 기술 문서이다.

연구 진행 순서는 다음과 같이 둔다.

1. 기존 연구의 공식 논문, 공식 코드, 공식 데이터 및 평가 방법을 확보한다.
2. 각 연구를 가능한 범위에서 원 저자 설정 그대로 재현한다.
3. 재현된 방법을 기능별 Reference Baseline으로 사용한다.
4. 동일 입력, 동일 데이터, 동일 하드웨어 또는 동일 cached output 조건에서 한 요소씩 변경한다.
5. 처리 순서, 입력 단위, Provider 선택 방식, 재사용 방식, 하이퍼파라미터 등 단순한 변경도 독립적인 실험 변수로 취급한다.
6. 실제 성능 차이가 반복적으로 확인된 변경만 최종 KCI 제안 방법 후보로 남긴다.

Provider는 객체의 추가적인 의미, 속성, 위치, 공간, 추적, 외부 정보 또는 실행 정보를 생성하거나 제공하는 기능 단위로 사용한다. 각 Provider는 모델 종류가 아니라 capability, 입력, 출력, 실행 위치, 품질 및 비용 프로파일로 관리한다.

이 문서는 **외부 기존 연구를 재현하기 위한 요구사항·기술 문서 활용 범위까지만** 다룬다. 재현된 baseline 위에 내 아이디어를 추가해 실험해보는 계획은 `ideas/` 디렉터리의 각 아이디어 문서에서 별도로 다룬다.

---

# 2. 논문 선정 구조

## A. 실행 성능 예측 및 선택

- ApproxDet: Content and Contention-Aware Approximate Object Detection for Mobiles
- DACC: Discerning and Adaptive Offloading for Coarse-Grained Content-Aware Video Analytics
- nn-Meter: Towards Accurate Latency Prediction of Deep-Learning Model Inference on Diverse Edge Devices
- OCTOPINF: Workload-Aware Inference Serving for Edge Video Analytics
- E4: Energy-Efficient DNN Inference for Edge Video Analytics via Early Exiting and DVFS

## B. 미확인 객체 탐지 및 의미 확장

- Open World Object Detection in the Era of Foundation Models
- OW-OVD: Unified Open World and Open Vocabulary Object Detection
- Open-World Objectness Modeling Unifies Novel Object Detection

## C. 지속 객체 관리 및 연속 영상 비교

- ByteTrack: Multi-Object Tracking by Associating Every Detection Box
- OVTR: End-to-End Open-Vocabulary Multiple Object Tracking with Transformer

## D. 지속 학습 및 변화 감지

- Boosting Vision-Language Models Towards Cross-Domain Incremental Object Detection
- H2ST: Hierarchical Two-Sample Tests for Continual Out-of-Distribution Detection
- Revisiting Generative Replay for Class Incremental Object Detection
- Ekya: Continuous Learning of Video Analytics Models on Edge Compute Servers

---

# 3. ApproxDet: Content and Contention-Aware Approximate Object Detection for Mobiles

## 역할

Provider의 예상 품질과 실행 비용을 이용하여 runtime configuration을 선택하는 Reference Baseline으로 사용한다.

## 핵심 특징

ApproxDet은 runtime에서 다음 세 가지 변화를 함께 고려한다.

- input video characteristics
- compute resource contention
- latency-accuracy requirement

Faster R-CNN detector와 tracker를 여러 approximation branch로 구성한다.

대표적인 approximation knob는 다음과 같다.

- sampling interval
- detector input shape
- number of proposals
- tracker type
- tracker downsampling ratio

각 branch의 accuracy와 latency를 offline profiling과 online state를 이용하여 예측하고, latency SLA를 만족하는 branch 중 예상 accuracy가 가장 높은 branch를 선택한다.

현재 resource contention은 최근 실행 latency와 offline contention profile을 비교하여 추정한다.

## 본 연구에서 가져올 요소

- Offline Provider Profiling
- Content Feature Extraction
- Accuracy Predictor
- Latency Predictor
- Resource Contention Awareness
- SLA 기반 configuration selection
- Switching overhead profiling
- Scheduler overhead 측정 방법

## 활용 계획

ApproxDet의 Faster R-CNN 전용 branch 구조를 그대로 전체 프레임워크에 강제하지 않고, 각 Provider Configuration을 branch에 대응시킨다.

예시:

- Provider A + input 320 + local CPU
- Provider A + input 640 + edge GPU
- Provider B + server GPU
- Provider C + external service

각 configuration에 대해 예측 가능한 품질과 비용을 관리하고 동일 조건에서 Provider selection baseline으로 사용한다.

## 재현 절차

1. ApproxDet 공식 구현 원본 재현
2. 공식 predictor와 scheduler 동작 확인

## 구현상 주의

공식 구현은 NVIDIA Jetson TX2, TensorFlow-GPU 1.14 계열 환경을 기준으로 한다. 새로운 장치에서는 profiling과 prediction model을 새로 구축해야 한다.

## 공식 자료

논문:
https://doi.org/10.1145/3384419.3431159

공식 코드:
https://github.com/StarsThu2016/ApproxDet

---

# 4. DACC: Discerning and Adaptive Offloading for Coarse-Grained Content-Aware Video Analytics

## 역할

ApproxDet보다 최근의 content-aware, resource-aware execution decision 비교군으로 사용한다.

## 핵심 특징

DACC는 edge와 cloud가 함께 video analytics를 수행할 때 모든 frame을 동일하게 처리하지 않고 복잡한 frame을 구분하여 cloud로 offload한다.

두 개의 주요 구성요소를 사용한다.

- Offloading Scheduler
- Accuracy Predictor

Accuracy Predictor는 frame의 detection complexity를 추정하고 cloud 실행으로 얻을 F1-score gain을 예측한다.

논문에서 사용하는 lightweight content information은 다음을 포함한다.

- optical flow
- entropy
- number of edge pixels

Offloading Scheduler는 time-varying resource conditions를 고려하여 cloud로 보낼 frame 비율을 조정한다.

## 본 연구에서 가져올 요소

- Lightweight content complexity feature
- 추가 고성능 Provider 실행 시 예상 accuracy gain 예측 개념
- edge-cloud execution decision
- 현재 resource condition에 따른 adaptive offloading
- frame별 execution value 판단 방식

## 활용 계획

ApproxDet과 DACC를 동일한 Reference Framework에서 서로 다른 execution policy로 재현해 둔다. Provider는 cloud detector 하나로 제한하지 않고, 동일 capability 또는 다른 추가 capability를 제공하는 실행 후보로 확장한다.

## 재현 절차

- DACC 공식 구현 재현
- Accuracy Predictor 입력 feature 재현
- predictor 자체의 inference overhead 포함해 측정

## 공식 자료

논문:
https://doi.org/10.1016/j.comnet.2026.112130

공식 코드:
https://github.com/twerppan/DEOF

---

# 5. nn-Meter: Towards Accurate Latency Prediction of Deep-Learning Model Inference on Diverse Edge Devices

## 역할

새로운 Model × Runtime × Hardware 조합을 매번 전부 실제 측정하는 비용을 줄일 수 있는 latency prediction Reference Method로 사용한다.

## 핵심 특징

nn-Meter는 전체 neural network latency를 단순 FLOPs로 추정하지 않고 device에서 실제 실행되는 fused operator 단위의 kernel로 분해한다.

각 kernel latency를 예측하고 이를 이용하여 전체 model inference latency를 예측한다.

공식 toolkit은 다음 model 형식을 지원한다.

- TensorFlow
- PyTorch
- ONNX
- nn-Meter IR
- NNI IR

또한 사용자가 자신의 hardware를 위한 latency predictor를 구축할 수 있는 nn-Meter Builder를 제공한다.

## 본 연구에서 가져올 요소

- Model structure 기반 hardware latency prediction
- kernel-level latency modeling
- hardware-specific predictor 구축
- 일부 실측을 활용한 새로운 hardware profile 생성
- profiling cost 절감 평가 방법

## 활용 계획

Provider 실행 프로파일을 생성할 때 두 방법을 재현해 비교할 수 있게 둔다.

### 방법 A

모든 Model × Runtime × Hardware × Input 조합을 직접 profiling한다.

### 방법 B

일부 조합을 profiling하고 nn-Meter 기반 latency prediction을 이용한다.

## 재현 검증 항목

- latency prediction error
- profiling에 필요한 실제 실행 횟수
- profiling 소요 시간

## 공식 자료

논문:
https://doi.org/10.1145/3458864.3467882

공식 코드:
https://github.com/microsoft/nn-Meter

---

# 6. Open World Object Detection in the Era of Foundation Models

## 시스템명

FOMO

## 역할

미확인 객체 탐지 및 attribute 기반 unknown recognition의 핵심 Reference Baseline으로 사용한다.

## 핵심 특징

FOMO는 foundation model을 Open World Object Detection에 활용한다.

미확인 객체를 완전히 새로운 class representation으로만 처리하지 않고 known base classes와 공유하는 attributes를 이용하여 unknown object를 식별한다.

논문은 foundation model을 활용하는 OWOD 방법을 평가하기 위해 Real-World Object Detection benchmark도 제공한다.

RWD benchmark는 여러 application-driven domain으로 구성된다.

공식 repository에서 benchmark 실행과 baseline 실행 script를 제공한다.

## 본 연구에서 가져올 요소

- Unknown Object Detection 기준선
- Attribute 기반 unknown identification
- Foundation model 활용 방법
- RWD benchmark
- 공식 baseline evaluation protocol
- attribute generation 및 refinement 구조

## 활용 계획

FOMO를 공식 RWD benchmark에서 그대로 재현하여 unknown perception Reference Baseline을 확보한다.

## 공식 자료

논문:
https://arxiv.org/abs/2312.05745

공식 코드:
https://github.com/orrzohar/FOMO

프로젝트:
https://ai.stanford.edu/~orrzohar/projects/fomo/

---

# 7. OW-OVD: Unified Open World and Open Vocabulary Object Detection

## 역할

FOMO보다 최근의 강한 open-world/open-vocabulary 통합 Reference Baseline으로 사용한다.

## 핵심 특징

OW-OVD는 Open World Object Detection과 Open Vocabulary Object Detection을 하나의 detector에서 다룬다.

핵심 구성은 다음과 같다.

- Visual Similarity Attribute Selection
- Hybrid Attribute-Uncertainty Fusion

Visual Similarity Attribute Selection은 annotated region과 unannotated region의 similarity distribution을 이용해 일반화 가능한 attribute를 선택한다.

Hybrid Attribute-Uncertainty Fusion은 attribute similarity와 known-class uncertainty를 결합하여 unknown likelihood를 추론한다.

논문은 M-OWODB와 S-OWODB에서 평가하며 CVPR 2025에 발표되었다.

공식 코드는 YOLO-World 기반으로 제공된다.

## 본 연구에서 가져올 요소

- 최신 reproducible unknown detection baseline
- attribute selection
- uncertainty와 attribute evidence의 결합
- YOLO-World 기반 real-time open-vocabulary implementation
- M-OWODB/S-OWODB 평가 구조

## 활용 계획

FOMO와 별도의 Reference Baseline으로 공식 설정 그대로 재현해 유지한다.

## 공식 자료

논문:
https://openaccess.thecvf.com/content/CVPR2025/html/Xi_OW-OVD_Unified_Open_World_and_Open_Vocabulary_Object_Detection_CVPR_2025_paper.html

공식 코드:
https://github.com/xxyzll/OW_OVD

---

# 8. Open-World Objectness Modeling Unifies Novel Object Detection

## 시스템명

OWOBJ

## 역할

Attribute 기반 방법과 다른 방향에서 unknown object 자체를 검출하는 강한 비교군으로 사용한다.

## 핵심 특징

OWOBJ는 unknown object가 background로 제거되거나 known class로 잘못 분류되는 문제를 objectness 관점에서 다룬다.

핵심 구성은 다음과 같다.

- class-agnostic objectness modeling
- variational approximation
- dynamic Gaussian prior
- energy-based margin loss

Open World Object Detection뿐 아니라 Few-Shot Object Detection과 zero-shot Open-Vocabulary Object Detection에서도 평가한다.

CVPR 2025에 발표되었다.

## 본 연구에서 가져올 요소

- unknown proposal/detection capability
- attribute 기반 unknown recognition과 다른 비교 축
- objectness uncertainty
- PROB 계열 benchmark 및 evaluation 구조

## 활용 계획

OWOBJ는 FOMO와 OW-OVD의 직접 대체로 단정하지 않고 별도의 unknown detection 비교군으로 재현해 둔다.

## 재현성 상태

공식 repository에 training/evaluation 관련 코드와 script가 존재하지만 repository 설명에는 release 상태와 관련된 이전 문구가 남아 있다. 실제 실험 시작 시 checkpoint, config 및 논문 결과의 재현 가능 여부를 먼저 확인한다.

## 공식 자료

논문:
https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Open-World_Objectness_Modeling_Unifies_Novel_Object_Detection_CVPR_2025_paper.html

공식 코드:
https://github.com/AI4Math-ShanZhang/OWOBJ

---

# 9. ByteTrack: Multi-Object Tracking by Associating Every Detection Box

## 역할

Detector와 독립적으로 persistent object state를 만드는 modular tracking Reference Baseline으로 사용한다.

## 핵심 특징

ByteTrack은 detection score가 높은 box만 association하는 대신 low-score detection도 기존 tracklet과 association하여 true object를 복구한다.

핵심 장점은 외부 detector 결과를 입력받아 tracker를 독립적으로 사용할 수 있다는 점이다.

공식 구현에서 다른 detector의 detection 결과를 BYTETracker에 전달하는 사용 방식을 제공한다.

## 본 연구에서 가져올 요소

- Persistent Object ID
- Frame 간 object association
- Detector-agnostic tracking interface
- object history 구성
- Provider 결과 재사용을 위한 object identity

## 활용 계획

FOMO, OW-OVD, OWOBJ 등 서로 다른 detector/unknown Provider에 동일 tracking interface를 적용하기 위한 modular baseline으로 재현해 둔다.

## 공식 자료

논문:
https://arxiv.org/abs/2110.06864

공식 코드:
https://github.com/FoundationVision/ByteTrack

---

# 10. OVTR: End-to-End Open-Vocabulary Multiple Object Tracking with Transformer

## 역할

Open-vocabulary perception과 tracking을 동시에 수행하는 강한 연속 영상 비교군으로 사용한다.

## 핵심 특징

OVTR은 end-to-end Open-Vocabulary Multiple Object Tracking을 수행한다.

주요 구성은 다음과 같다.

- Category Information Propagation
- Attention Isolation
- Dual-branch Decoder
- Multimodal Alignment

TAO dataset에서 base와 novel category를 대상으로 TETA, AssocA, ClsA를 평가한다.

공식 코드, script, checkpoint가 공개되어 있으며 OVTR-Lite도 제공된다.

## 본 연구에서 가져올 요소

- Open-vocabulary tracking Reference Baseline
- TAO dataset 평가 protocol
- persistent semantic state 비교
- base/novel category 분리 평가
- modular detector + tracker 방식과 end-to-end 방식 비교

## 활용 계획

ByteTrack 기반 modular 방식보다 강한 end-to-end 비교군으로 공식 설정 그대로 재현해 유지한다.

## 공식 자료

논문:
https://arxiv.org/abs/2503.10616

공식 코드:
https://github.com/jinyanglii/OVTR

---

# 11. Boosting Vision-Language Models Towards Cross-Domain Incremental Object Detection

## 시스템명

DGS

## 역할

지속 학습 영역의 최신 핵심 Reference Baseline으로 사용한다.

## 선정 이유

- CVPR 2026 Highlight 논문이다.
- Vision-Language Model 기반 Incremental Object Detection을 다룬다.
- 새 class 추가뿐 아니라 domain shift까지 포함하는 Cross-Domain Incremental Object Detection을 정의한다.
- 공식 구현이 공개되어 있다.
- 미확인 객체가 확인된 이후 새로운 class 또는 새로운 domain 정보를 기존 detector에 반영하는 프로젝트 흐름과 직접적으로 연결된다.

## 핵심 특징

DGS는 Dynamic Group Subspace를 사용하여 서로 다른 incremental task를 distribution에 따라 동적으로 group화한다.

주요 구성은 다음과 같다.

- Dynamic task grouping
- Task distribution 기반 routing
- Adapter consolidation
- Shared subspace construction
- Parameter growth control
- Dynamic training pipeline
- Stability-adaptivity balance

Grounding DINO 기반 incremental detector를 제공하고 LoRA, Adapter, MoE 등 PEFT module을 포함하는 공식 구현을 제공한다.

논문은 Cross-Domain Incremental Object Detection benchmark를 제안하고 여러 benchmark에서 SOTA 성능을 보고한다.

## 본 연구에서 가져올 요소

- 지속적으로 새로운 class와 domain을 학습하는 detection baseline
- VLM 기반 incremental detection
- PEFT 기반 업데이트
- task grouping과 adapter consolidation
- 기존 지식 유지와 새 환경 적응을 함께 평가하는 실험 구조
- 새로운 domain이 들어왔을 때의 stability-adaptivity 평가

## 프로젝트 요구사항 연결

- 학습 실행 전략 교체
- 새 환경 및 새 class 적응
- 기존 성능 유지 검증
- 모델 업데이트 후 회귀 평가
- 모델 및 학습 구성별 실행 프로파일 비교

## 활용 계획

DGS를 지속 학습의 가장 강한 최신 직접 baseline으로 우선 재현한다. DGS가 사용하는 공식 benchmark와 training protocol을 그대로 재현하는 것을 먼저 확보한다.

## 공식 자료

논문:
https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Boosting_Vision-Language_Models_Towards_Cross-Domain_Incremental_Object_Detection_CVPR_2026_paper.html

공식 코드:
https://github.com/Never-wx/dgs

---

# 12. H2ST: Hierarchical Two-Sample Tests for Continual Out-of-Distribution Detection

## 역할

운영 데이터가 기존 학습 분포에서 벗어났는지 판단하고 학습 후보 또는 추가 검증 대상으로 연결하는 Reference Method로 사용한다.

## 선정 이유

- CVPR 2025 논문이다.
- continual learning과 open-world OOD detection을 직접 연결한다.
- threshold 기반 단순 OOD 판정 대신 hypothesis testing을 사용한다.
- task-level identification을 지원한다.
- 공식 코드가 공개되어 있다.
- 운영 중 새로운 환경 또는 기존 모델이 설명하기 어려운 입력을 학습 후보로 선별하는 프로젝트 요구와 직접 연결된다.

## 핵심 특징

H2ST는 continual learning 환경에서 들어오는 입력이 기존 task distribution에 속하는지 판단한다.

기존 output confidence 중심 OOD 방법 대신 feature map과 hierarchical two-sample test를 이용한다.

주요 특징은 다음과 같다.

- threshold-free hypothesis testing
- feature-map 기반 OOD detection
- hierarchical task-level detection
- continual open-world setting
- replay-based Task Incremental Learning framework와의 결합 가능

## 본 연구에서 가져올 요소

- 학습 필요성 판단을 위한 변화 감지 baseline
- OOD sample 선별
- task identity 추정
- confidence threshold와 다른 변화 감지 비교군
- 학습 후보 데이터 선별 기준

## 활용 계획

H2ST 자체의 threshold-free 구조를 변경하지 않고 그대로 재현한 결과를 먼저 확보한다.

## 공식 자료

논문:
https://openaccess.thecvf.com/content/CVPR2025/html/Liu_H2ST_Hierarchical_Two-Sample_Tests_for_Continual_Out-of-Distribution_Detection_CVPR_2025_paper.html

공식 코드:
https://github.com/YuhangLiuu/H2ST

---

# 13. Revisiting Generative Replay for Class Incremental Object Detection

## 시스템명

RGR-IOD

## 역할

Incremental Object Detection에서 catastrophic forgetting을 줄이기 위한 최신 강한 replay baseline으로 사용한다.

## 선정 이유

- CVPR 2025 논문이다.
- Class Incremental Object Detection을 직접 다룬다.
- PASCAL VOC와 MS COCO에서 SOTA 결과를 보고한다.
- 공식 PyTorch 구현이 공개되어 있다.
- 새 데이터를 학습하면서 기존 객체 class의 성능을 유지해야 하는 프로젝트 요구와 직접 연결된다.

## 핵심 특징

RGR-IOD는 old class data를 직접 계속 저장하는 대신 Stable Diffusion 기반 generative replay를 활용한다.

주요 구성은 다음과 같다.

- generative replay
- old detector와 stage-wise detector 기반 pseudo labeling
- Similarity-based Cross Sampling
- old/new class confusion sample 선택
- synthetic and real data joint training

논문은 forgetting이 localization보다 classification sub-task에서 더 크게 나타나는 점을 이용하여 replay data를 구성한다.

## 본 연구에서 가져올 요소

- catastrophic forgetting 평가 방법
- old/new class incremental detection baseline
- replay 전략
- 기존 지식 유지 성능 비교
- 학습 데이터 선택과 replay 비용 비교

## 활용 계획

지속 학습 후보 중 하나로 재현하되 DGS와 역할을 구분한다.

- DGS: 최신 VLM 기반 cross-domain incremental detection
- RGR-IOD: replay 기반 class incremental detection

## 공식 자료

논문:
https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Revisiting_Generative_Replay_for_Class_Incremental_Object_Detection_CVPR_2025_paper.html

공식 코드:
https://github.com/qiangzai-lv/RGR-IOD

---

# 14. Ekya: Continuous Learning of Video Analytics Models on Edge Compute Servers

## 역할

지속 학습과 실시간 inference가 같은 제한된 edge GPU 자원을 공유하는 상황의 시스템 Reference Baseline으로 사용한다.

## 선정 이유

- NSDI 2022의 system research이다.
- edge video analytics에서 data drift와 continuous retraining을 직접 다룬다.
- inference와 retraining의 자원 경쟁을 scheduler가 관리한다.
- micro-profiling을 통해 retraining configuration의 미래 효용을 짧은 실행으로 추정한다.
- 공식 코드와 Cityscapes, Waymo, UrbanTraffic, UrbanBuilding 실행 절차가 공개되어 있다.
- 새로운 학습 알고리즘과 scheduler를 교체할 수 있는 확장 지점을 공식 구현이 제공한다.

최신 논문은 아니지만 프로젝트의 지속 학습, 실행 위치, 자원 최소화, 학습과 운영 추론의 격리 요구를 동시에 다루는 직접적인 시스템 연구이므로 유지한다.

## 핵심 특징

Ekya는 edge server에서 여러 live video stream의 inference와 retraining job을 함께 실행한다.

핵심 구성은 다음과 같다.

- Continuous retraining
- Micro-profiler
- Thief Scheduler
- GPU resource allocation
- Retraining configuration selection
- Live inference and background retraining coordination

Micro-profiler는 retraining job을 짧게 실행하여 이후 성능을 추정한다.

Thief Scheduler는 inference와 retraining job 사이에서 작은 resource chunk를 이동시키면서 전체 accuracy utility를 높이는 resource allocation을 선택한다.

저자 결과에서는 baseline scheduler보다 accuracy gain이 29% 높고 동일 accuracy를 얻기 위해 baseline이 4배 많은 GPU resource를 필요로 했다고 보고한다.

## 본 연구에서 가져올 요소

- 지속 학습 system architecture
- inference와 training resource competition model
- micro-profiling
- retraining configuration profiling
- training/inference scheduler
- data drift에 따른 periodic retraining
- custom scheduler 및 custom continual learning method 확장 구조

## 프로젝트 요구사항 연결

- 학습 실행 위치 선택
- 자원 제약 하 지속 학습
- 학습 기능과 운영 추론의 자원 경쟁 측정
- 학습 관리 overhead 측정
- 학습 configuration 변경
- edge/server 학습 실행 비교

## 활용 계획

지속 학습 전체 시스템 비교의 필수 baseline으로 원 저자 설정 그대로 재현한다. DGS 또는 RGR-IOD와 같은 학습 방법은 모델 업데이트 알고리즘으로, Ekya는 그 학습을 언제 수행하고 자원을 얼마나 배정할지 결정하는 system baseline으로 역할을 구분한다.

## 공식 자료

논문:
https://www.usenix.org/conference/nsdi22/presentation/bhardwaj

공식 코드:
https://github.com/edge-video-services/ekya

---

# 15. OCTOPINF: Workload-Aware Inference Serving for Edge Video Analytics

## 역할

실시간 자원 관측과 workload 변화에 따라 edge inference resource를 조정하는 최신 serving baseline으로 사용한다.

## 선정 이유

- IEEE PerCom 2025 논문이다.
- Edge Video Analytics를 직접 대상으로 한다.
- workload variability, network instability, GPU resource contention을 다룬다.
- fine-grained resource allocation, adaptive batching, edge-server workload balancing을 포함한다.
- 실제 testbed에서 baseline 대비 최대 10배 effective throughput 향상을 보고한다.
- 공식 코드가 공개되어 있다.

## 핵심 특징

OCTOPINF는 dynamic edge environment에서 여러 DNN inference workload를 효율적으로 serving한다.

주요 구성은 다음과 같다.

- fine-grained resource allocation
- adaptive batching
- workload balancing
- edge-server scheduling
- GPU co-location
- spatiotemporal scheduling
- SLO compliance

## 본 연구에서 가져올 요소

- 실시간 inference serving baseline
- workload/resource contention 대응
- GPU allocation
- adaptive batching
- edge/server load balancing
- SLO 기반 평가
- serving scheduler overhead 측정

## 활용 계획

ApproxDet과 역할을 구분해 재현한다.

- ApproxDet: content와 contention으로 어떤 model/configuration을 실행할지 선택
- OCTOPINF: 선택된 여러 inference workload를 제한된 edge/server resource에서 어떻게 serving할지 관리

## 공식 자료

논문:
https://doi.org/10.1109/PerCom64205.2025.00032

공식 코드:
https://github.com/tungngreen/PipelineScheduler

---

# 16. E4: Energy-Efficient DNN Inference for Edge Video Analytics via Early Exiting and DVFS

## 역할

CPU/GPU clock과 frame complexity까지 포함하여 energy-aware configuration을 선택하는 최신 Reference Research로 사용한다.

## 선정 이유

- AAAI 2025 논문이다.
- edge video analytics를 대상으로 한다.
- 입력 frame complexity와 hardware operating state를 함께 고려한다.
- early exit와 DVFS를 함께 최적화한다.
- just-in-time profiler를 사용한다.
- 저자 실험에서 최대 2.8배 speedup과 평균 26% energy saving을 보고한다.

## 핵심 특징

E4는 attention-based cascade로 frame diversity를 분석해 적절한 DNN early-exit point를 결정한다.

JIT profiler는 coordinate descent를 사용하여 선택된 exit point까지의 각 layer 실행에 대해 CPU와 GPU clock frequency를 공동 최적화한다.

주요 요소는 다음과 같다.

- frame complexity awareness
- early exit
- DVFS
- JIT profiling
- CPU/GPU frequency optimization
- energy-performance trade-off

## 본 연구에서 가져올 요소

- energy-aware Provider Profile 후보
- hardware clock state를 포함하는 profiling
- JIT profiling
- frame complexity 기반 configuration 변경
- latency/accuracy 외 energy를 포함하는 평가 구조

## 활용 계획

전력 측정이 가능한 하드웨어에서만 정량 비교 대상으로 사용한다. 우선 E4 논문의 설정과 결과를 분석하고, 공식 구현 확보 여부를 별도로 확인한다. Energy metric을 사용하기 전에는 실제 측정 장비 또는 신뢰 가능한 hardware energy counter를 확보한다.

## 공식 자료

논문:
https://doi.org/10.1609/aaai.v39i1.32104

공식 코드:
명시적으로 확인된 공식 repository 없음

---

# 17. 자원 관측 구현 기술

이 절은 논문 비교군이 아니라 Resource Observation Layer를 구현하기 위한 공식 기술 자료이다.

## OpenTelemetry

### 역할

각 Provider의 inference, training, selection, queue, transport 과정에 대한 trace와 metric을 공통 형식으로 수집한다.

### 수집 후보

- Provider start/end
- queue waiting time
- scheduling overhead
- inference latency
- training latency
- error/timeout event
- object/evidence correlation ID

공식 문서:
https://opentelemetry.io/docs/

---

## Prometheus Node Exporter

### 역할

Linux node의 CPU, memory, filesystem, network 등 system metric을 수집한다.

공식 코드:
https://github.com/prometheus/node_exporter

공식 문서:
https://prometheus.io/docs/guides/node-exporter/

---

## NVIDIA DCGM Exporter

### 역할

NVIDIA GPU가 있는 실행 노드에서 GPU utilization, memory, temperature, clock 등 GPU 상태를 Prometheus metric으로 제공한다.

공식 코드:
https://github.com/NVIDIA/dcgm-exporter

공식 문서:
https://docs.nvidia.com/datacenter/dcgm/latest/installation/install-dcgm-exporter.html

---

## Open Edge Platform Metrics Manager

### 역할

heterogeneous edge node에서 CPU, RAM, temperature, GPU/NPU utilization, power, frequency 등을 수집할 수 있는 최신 edge telemetry 구현 후보로 사용한다.

Intel Arc GPU와 Intel NPU를 포함한 metric을 제공하며 OpenTelemetry와 Telegraf 입력을 수용한다.

공식 문서:
https://docs.openedgeplatform.intel.com/2026.2/edge-ai-libraries/metrics-manager/index.html

---

# 18. 지속 학습 및 자원 관측 재현 시 측정 항목

지속 학습과 자원 관측을 별개의 기능으로 재현하되, 재현 검증 시 다음 항목을 측정한다.

## 학습 후보 선별 (Reference: H2ST)

측정:

- 실제 학습에 사용된 sample 수
- label 또는 user confirmation 수
- 새로운 task/domain 성능
- 기존 task 성능

## 학습 알고리즘 (Reference: DGS, RGR-IOD)

측정:

- new-task accuracy
- old-task accuracy
- forgetting
- training time
- peak memory
- training data amount

## 학습 자원 배치 (Reference: Ekya)

측정:

- live inference accuracy
- live inference latency
- retraining completion time
- GPU allocation
- training/inference interference

## 실행 자원 관리 (Reference: ApproxDet, DACC, OCTOPINF, E4)

측정:

- latency
- p95 latency
- throughput
- resource utilization
- queue
- network
- energy when measurable

---

# 19. 논문별 역할 요약

우선순위·최종 채택 여부는 아직 고정하지 않는다. 아래는 각 baseline이 어떤 기능을 재현 대상으로 제공하는지에 대한 요약일 뿐이다.

| 논문 | 핵심 기능 | 연구에서의 역할 |
|---|---|---|
| ApproxDet | content/resource-aware accuracy-latency prediction 및 scheduling | 실행 성능 예측·선택 baseline |
| FOMO | foundation model과 shared attribute 기반 unknown detection | unknown perception baseline |
| OW-OVD | attribute selection과 uncertainty를 결합한 OWOD/OVD | 최신 강한 unknown baseline |
| DGS | cross-domain VLM incremental object detection | 최신 지속 학습 baseline |
| Ekya | edge inference와 continuous retraining의 자원 공동 관리 | 지속 학습 시스템 baseline |
| DACC | content-aware expected gain 및 edge-cloud offloading | adaptive execution baseline |
| OCTOPINF | workload-aware inference serving 및 GPU scheduling | 자원 관측·실행 serving baseline |
| H2ST | continual OOD detection과 task identification | 학습 후보 및 변화 감지 baseline |
| RGR-IOD | generative replay 기반 class incremental detection | catastrophic forgetting 비교군 |
| nn-Meter | hardware-specific DNN latency prediction | 실행 프로파일 생성 비용 절감 참고 |
| ByteTrack | detector-agnostic multi-object tracking | modular persistent object baseline |
| OVTR | end-to-end open-vocabulary tracking | 강한 연속영상 비교군 |
| E4 | frame-aware early exit와 DVFS | energy-aware profile 참고 |
| OWOBJ | class-agnostic probabilistic objectness | unknown detection 보조 비교군 |

---

# 20. 재현 대상 기능별 정리

아래는 기능 영역별로 어떤 baseline을 재현 대상으로 두는지 정리한 것이며, 최초 구현 우선순위나 최종 조합을 확정하는 목록이 아니다.

## Perception

- FOMO
- OW-OVD

## Object Persistence

- ByteTrack

## Performance Prediction and Selection

- ApproxDet
- DACC

## Resource-aware Serving

- OCTOPINF

## Runtime Profiling

- 실제 측정 profile
- nn-Meter latency prediction
- OpenTelemetry
- Prometheus Node Exporter
- GPU 사용 시 NVIDIA DCGM Exporter

## Continual Change Detection

- H2ST

## Continual Learning

- DGS
- RGR-IOD

## Training/Inference Resource Coordination

- Ekya

## Energy-aware Reference

- E4

## 추가 비교

- OVTR
- OWOBJ

---

# 21. 이후 실험에서 변경할 수 있는 요소

아래 항목은 현재 제안 방법으로 확정하지 않고 실험 변수 후보로만 관리한다.

- frame-level Provider execution
- object-level Provider execution
- Provider result reuse
- Provider execution order
- Provider count
- Provider capability 분할
- sequential execution
- parallel execution
- Static Profile
- ApproxDet-style prediction
- DACC-style prediction
- measured latency
- nn-Meter predicted latency
- average latency
- p95 latency
- content-only predictor
- content + hardware-state predictor
- visual information only
- visual + infrastructure information
- single Provider
- multiple Providers
- FOMO
- OW-OVD
- OWOBJ
- ByteTrack
- OVTR

각 실험에서는 가능한 경우 한 번에 하나의 요소만 변경하고 나머지 입력, 모델, 데이터, hardware condition, evaluation code를 동일하게 유지한다.

---

# 22. 개별 논문 raw markdown 노트

각 baseline의 상세 Obsidian 분석 노트는 `papers/` 디렉터리에 있다. 논문 선정 자체가 아직 고정된 것이 아니므로, 이 목록도 확정된 최종 구성이 아니라 지금까지 작성된 재현 대상 기록이다.

- papers/approxdet.md
- papers/fomo.md
- papers/ow-ovd.md
- papers/dacc.md
- papers/dgs.md
- papers/ekya.md
- papers/h2st.md
- papers/rgr-iod.md
- papers/octopinf.md
- papers/nn-meter.md
- papers/owobj.md
- papers/bytetrack.md
- papers/ovtr.md
- papers/e4.md

각 노트는 원 논문이 실제로 해결한 문제, 입력과 출력, 알고리즘 구조, 학습 또는 profiling 방법, runtime decision 과정, 데이터셋, baseline, 평가 metric, 저자가 보고한 결과, 한계, 공식 구현 방법에 집중한다.

내 아이디어를 이 baseline들 위에 적용해보는 실험 계획은 `ideas/` 디렉터리에서 별도로 관리한다.
