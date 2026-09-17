# Perceive What Matters: Relevance-Driven Scheduling for Multimodal Streaming Perception

## 메타데이터
- categories: Relevance 기반 지각 스케줄링, Perception Module 선택적 활성화, Perception Reward Estimation, Keyframe Accuracy
- domain: [[로보틱스·다중로봇]]
- source: Huang, Dingcheng, Zhang, Xiaotong, Youcef-Toumi, Kamal. "Perceive What Matters: Relevance-Driven Scheduling for Multimodal Streaming Perception." IEEE International Conference on Robotics and Automation (ICRA), 2026.
- url: https://arxiv.org/abs/2603.13176
- year: 2026
- authors: Huang et al.
- venue: IEEE International Conference on Robotics and Automation (ICRA)

## 1. 핵심 요약
- human-robot collaboration(HRC)에서 visual/auditory/contextual 등 여러 perception module을 매 프레임 모두 실행하면 offline에서는 인지 품질이 좋아지지만, streaming 환경에서는 지연이 누적되어 시스템 성능이 크게 저하된다.
- 인간 뇌의 reticular activating system(RAS)을 모사해 task context·human intent에 따라 지각 입력의 우선순위를 매기는 선행 연구인 "relevance modeling" 개념을 계승, 이전 프레임 출력을 이용해 지금 필요한 perception module만 실시간으로 추정·활성화하는 경량 스케줄링 프레임워크를 제안한다.
- Perception Region Segmentation → Perception Reward Estimation → Perception Module Selector의 3단계 파이프라인으로 구성되며, 각 module의 활성화 여부를 information gain에서 계산 비용을 뺀 reward로 결정한다.
- Indoor Reading/Eating/Walking 3개 시나리오(30 FPS)에서 conventional parallel perception pipeline·oracle scheduling 대비 computational latency 최대 27.52% 감소, MMPose activation recall 72.73% 향상, keyframe accuracy 최대 98%를 보고한다.

## 2. 문서 목적
- 해결하려는 문제: HRC에서 여러 perception module을 매 프레임 전부 실행하는 방식은 offline에서는 인지 품질을 높이지만 streaming(실시간) 시나리오에서는 지연이 누적되어 시스템 성능이 크게 저하되고, 기존 perception pipeline은 정보 중복(information redundancy)과 연산 자원의 비효율적 배분 문제를 가진다.
- 기술적 목표: 미래 프레임에 접근할 수 없는 실시간 제약 하에서, 이전 프레임의 perception 출력과 현재 scene context만으로 각 perception module의 활성화 필요성을 실시간 추정하고 필요한 module만 선택적으로 실행하는 경량 스케줄링 방법을 제시하는 것.
- 다루는 범위: relevance modeling 개념의 계승, Perception Region Segmentation·Reward Estimation·Module Selector 3단계 파이프라인 설계, YOLO(object detection)·MMPose(pose estimation) 두 module에 대한 실증, conventional parallel perception pipeline 및 oracle scheduling 대비 latency·activation recall·keyframe accuracy 비교 평가.

## 3. 핵심 개념 상세
### Relevance Modeling (RAS 기반 지각 우선순위화)
- 원문 표현: "Inspired by the relevance modeling framework, which emulates the human reticular activating system (RAS) to prioritize perceptual inputs based on task context and human intent."
- 정의: 인간 뇌의 reticular activating system이 과제 맥락과 의도에 따라 지각 입력에 선택적으로 주의를 배분하는 방식을 모사해, task context와 human intent를 근거로 지각 입력의 처리 우선순위를 정하는 선행 연구의 프레임워크.
- 역할: 모든 감각·module 출력을 동등하게 처리하지 않고, 현재 과제·의도와 관련이 높은 입력에 우선순위를 두어 처리 자원을 배분하는 근거 개념으로 사용된다.

### Perception Region Segmentation
- 정의: 이전 프레임 데이터를 이용해 현재 scene을 background, object, human region으로 구분하고, frame differencing으로 motion 상태를 추정해 relevance state를 갱신하는 파이프라인의 첫 단계.
- 역할: 이후 reward 계산 단계에 앞서 scene을 의미 단위로 나눠, 어느 영역에서 변화가 발생했는지를 판별할 수 있는 입력을 제공한다.
- 원문 표현: 원문 확인 안 됨(단계의 기능은 논문 본문에서 확인했으나, 정확한 원문 문장 자체는 확인 안 됨).

### Perception Reward Estimation
- 원문 표현: "ρkj=ΦR(Sk,mj)−Cj" / "module mj is activated if and only if ρkj>0 or G1j[k]=1"에서 사용되는 reward 정의(수식으로 제시됨)
- 정의: 각 perception module mj에 대해 현재 프레임 상태 Sk가 주는 information gain에서 그 module을 실행하는 계산 비용 Cj를 뺀 reward ρkj를 계산하는 단계. object detection에서는 배경 차분 기반 scene 변화와 Kalman filter 예측 대비 bounding box의 entropy 감소를, pose estimation에서는 사람의 진입·이탈 감지와 bounding box에서 keypoint로 전환될 때의 entropy 감소를 reward에 반영한다.
- 역할: 각 module을 지금 실행하는 것이 실제로 얼마나 새로운 정보를 주는지를 정량화해, 다음 단계의 활성화 결정을 위한 근거 점수를 만든다.

### Perception Module Selector
- 원문 표현: "module mj is activated if and only if ρkj>0 or G1j[k]=1"
- 정의: 계산된 reward ρkj가 0보다 크거나, 사전에 정해진 활성화 지시자 G1j[k]가 1인 경우에만 해당 perception module을 활성화하는 최종 결정 단계.
- 역할: reward 계산 결과를 실제 module on/off 결정으로 변환해, 정보 이득이 없는 프레임에서는 module 실행을 건너뛰고 연산을 절약한다.

### Keyframe Accuracy
- 원문 표현: "The Keyframe Accuracy is defined as the percentage of important frames that are correctly identified for activation." / "keyframe selection often relies on access to the full video sequence, making it unsuitable for real-time systems where future frames are unavailable."
- 정의: 실제로 module 활성화가 필요한(정보 이득이 있는) "중요 프레임"을 얼마나 정확히 식별했는지를 나타내는 지표로, 전체 시퀀스에 접근 가능한 기존 offline keyframe selection과 달리 미래 프레임 없이 실시간으로 판단해야 한다는 점이 다르다.
- 역할: 스케줄링 결정의 정확도를 처리 지연과 분리해 평가함으로써, "얼마나 빠른가"뿐 아니라 "필요한 프레임을 얼마나 놓치지 않는가"를 별도로 검증하는 지표로 사용된다.

## 4. 구조 및 흐름
1. Perception Region Segmentation: 이전 프레임 정보를 이용해 현재 scene을 background/object/human region으로 나누고 frame differencing으로 motion 상태를 추정, relevance state를 갱신한다.
2. Perception Reward Estimation: 각 module(YOLO object detection, MMPose pose estimation)에 대해 정보 이득(scene 변화, entropy 감소 등)에서 계산 비용을 뺀 reward ρkj를 계산한다.
3. Perception Module Selector: ρkj>0이거나 사전 활성화 지시자가 설정된 module만 활성화하고 나머지는 건너뛴다.
4. 활성화된 module만 실제로 실행되어 해당 프레임의 perception 출력을 생성하고, 이 출력은 다음 프레임의 Region Segmentation·Reward Estimation 입력으로 다시 사용된다.
5. RTX 4090(추론)과 Intel i9(스케줄링)을 사용한 실험 환경에서 Indoor Reading/Eating/Walking 3개 시나리오(30 FPS)에 대해 conventional parallel perception pipeline, oracle scheduling과 latency·activation recall·keyframe accuracy를 비교 평가한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 매 프레임 모든 module을 실행하는 방식은 streaming 환경에서 성능을 저하시킨다 | "executing multiple perception modules on a frame-by-frame basis enhances perception quality in offline settings, it inevitably accumulates latency, leading to a substantial decline in system performance in streaming perception scenarios" |
| 이전 프레임 출력 기반 스케줄링이 연산 지연을 크게 줄인다 | conventional parallel perception pipeline 대비 computational latency 최대 27.52% 감소 |
| 스케줄링이 중요 module 활성화를 잘 포착한다 | MMPose activation recall 72.73% 향상, keyframe accuracy 최대 98% 달성 |
| reward 기반 활성화 결정(ρkj>0 또는 사전 지시자)이 실제 필요 여부를 잘 반영한다 | "module mj is activated if and only if ρkj>0 or G1j[k]=1" 기준으로 Region Segmentation→Reward Estimation→Module Selector 3단계 파이프라인을 실측 평가 |

## 6. 한계 및 부족한 점
- 저자들이 직접 명시: "Despite the observed improvement, the MMPose recall remains relatively low" 하며 그 원인을 "inherent inference latency"로 지목한다.
- YOLO recall 역시 "Minor decrease"가 관찰되었고, 이는 "inherent accuracy limitations of the perception modules"에 기인한다고 명시한다.
- 평가가 Indoor Reading/Eating/Walking 등 제한된 실내 시나리오와 YOLO·MMPose 2개 module 조합으로만 이루어져, 더 많은 module을 공유 연산 예산 아래 함께 스케줄링하는 경우는 다루지 않는다.
- 저자들은 향후 과제로 "developing adaptive methods across diverse scenarios and extending the framework to incorporate resource coupling constraints when scheduling larger sets of perception modules under shared computational budgets"를 명시한다.

## 7. 원문 기반 핵심 문장
> "While executing multiple perception modules on a frame-by-frame basis enhances perception quality in offline settings, it inevitably accumulates latency, leading to a substantial decline in system performance in streaming perception scenarios. ... we propose a novel lightweight perception scheduling framework that efficiently leverages output from previous frames to estimate and schedule necessary perception modules in real-time based on scene context."
