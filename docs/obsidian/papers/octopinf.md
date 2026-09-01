# OCTOPINF: Workload-Aware Inference Serving for Edge Video Analytics

## 메타데이터
- categories: [[Cross-Device Workload Distributor]], [[Adaptive Batching]], [[Co-location Inference Spatiotemporal Scheduler]], [[Runtime Horizontal AutoScaler]]
- domain: [[Edge Video Analytics]], [[Edge Computing]]
- source: Thanh-Tung Nguyen, Lucas Liebe, Nhat-Quang Tau, Yuheng Wu, Jinghan Cheng, Dongman Lee, "OCTOPINF: Workload-Aware Inference Serving for Edge Video Analytics," IEEE International Conference on Pervasive Computing and Communications (PerCom), 2025.
- url: https://doi.org/10.1109/PerCom64205.2025.00032
- year: 2025
- authors: Thanh-Tung Nguyen et al.
- venue: IEEE International Conference on Pervasive Computing and Communications (PerCom) 2025

## 1. 핵심 요약
- Edge Video Analytics(EVA) 파이프라인의 동적 워크로드, 네트워크 불안정성, GPU 자원 경합 문제를 해결하기 위해 OCTOPINF라는 자원 효율적이고 워크로드 인식형(workload-aware) 추론 서빙 시스템을 제안한다.
- fine-grained resource allocation, adaptive batching, 엣지-서버 간 workload balancing을 결합하고, GPU 상의 추론 태스크 co-location을 최적화하는 spatiotemporal scheduling 알고리즘을 추가로 제안한다.
- 실제 테스트베드(RTX 3090 서버 4대, Jetson AGX/Xavier NX/Orin Nano 등 엣지 디바이스 9대)에서 실험한 결과 baseline 대비 최대 10배의 유효 처리량(effective throughput) 향상과 향상된 강건성(robustness)을 보였다.

## 2. 문서 목적
- 해결하려는 문제: EVA 파이프라인은 엄격한 지연 요구사항 하에서 효율적인 추론 서빙을 필요로 하지만, 워크로드 변동성과 네트워크 불안정성 등 동적인 엣지 환경으로 인해 이를 만족하기 어렵고, 동시에 엣지의 GPU 등 자원 제약으로 인한 심각한 자원 경합(resource contention) 문제에 직면한다.
- 기술적 목표: 동적 엣지 환경에서도 SLO(service-level objectives) 준수를 보장하면서 자원 효율적으로 실시간 추론을 서빙할 수 있는 시스템을 구현하는 것.
- 다루는 범위: DNN 기반 EVA 파이프라인의 배치 크기 결정, 엣지-서버 간 워크로드 분산, GPU 상의 모델 co-location 스케줄링, 런타임 오토스케일링을 포함하는 end-to-end 추론 서빙 시스템 설계와 실제 테스트베드 기반 평가.

## 3. 핵심 개념 상세
### Cross-Device Workload Distributor
- 원문 표현: "temporally multiplexing model executions mitigates co-location interference, improving resource efficiency while ensuring compliance with SLO and throughput demands"에서 다뤄지는 워크로드 분산 인사이트와 연결되는 구성요소로, Controller 내 Cwd(Cross-Device Workload Distributor) 모듈로 명시됨.
- 정의: 파이프라인의 각 모델에 대해 배치 크기, 실행 장치(엣지/서버), 인스턴스 수를 결정하는 탐욕(greedy) 알고리즘 기반 모듈. burstiness(워크로드 변동성), IO ratio(입출력 크기 비율), 파이프라인 분할점 최소화라는 세 가지 인사이트에 기반한다.
- 역할: 버스티한 워크로드를 가진 모델에 더 큰 배치 크기를 할당해 대기 시간을 줄이고, 네트워크 트래픽 병목을 최소화하도록 모델 실행 위치를 DFS 기반의 ToEdge() 함수로 엣지 장치 쪽으로 점진적으로 이동시켜 fine-grained resource allocation과 엣지-서버 workload balancing을 수행한다.

### Adaptive Batching
- 원문 표현: "OCTOPINF tackles the unique challenges of dynamic edge environments through fine-grained resource allocation, adaptive batching, and workload balancing between edge devices and servers."
- 정의: 모델별 워크로드 특성(burstiness)에 따라 배치 크기를 동적으로 탐색하고, SLO 위반이 발생하면 롤백하는 방식으로 배치 크기를 조정하는 기법.
- 역할: 처리량을 극대화하면서도 지연 요구사항(SLO)을 만족하도록 배치 크기를 실시간으로 조정하여, 정적 배치 크기를 사용하는 기존 시스템(Distream, Rim 등)이 대응하지 못하는 동적 워크로드 변화에 대응한다.

### Co-location Inference Spatiotemporal Scheduler
- 원문 표현: "we propose a spatiotemporal scheduling algorithm that optimizes the co-location of inference tasks on GPUs, improving performance and ensuring service-level objectives (SLOs) compliance."
- 정의: Controller 내 Coral(Co-location Inference Spatiotemporal Scheduler) 모듈로, GPU의 추론 용량을 여러 스트림(Inference Stream)으로 분할하고 각 모델 실행을 시간·공간 축에 Best-Fit 방식으로 배치하는 스케줄링 알고리즘(Algorithm 2).
- 역할: 시간적 가용성(포션이 모델 실행 구간을 완전히 포함하는지), 공간적 충분성(메모리·GPU 활용률 제한 내인지), 의무주기(duty cycle) 충돌 여부라는 세 조건을 검증해 GPU 상의 모델 co-location으로 인한 성능 저하(co-location interference)를 완화하고 메모리 사용을 시간적으로 공유해 절감한다.

### Runtime Horizontal AutoScaler
- 원문 표현: 논문 구조 설명에서 Controller의 세 번째 구성요소로 제시되는 런타임 오토스케일러.
- 정의: 런타임 중 워크로드 급증을 감지해 모델 인스턴스를 자동으로 복제하고, 수요가 감소하면 인스턴스를 제거하는 수평적(horizontal) 오토스케일링 모듈.
- 역할: Cwd와 Coral이 수행한 초기 배치·스케줄링 결정을 런타임 동안 지속적으로 보완해, 워크로드 변동에 따라 시스템이 동적으로 확장·축소될 수 있도록 한다.

## 4. 구조 및 흐름
1. 파이프라인이 생성되면 초기 통계를 수집한다.
2. Controller의 Cwd가 실행되어 각 모델의 배치 크기, 실행 장치(엣지/서버), 인스턴스 수를 결정한다.
3. Controller의 Coral이 실행되어 GPU 상의 모델들에 대한 시간-공간(spatiotemporal) 스케줄을 산정한다.
4. 결정된 배치·스케줄이 각 디바이스의 Device Agent(Docker + TensorRT 기반 컨테이너)에 배포되고 모니터링된다.
5. 런타임 중 Runtime Horizontal AutoScaler가 워크로드 변화를 감지해 인스턴스를 동적으로 확장·축소하며, 관련 메트릭은 PostgreSQL 기반 Knowledge Base에 저장되어 다음 스케줄링 사이클에 활용된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| OCTOPINF는 baseline 대비 최대 10배의 유효 처리량 향상을 달성한다 | 실제 테스트베드(RTX 3090 서버 4대, Jetson AGX/Xavier NX/Orin Nano 엣지 디바이스 9대, 공개 영상 스트림 9개·13시간·15fps·720p) 실험에서 확인됨 |
| OCTOPINF는 기존 시스템보다 SLO 준수율이 높다 | Distream과 Rim은 20~30%의 요청에서 SLO를 위반한 반면 OCTOPINF는 위반이 0%로 나타남 |
| Coral의 시간적 다중화(temporal multiplexing)는 co-location interference를 완화하고 메모리 사용을 줄인다 | "temporally multiplexing model executions mitigates co-location interference, improving resource efficiency while ensuring compliance with SLO and throughput demands"라는 원문 서술과 함께, 기존 대비 메모리 사용이 현저히 감소했다는 평가 결과로 뒷받침됨 |
| 엄격한 SLO 조건에서도 OCTOPINF는 baseline 대비 우수한 성능을 유지한다 | SLO를 100ms 낮춘 시나리오에서 Rim 대비 10배의 처리량을 보였고, "OctopInf maintains its performance and continues to outperform the baselines, which experience significant performance degradation"이라는 서술로 뒷받침됨 |

## 6. 한계 및 부족한 점
- Co-location interference를 완전히 정밀하게 예측하지는 못한다. 모델별 메모리·GPU 활용률의 피크 시점이 서로 어긋날 경우 최적 자원 활용도에 도달하지 못할 수 있다.
- 스케줄링 알고리즘의 복잡도를 O(D·M·BZ + M·PT) 수준으로 낮췄음에도, 실시간 환경에서 완전한 최적해를 구하는 데는 여전히 제약이 있다.
- Future work로 저사양 디바이스(Raspberry Pi 등, ONNX/TensorFlow 기반) 대상 추가 검증, 시계열 성능 데이터를 이용한 co-located 모델 성능 예측 모델 구축, Meta Learning/Test-time Adaptation을 통한 신규 아키텍처 적응, 강화학습 기반 컨테이너별 로컬 적응(배치 크기·요청 우선순위 조정)이 언급되어 현재 시스템이 이 부분들을 아직 다루지 않음을 시사한다.

## 7. 원문 기반 핵심 문장
> OCTOPINF tackles the unique challenges of dynamic edge environments through fine-grained resource allocation, adaptive batching, and workload balancing between edge devices and servers. Furthermore, we propose a spatiotemporal scheduling algorithm that optimizes the co-location of inference tasks on GPUs, improving performance and ensuring service-level objectives (SLOs) compliance. Extensive evaluations on a real-world testbed demonstrate the effectiveness of our approach.
