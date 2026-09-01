# nn-Meter: Towards Accurate Latency Prediction of Deep-Learning Model Inference on Diverse Edge Devices

## 메타데이터
- categories: [[커널 수준 지연시간 예측]], [[자동 커널 탐지]], [[적응형 데이터 샘플링]], [[nn-Meter Builder]]
- domain: [[엣지 AI 추론]], [[하드웨어 인식 신경망 아키텍처 탐색]]
- source: Li Lyna Zhang, Shihao Han, Jianyu Wei, Ningxin Zheng, Ting Cao, Yuqing Yang, Yunxin Liu, "nn-Meter: Towards Accurate Latency Prediction of Deep-Learning Model Inference on Diverse Edge Devices," Proceedings of the 19th Annual International Conference on Mobile Systems, Applications, and Services (MobiSys), 2021.
- url: https://doi.org/10.1145/3458864.3467882
- year: 2021
- authors: Li Lyna Zhang et al.
- venue: MobiSys 2021 (19th ACM International Conference on Mobile Systems, Applications, and Services)

## 1. 핵심 요약
- nn-Meter는 다양한 edge device 상에서 DNN 모델의 추론 지연시간(inference latency)을 실제 device 배포 없이 정확하게 예측하는 시스템으로, 전체 모델 추론을 kernel 단위로 나누어 kernel 수준에서 지연시간을 예측한다.
- kernel은 device 상의 기본 스케줄링 단위로, 단일 operator이거나 여러 operator가 fusion된 형태이며, 모델 전체 지연시간은 모든 kernel 지연시간의 합으로 계산된다.
- 핵심 기술은 두 가지다. (i) kernel detection은 잘 설계된 test case 집합으로 device의 operator fusion 규칙을 자동 탐지하고, (ii) adaptive data sampler는 방대한 configuration 공간에서 예측에 가장 유용한 설정만 선택적으로 샘플링한다.
- Pixel4(Cortex-A76 CPU), Mi9(Adreno640 GPU), Pixel3XL(Adreno630 GPU), Intel Movidius NCS2(Myriad VPU) 4개 edge platform, 26,000개 모델 데이터셋으로 평가했으며 각각 99.0%, 99.1%, 99.0%, 83.4%의 예측 정확도를 얻었다.
- FLOPs, FLOPs+MAC, BRP-NAS(GCN 기반) 등 기존 baseline과 비교해 평균 89.2% 정확도로, FLOPs(22.1%), FLOPs+MAC(17.1%), BRP-NAS(8.5%)를 크게 상회했다.
- MobiSys 2021 Best Paper Award를 수상했다.

## 2. 문서 목적
- 해결하려는 문제: 실제 device에 모델을 배포하지 않고도 임의의 DNN 모델이 다양한 edge device(mobile CPU/GPU, VPU 등)에서 갖는 추론 지연시간을 정확히 예측하는 문제. 실측은 다양한 inference framework와 chip에 대한 배포 엔지니어링 비용이 크고, NAS처럼 대량의 후보 모델(예: ProxylessNAS의 약 0.3 million 모델 탐색)을 다룰 때는 시간이 지나치게 많이 든다.
- 기술적 목표: operator fusion과 같은 hardware/framework 수준의 최적화를 포착하면서도, 학습에 쓰이지 않은 unseen model graph에도 일반화되는 kernel-level latency predictor를 만드는 것.
- 다루는 범위: mobile CPU, mobile GPU, Intel VPU 등 4개 edge platform에 대한 kernel-level latency predictor 구축·평가, TensorFlow(.pb)/ONNX/PyTorch/NNI IR/nn-Meter IR 모델 입력 지원, 그리고 custom device를 위한 nn-Meter Builder 제공.

## 3. 핵심 개념 상세
### 커널 수준 지연시간 예측
- 원문 표현: "nn-Meter divides a whole model inference into kernels, i.e., the execution units of fused operators on a device, and conduct kernel-level prediction."
- 정의: kernel은 device 상에서 스케줄링되는 기본 단위로 단일 operator이거나 여러 operator가 fusion된 결과이며, 전체 모델 추론은 여러 kernel로 분해되고 모델 전체 지연시간은 kernel별 지연시간의 합으로 산출된다.
- 역할: operator 단위로 지연시간을 단순 합산하는 기존 operator-level 방식과 달리, 실제 device/framework에서 발생하는 operator fusion 등 그래프 최적화를 반영해 예측 정확도를 높인다.

### 자동 커널 탐지
- 원문 표현: "kernel detection to automatically detect the execution unit of model inference via a set of well-designed test cases"
- 정의: 임의의 두 operator에 대해 Op1 단독, Op2 단독, Op1+Op2 결합의 3개 test graph를 생성하고 측정된 지연시간 T_op1, T_op2, T(op1,op2)에 대해 T_op1+T_op2-T(op1,op2) > α·min(T_op1,T_op2) 조건을 만족하면 두 operator가 fusion 가능하다고 판정하는 규칙 기반 탐지 방법이며, 탐지된 fusion rule을 대상 모델 그래프에 적용해 최대로 fusion된 kernel 단위를 탐색한다(kernel search by fusion rules).
- 역할: 내부 구현이 공개되지 않은 black-box device/inference framework에 대해서도 test case 측정만으로 operator fusion 규칙을 자동으로 알아내, 별도의 hardware 내부 지식 없이 kernel 경계를 결정할 수 있게 한다.

### 적응형 데이터 샘플링
- 원문 표현: "adaptive sampling to efficiently sample the most beneficial configurations from a large space to build accurate kernel-level latency predictors"
- 정의: conv-bn-relu처럼 configuration 공간이 매우 큰(입력 HW·kernel size·stride·Cin·Cout 조합으로 약 0.7 billion) kernel에 대해, 무작위 샘플링 대신 model zoo에서 학습한 사전 확률 분포로 실제 모델 설계에서 자주 나타나는 configuration을 우선 샘플링하고, 예측이 부정확한 데이터 주변을 추가로 fine-grained 샘플링하는 기법.
- 역할: Cout 등 일부 차원에서 지연시간이 계단형(step) 패턴을 보여 무작위 샘플링이 hardware-crucial한 데이터를 놓칠 수 있는 문제를 완화하고, 적은 측정 비용으로도 새로운 device용 predictor를 구축할 수 있게 한다.

### nn-Meter Builder
- 원문 표현: "Use nn-Meter to build latency predictor for your own device!"
- 정의: 사용자가 자신의 backend(device)를 연결하면 Backend Builder가 test case를 생성·실행해 지연시간을 profiling하고, Rule Tester가 fusion rule을 탐지하며, Predictor Builder가 adaptive data sampling으로 kernel별 latency predictor를 학습하는 구성의 building toolkit.
- 역할: nn-Meter가 기본 제공하는 4개 platform 외의 새로운 inference framework·hardware chip에 대해서도 사용자가 자체 latency predictor를 구축해 등록할 수 있게 해 확장성을 제공한다.

## 4. 구조 및 흐름
1. 입력 모델(TensorFlow .pb, ONNX, PyTorch NN module, nn-Meter IR Graph, NNI IR Graph)을 nn-Meter의 공통 IR graph로 변환한다.
2. Kernel Detector가 대상 device에서 사전에 탐지된 fusion rule을 적용해 모델 그래프를 kernel 단위로 분해한다(kernel search by the fusion rules).
3. 각 kernel을 해당 platform용 RandomForest 기반 kernel latency predictor(구현체 기준 CPU 22종, GPU 26종, VPU 22종 kernel 탐지)에 입력해 kernel별 latency를 예측한다.
4. 전체 모델의 예측 latency는 모든 kernel latency의 합으로 산출되며, custom device의 경우 nn-Meter Builder(Backend 연결 → Rule Tester → Predictor Builder)로 새 predictor를 만들어 동일 파이프라인에 등록할 수 있다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| nn-Meter는 4개 edge platform에서 매우 높은 지연시간 예측 정확도를 달성한다 | 26k 모델 벤치마크 데이터셋에서 Pixel4(Cortex-A76 CPU) 99.0%, Mi9(Adreno640 GPU) 99.1%, Pixel3XL(Adreno630 GPU) 99.0%, Intel Movidius NCS2(Myriad VPU) 83.4%의 예측 정확도 확인 |
| nn-Meter는 기존 FLOPs·그래프 기반 방법보다 unseen model graph에 대한 일반화 성능이 뛰어나다 | 평균 정확도 비교에서 nn-Meter 89.2% vs FLOPs 22.1%, FLOPs+MAC 17.1%, BRP-NAS(GCN) 8.5% |
| kernel-level 예측이 operator-level 합산 방식보다 우수하다 | conv-bn-relu 등에서 operator-level 대비 CPU +8%, GPU +45.5%, VPU +75.1% 높은 예측 정확도 달성 |
| adaptive data sampling이 random sampling보다 효율적으로 정확한 predictor를 만든다 | 동일 측정 비용 조건에서 conv-bn-relu predictor의 예측 성능을 random sampling과 비교해 우위를 보였고, 새 device용 predictor 구축에 필요한 측정 비용을 낮춤 |

## 6. 한계 및 부족한 점
- Intel Movidius NCS2(Myriad VPU)에서의 예측 정확도(83.4%)는 CPU/GPU(약 99%) 대비 뚜렷하게 낮아, device 종류에 따라 예측 정확도 편차가 있다.
- 실측 평가 대상 device가 mobile CPU, mobile GPU, Intel VPU 계열 4개 device로 한정되어 있으며, 슬라이드 자료에 언급된 Edge TPU·DSP 등은 실제 평가 대상에 포함되지 않았다.
- PyTorch 모델을 예측하려면 ONNX/onnx-simplifier 또는 NNI 패키지를 통한 shape inference가 추가로 필요하다.
- 공식 GitHub 저장소(microsoft/nn-Meter)는 2025년 9월 12일자로 archive되어 read-only 상태이며, 이후 추가 유지보수가 이루어지지 않는다.

## 7. 원문 기반 핵심 문장
> nn-Meter is a novel and efficient system to accurately predict the inference latency of DNN models on diverse edge devices. The key idea of nn-Meter is dividing a whole model inference into kernels, i.e., the execution units on a device, and conducting kernel-level prediction.
