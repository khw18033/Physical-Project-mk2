# Ekya: Continuous Learning of Video Analytics Models on Edge Compute Servers

## 메타데이터
- categories: [[Micro-Profiler]], [[Thief Scheduler]], [[Continuous Learning]], [[Data Drift]]
- domain: [[Edge Computing]], [[Video Analytics]]
- source: Bhardwaj, R., Xia, Z., Ananthanarayanan, G., Jiang, J., Shu, Y., Karianakis, N., Hsieh, K., Bahl, P., Stoica, I., "Ekya: Continuous Learning of Video Analytics Models on Edge Compute Servers", USENIX NSDI, 2022, pp. 119-135
- url: https://www.usenix.org/conference/nsdi22/presentation/bhardwaj
- year: 2022
- authors: Bhardwaj et al.
- venue: USENIX NSDI 2022

## 1. 핵심 요약
- 엣지 컴퓨트 서버에 배포된 압축 모델은 실시간 영상 데이터가 학습 데이터와 달라지는 data drift를 겪으며, continuous learning은 새 데이터로 모델을 주기적으로 재학습해 이를 처리한다.
- Ekya는 엣지 서버에서 inference와 retraining 작업을 동시에 지원할 때 발생하는, 재학습 모델의 정확도와 추론 정확도 사이의 근본적인 tradeoff를 다루는 시스템이다.
- Ekya는 이 tradeoff를 여러 모델에 걸쳐 균형 있게 조정하며, 재학습이 가장 필요한 모델을 식별하기 위해 micro-profiler를 사용한다.
- baseline 스케줄러 대비 Ekya의 정확도 향상은 29% 더 높고, baseline이 Ekya와 동일한 정확도를 내려면 4배 더 많은 GPU 자원이 필요하다.

## 2. 문서 목적
- 해결하려는 문제: 엣지 서버에 배포된 압축 딥러닝 모델이 실시간 비디오 데이터의 data drift로 인해 정확도가 저하되는 문제, 그리고 제한된 자원의 엣지 서버에서 inference와 retraining 작업을 동시에 지원해야 하는 문제
- 기술적 목표: 여러 비디오 스트림에 걸쳐 retraining 자원 배분과 재학습 configuration 선택을 동시에 최적화해 retraining window 동안의 inference accuracy를 최대화하는 스케줄링 솔루션 제공
- 다루는 범위: 단일 엣지 컴퓨트 서버 상에서 다중 비디오 스트림에 대한 continuous learning 스케줄링, micro-profiling 기반 재학습 필요성 추정, Thief Scheduler를 통한 GPU 자원 재분배

## 3. 핵심 개념 상세
### Micro-Profiler
- 원문 표현: "retrains only a few select configurations on a fraction of the data", "100× more efficient than exhaustive profiling while predicting accuracies with an error of 5.8%"
- 정의: retraining configuration들을 데이터의 일부와 적은 epoch 수로 짧게 실행한 뒤 curve fitting으로 최종 정확도를 추정하는 저비용 프로파일링 메커니즘
- 역할: 모든 configuration을 전체 데이터로 학습해보지 않고도 어떤 모델이 재학습으로 가장 큰 이득을 볼지 식별해 Thief Scheduler의 자원 배분 결정에 필요한 정보를 제공

### Thief Scheduler
- 원문 표현: "steals small resource chunks from a selected job and reallocates them to a more promising job", "decouples resource allocation and configuration selection"
- 정의: 각 retraining window 시작 시점과 job 완료 시점마다 실행되며, 비디오 스트림 전체에 공정한 GPU 배분에서 시작해 victim job으로부터 작은 자원 단위 Δ를 훔쳐 더 유망한 thief job에 재배분하고, 정확도가 개선되는 경우에만 배분을 유지하는 반복적 휴리스틱 스케줄러
- 역할: 자원 배분과 configuration 선택을 분리해 다중 비디오 스트림에 대한 스케줄링 문제를 다루기 쉬운 형태로 만듦

### Continuous Learning
- 원문 표현: "Continuous learning handles data drift by periodically retraining the models on new data."
- 정의: 배포된 모델을 새로 수집된 데이터로 주기적으로 재학습시켜 정확도를 유지하는 방식
- 역할: data drift로 인한 정확도 저하 문제에 대한 Ekya의 기본 대응 전략이며, Ekya는 이 재학습 과정에서 발생하는 자원 경합을 스케줄링으로 해결

### Data Drift
- 원문 표현: "Compressed models that are deployed on the edge servers for inference suffer from data drift where the live video data diverges from the training data."
- 정의: 엣지 서버에 배포된 압축 모델의 학습 데이터와 실제 실시간 비디오 데이터 사이의 분포 괴리 현상
- 역할: Ekya가 해결하고자 하는 근본 문제로, retraining의 필요성과 시점을 결정하는 트리거 역할을 함

## 4. 구조 및 흐름
1. 엣지 서버에 배포된 압축 모델이 실시간 비디오 스트림에 대해 inference를 수행하며, 시간이 지남에 따라 data drift로 인해 정확도가 저하됨.
2. 각 retraining window 시작 시 Micro-Profiler가 후보 retraining configuration들을 소량 데이터·적은 epoch로 짧게 실행하여 최종 정확도를 추정함.
3. Thief Scheduler가 모든 비디오 스트림에 공정한 GPU 배분으로 시작한 뒤, victim job으로부터 작은 자원 단위(Δ)를 반복적으로 훔쳐 더 유망한 thief job에 재배분하면서 window 전체의 inference accuracy를 최대화하는 configuration을 선택함.
4. 재배분 후 정확도가 개선되면 해당 배분을 유지하고, 개선되지 않으면 반복을 중단하고 최종 자원 배분 상태를 반환하여 inference와 retraining 작업에 GPU 자원을 실제로 적용함.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| Ekya는 baseline(uniform) 스케줄러보다 높은 정확도를 낸다 | 단일 GPU 환경에서 baseline 대비 29% 더 높은 정확도, GPU 2개 환경에서 23% 더 높은 정확도를 보고 |
| Ekya는 baseline 대비 GPU 자원 사용을 크게 절감한다 | baseline이 Ekya와 동일한 정확도를 달성하려면 4배 더 많은 GPU 자원이 필요함을 보고 |
| Micro-Profiler는 전수 프로파일링 대비 효율적이면서도 정확한 추정을 제공한다 | exhaustive 프로파일링 대비 100배 효율적이며 정확도 예측 median error 5.8%를 보고 |
| Thief Scheduler는 다중 스트림 환경에서도 실용적인 시간 내 동작한다 | 8개 GPU에 걸친 10개 스트림에 대해 9.4초 만에 스케줄링 결정을 완료함을 보고 |

## 6. 한계 및 부족한 점
- 현재 시스템은 단일 엣지 디바이스 환경을 대상으로 하며, 이기종 하드웨어를 가진 계층적 엣지 아키텍처로의 확장은 다루지 않음.
- 분산 엣지 클러스터로 확장할 경우 privacy 문제가 더 복잡해진다는 점을 저자들이 지적함.
- vision 워크로드를 넘어 다른 영역으로 일반화하려면 resource-accuracy 함수가 "strictly increasing"이어야 한다는 전제 조건이 필요함.

## 7. 원문 기반 핵심 문장
> Video analytics applications use edge compute servers for processing videos. Compressed models that are deployed on the edge servers for inference suffer from data drift where the live video data diverges from the training data. Continuous learning handles data drift by periodically retraining the models on new data. Our work addresses the challenge of jointly supporting inference and retraining tasks on edge servers, which requires navigating the fundamental tradeoff between the retrained model's accuracy and the inference accuracy. Our solution Ekya balances this tradeoff across multiple models and uses a micro-profiler to identify the models most in need of retraining. Ekya's accuracy gain compared to a baseline scheduler is 29% higher, and the baseline requires 4× more GPU resources to achieve the same accuracy as Ekya.
