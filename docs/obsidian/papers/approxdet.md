# ApproxDet: Content and Contention-Aware Approximate Object Detection for Mobiles

## 메타데이터
- categories: [[Multi-branch Object Detection Framework]], [[Content-aware Feature Extraction]], [[Latency-Accuracy Prediction Model]], [[Latency SLA-driven Scheduler]], [[Contention Sensor]]
- domain: [[모바일 비디오 객체 탐지]], [[근사 컴퓨팅]]
- source: Ran Xu, Chen-lin Zhang, Pengcheng Wang, Jayoung Lee, Subrata Mitra, Somali Chaterji, Yin Li, Saurabh Bagchi, "ApproxDet: Content and Contention-Aware Approximate Object Detection for Mobiles," Proceedings of the 18th ACM Conference on Embedded Networked Sensor Systems (SenSys '20), 2020.
- url: https://doi.org/10.1145/3384419.3431159
- year: 2020
- authors: Ran Xu et al.
- venue: The 18th ACM Conference on Embedded Networked Sensor Systems (SenSys '20)

## 1. 핵심 요약
- 모바일·임베디드 기기에서 실행되는 비디오 객체 탐지 시스템이 런타임에 겪는 세 가지 dynamism, 즉 (1) 입력 영상 콘텐츠 특성 변화, (2) co-located 애플리케이션으로 인한 연산 자원 경합(contention) 변화, (3) 사용자의 latency-accuracy 요구사항 변화에 적응하지 못한다는 문제를 다룬다.
- Faster R-CNN 기반 multi-branch object detection kernel과 latency SLA-driven scheduler, approximable video object tracking을 결합한 단일 모델(single model) 기반 end-to-end 시스템 ApproxDet을 제안한다.
- ImageNet VID 데이터셋과 NVIDIA Jetson TX2 보드에서 AdaScale, Faster R-CNN, Faster R-CNN+MedianFlow, YOLOv3와 비교 평가했으며, YOLOv3 대비 52%(초록 기준)/52.9%(결론 기준) 낮은 latency와 11.1% 높은 accuracy를 달성했다고 보고한다.

## 2. 문서 목적
- 해결하려는 문제: 기존 비디오 분석 시스템 대부분이 사전에 정의된 latency 또는 accuracy 요구사항으로 오프라인 학습되어, 입력 영상 콘텐츠 변화와 기기 내 자원 경합, 사용자 요구사항 변화라는 런타임 조건 변화에 적응하지 못한다.
- 기술적 목표: 단일 모델 위에 여러 approximation knob을 두어 런타임에 branch를 전환함으로써, 자원 경합 하에서도 latency 요구사항을 지키면서 accuracy를 최대화하는 content-and-contention-aware 적응형 비디오 객체 탐지 프레임워크를 구현하는 것.
- 다루는 범위: Faster R-CNN(ResNet-50 backbone) 기반 탐지 커널에 노출된 5개 tuning knob(sampling interval, input shape, number of proposals, tracker type, downsampling ratio), offline 학습되는 latency/accuracy 예측 모델, CPU/memory bandwidth/GPU 3차원 synthetic contention generator, NVIDIA Jetson TX2에서의 end-to-end 평가.

## 3. 핵심 개념 상세
### Multi-branch Object Detection Framework
- 원문 표현: "we introduce a multi-branch object detection kernel (layered on Faster R-CNN)... We refer to the execution branch with a particular configuration of the approximation knob as an approximation branch (AB)."
- 정의: Faster R-CNN(ResNet-50) 탐지 DNN과 MedianFlow·KCF·CSRT·Dense Optical Flow 중 선택되는 tracker를 결합하고, sampling interval(si), input shape, number of proposals(nprop), tracker 종류, tracker downsampling ratio(ds)라는 5개 tuning knob으로 구성되는 configuration의 실행 경로를 approximation branch(AB)라 부른다.
- 역할: 여러 모델을 동시에 적재하는 앙상블 방식 대신 단일 모델의 configuration 전환만으로 accuracy-latency tradeoff의 여러 지점을 실행해, 전환 오버헤드(측정된 switching latency 최대 12ms)와 메모리 사용을 줄인다.

### Content-aware Feature Extraction
- 원문 표현: "we mainly consider two types of content features" — Object Basic Features(number of objects, average object size)와 Object Movement Features(객체 중심의 최근 프레임 간 평균 이동 거리).
- 정의: tracker latency는 객체 개수·면적에, accuracy는 객체 이동 속도(움직임)에 영향받는다는 관찰에 근거해 detection DNN 출력에서 추가 비용 없이 추출하는 두 종류의 런타임 콘텐츠 특징.
- 역할: latency·accuracy 예측 모델의 입력 특징으로 사용되어, 검증셋 평균만 사용하는 content-agnostic 예측 대비 개별 영상의 특성을 반영한 예측을 가능하게 한다.

### Latency-Accuracy Prediction Model
- 원문 표현: "𝐿𝐷𝑁𝑁 = 𝑓𝐷𝑁𝑁(𝑛𝑝𝑟𝑜𝑝, 𝑠ℎ𝑎𝑝𝑒, ℎ𝑒𝑖𝑔ℎ𝑡, 𝑤𝑖𝑑𝑡ℎ, 𝑐𝑜𝑛𝑡𝑒𝑛𝑡𝑖𝑜𝑛)"; "we propose a content-aware model that estimates the accuracy based on the input video content."
- 정의: detection DNN latency와 tracker latency는 각각 quadratic regression으로, accuracy는 content-agnostic 단계에서는 decision tree(CART), content-aware 단계에서는 linear regression(content-agnostic 대비 MSE 8% 개선)으로 오프라인 학습되는 예측 모델.
- 역할: 각 approximation branch가 향후 프레임에서 가질 latency와 accuracy(상대 mAP)를 사전에 추정해 scheduler가 branch를 선택할 근거를 제공한다.

### Latency SLA-driven Scheduler
- 원문 표현: "𝑏𝑜𝑝𝑡 = argmax𝑏∈𝐵ˆ(𝐴𝑏), if 𝐵ˆ ≠ ∅; argmin𝑏∈B(𝐿𝑒𝑠𝑡,𝑏) otherwise."
- 정의: 사용자가 지정한 latency requirement L_req를 만족하는 branch 집합(B̂) 중 추정 accuracy가 가장 높은 branch를 선택하고, 만족하는 branch가 없으면 추정 latency가 가장 낮은 branch를 선택하는 의사결정 로직으로, 최소 sw = max(8, si) 프레임마다 재평가된다.
- 역할: latency 요구사항을 지키면서 accuracy를 최대화하는 branch를 런타임에 동적으로 선택함으로써, 정적으로 고정된 모델 대비 자원 경합·콘텐츠 변화에 적응한다.

### Contention Sensor
- 원문 표현: "The log-based contention sensor tries to find a contention level where the offline latency log matches the averaged online latency most closely."
- 정의: OS 권한 없이 다른 프로세스의 CPU/GPU 사용률을 직접 측정하는 대신, 최근 몇 회 실행에서 관측한 online latency를 offline latency log와 nearest-neighbor로 매칭해 현재 contention level을 추정하는 log-based sensor. 평가를 위해 CPU/memory bandwidth(STREAM 벤치마크 변형)/GPU 3차원의 orthogonal synthetic contention generator(CG)를 별도로 구현했다.
- 역할: 사용자 공간(user-space) 애플리케이션으로서 OS 특권 없이 자원 경합을 black-box로 추정해 latency 예측 모델의 contention 입력값을 제공한다.

## 4. 구조 및 흐름
1. 사용자 latency requirement와 비디오 프레임이 Adaptive Object Detection Framework(AODF)에 입력된다.
2. Content-aware feature extractor가 현재 프레임의 height, width와 직전 프레임의 n_obj, avg_size, 그리고 과거 프레임들의 movement를 추출하고, Contention sensor가 offline latency log 매칭을 통해 현재 contention level을 추정한다.
3. Scheduler가 accuracy model과 latency model에 이 특징들을 입력해 각 approximation branch의 추정 accuracy·latency를 계산하고, latency requirement를 만족하는 branch 중 최고 accuracy branch(만족 branch가 없으면 최저 latency branch)를 선택한다.
4. 선택된 configuration으로 Multi-branch detection framework 내 Detection DNN(sampling interval마다) 또는 Tracker(그 사이 프레임)가 실제 입력 프레임을 처리해 detection 결과를 산출하며, 이 결과는 다시 다음 스케줄링 주기의 content feature로 피드백된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| YOLOv3 대비 52%(초록)/52.9%(결론) 낮은 latency, 11.1% 높은 accuracy를 달성하며 모든 baseline을 능가한다 | ImageNet VID test set에서 ApproxDet과 AdaScale, Faster R-CNN, Faster R-CNN+MedianFlow, YOLOv3를 동일 학습/평가 데이터 분할로 비교한 end-to-end 실험(Section 6.4, Figure 7~10) |
| 50% GPU contention이 주입되어도 latency SLA를 유지한다 | 무경합 대비 accuracy 저하 약 2%, 95th percentile latency 변화 최대 16%인 반면, 최선의 baseline인 FRCNN+MF는 latency가 25~50%, FRCNN·AdaScale은 75~120% 증가함(Section 6.4) |
| Branch 간 전환 비용이 낮아 실시간 적응이 가능하다 | Detection DNN 내부 branch 간 switching latency가 heatmap 측정 결과 최대 12ms(Section 6.7, Figure 15); scheduler overhead는 평균 11.09ms/실행이며 si 프레임마다 1회만 실행되어 전체 latency의 1% 미만을 차지함(Table 5) |
| Content-aware accuracy 예측이 content-agnostic 예측보다 우수하다 | Content-aware(linear regression) 모델이 content-agnostic(decision tree) 모델 대비 MSE 기준 8% 개선(Section 4.4.2) |
| 소수의 프로파일링 샘플만으로도 정확한 예측 모델을 학습할 수 있다 | latency 모델은 백만 개 feature point 중 15개(detection)·169개(tracker) 샘플만으로, accuracy 모델은 전체 configuration의 20%만으로 test set에서 74.58 MSE를 달성(oracle 71.65 MSE와 근접)(Section 4.6, 6.6) |

## 6. 한계 및 부족한 점
- Contention을 black-box로 취급해 OS 권한 없이 정확한 contention의 종류나 원인을 알 수 없으며, latency에 동일한 영향을 주는 서로 다른 contention 시나리오를 구별하지 못해 sub-optimal한 적응이 발생할 수 있다고 저자들이 명시한다.
- 평가가 주로 synthetic GPU contention(및 Gaussian Elimination 실제 앱 1건)에 한정되어 있어, 다양한 실제 모바일 백그라운드 워크로드 trace에 대한 평가가 future work로 남아 있다.
- 1080p·2K 등 고해상도 영상 데이터셋과 더 낮은 연산 성능의 기기·스마트폰 등 다른 모바일 플랫폼에 대한 평가는 아직 수행되지 않았다고 명시한다.
- 일부 tracker(CSRT 등)는 고경합 상황에서 latency가 불안정해 tracker latency 예측 모델의 RMSE가 다른 tracker보다 크게 나타나며, 저자들은 이에 대한 추가 탐구를 future work로 남긴다(Table 4).

## 7. 원문 기반 핵심 문장
> In this paper we introduce ApproxDet, an adaptive video object detection framework for mobile devices to meet accuracy-latency requirements in the face of changing content and resource contention scenarios.
