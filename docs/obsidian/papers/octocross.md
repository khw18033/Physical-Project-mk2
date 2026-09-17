# OctoCross: Workload-Aware Request Offloading Scheduling in Cross-Camera Collaboration

## 메타데이터
- categories: Graph 기반 Spatiotemporal Attention Encoder, Multi-step Predictive Offloading Scheduling, Iterative Transfer Projection, Node Churn 대응 온라인 마스킹
- domain: [[엣지 실행·자원]]
- source: Jinghan Cheng, Thanh-Tung Nguyen, Lucas Liebe, Yuheng Wu, Nhat-Quang Tau, Pablo Espinosa, Dongman Lee, "OctoCross: Workload-Aware Request Offloading Scheduling in Cross-Camera Collaboration," 23rd International Conference on Service-Oriented Computing (ICSOC 2025), Lecture Notes in Computer Science, vol. 16320, pp. 365-380, 2026.
- url: https://doi.org/10.1007/978-981-95-5012-8_27 (KAIST Pure 레코드: https://pure.kaist.ac.kr/en/publications/octocross-workload-aware-request-offloading-scheduling-incross-ca/)
- year: 2026 (ICSOC 2025 학회 발표, Shenzhen, China, 2025-12-01~04; 논문집(LNCS)은 2026년 출판)
- authors: Jinghan Cheng, Thanh-Tung Nguyen, Lucas Liebe, Yuheng Wu, Nhat-Quang Tau, Pablo Espinosa, Dongman Lee (KAIST)
- venue: 23rd International Conference on Service-Oriented Computing (ICSOC 2025), 정규 세션 논문(LNCS vol. 16320 수록, workshop 아님)

## 1. 핵심 요약
- 다중 카메라 비디오 분석 시스템에서 기존 오프로딩 기법이 공간(카메라/노드 간 관계)과 시간(워크로드 변화 추이) 동역학을 함께 모델링하지 못한다는 문제를 지적하며, 이를 동시에 학습해 실행 가능한 오프로딩 계획을 생성하는 OctoCross를 제안한다.
- 그래프 기반 multi-head attention 인코더로 각 카메라/노드의 과거 워크로드 이력과 네트워크 토폴로지를 함께 학습(joint spatiotemporal learning)하고, 예측된 미래 부하를 바탕으로 반복적(iterative) 오프로딩 매트릭스를 산출하는 예측형 스케줄링 루프를 사용한다.
- 최대 100개 노드 규모의 동적 토폴로지에서 baseline 대비 최대 5.8배의 처리량 향상과 3.2배의 지연 감소를 달성하면서 SLO 준수율을 유지했다고 보고한다.
- 저자들의 GitHub 저장소(`tungngreen/PipelineScheduler`)에 `OctoCross-ICSOC2025`라는 별도 브랜치로 상당히 완성도 높은 구현체(C++ 실행 프레임워크 + Python 기반 spatiotemporal 모델 학습/추론 코드)가 실제로 존재함을 확인했다.

## 2. 문서 목적
- 해결하려는 문제: 다중 카메라 협업(cross-camera collaboration) 비디오 분석 환경에서 각 노드(카메라/엣지 디바이스)의 워크로드가 시공간적으로 변동하는데, 기존 오프로딩 방법은 공간적 근접성/토폴로지와 시간적 부하 추이를 분리하거나 둘 중 하나만 고려해 실행 가능한 오프로딩 계획을 내지 못한다.
- 기술적 목표: 공간(노드 간 연결·거리)과 시간(과거 부하 이력) 정보를 하나의 신경망으로 공동 학습(jointly learn)해 미래 부하를 예측하고, 이 예측을 바탕으로 노드 간 요청 분배(오프로딩 매트릭스)를 실시간으로 생성하는 스케줄링 시스템을 구현하는 것.
- 다루는 범위: 그래프 기반 spatiotemporal 인코더 설계, 다단계(multi-step) 반복 오프로딩 스케줄링 루프, 노드 추가/제거(node churn)에 대응하는 온라인 마스킹과 부분 재학습(fine-tuning), 최대 100노드 규모 동적 토폴로지·실제 5G 대역폭 트레이스 기반 실증 평가.

## 3. 핵심 개념 상세

### Joint Spatiotemporal Learning (Graph 기반 Multi-head Attention 인코더)
- 원문 표현: "existing offloading methods lack the capability to jointly model spatial and temporal dynamics" 문제를 해결하기 위해 "OctoCross introduces a novel spatiotemporal model that jointly learns spatial and temporal dynamics to generate actionable offloading plans"라고 명시한다(KAIST Pure 게재 초록).
- 정의: 구현 코드(`libs/controller/Model/ST.py`)의 `SimpleSTBlock`은 각 노드의 시계열(초 단위로 집계한 프레임별 객체 수 등 부하 지표)에 대해 시간축 self-attention(`temporal_attn`)과 노드축 self-attention(`spatial_attn`)을 별도로 계산한 뒤, 두 결과를 학습 가능한 게이트(`gate`)로 융합하고 residual + LayerNorm + FFN을 거치는 블록이며, 이를 여러 층(`num_encoder_layers`) 쌓아 인코더를 구성한다. Positional encoding으로 시간 순서 정보를 주입한다.
- 역할: 노드별 과거 이력(`history_steps`, 기본 32스텝)을 인코딩해 향후 여러 스텝(`forecast_horizon`, 기본 8스텝)의 부하를 동시에 예측하는 `main_pred`와 스케줄링 전용 보조 예측치 `aux_pred`를 산출한다. 즉 "예측"과 "스케줄링에 실제 사용할 신호"를 분리해 산출하는 구조다.

### Predictive Scheduling Loop (Multi-step 반복 오프로딩)
- 원문 표현: README 및 초록에서 "Multi-step iterative offloading based on predicted workloads"라고 설명한다.
- 정의: 예측된 각 미래 스텝(`h`)마다 `compute_schedule()`을 호출해 오프로딩 매트릭스 `T_h`와 갱신된 노드별 부하 `final_load_h`를 계산하고, 이를 전체 forecast horizon에 대해 순차적으로 쌓아(`T_all`, `final_load_all`) 다단계 스케줄을 생성한다.
- 역할: 한 시점의 순간 부하가 아니라 예측된 미래 궤적 전체에 대해 오프로딩 계획을 미리 산출함으로써, 부하가 실제로 임계치를 넘기기 전에 선제적으로(proactively) 재분배 결정을 내릴 수 있게 한다. 저자들은 이를 "런타임 마스크가 영향이 적은 노드를 건너뛰어 연산 오버헤드를 줄인다(Runtime masks skip low-impact nodes to reduce compute overhead)"고 설명한다.

### 오프로딩 매트릭스 산출 메커니즘 (구현 세부, `compute_schedule`)
- 정의(코드 기반): 각 노드의 예측 부하와 임계치(threshold, 기본 10)를 비교해 잉여(sender, `available`)와 부족(receiver, `deficit`)을 계산하고, 노드 임베딩(학습 파라미터) + 그래프 차수 기반 구조 임베딩(`structural_embedding`) + 시간축 특징(`temporal_fc`)을 결합한 spatiotemporal 특징을 MLP(`ResidualBlock` 2개 + 선형층)에 통과시켜 노드 쌍(N×N) 점수(`base_scores`)를 얻는다.
- 허용 연결 마스크: 네트워크 토폴로지 파일(`bandwidth.cites`, 노드 간 거리/대역폭을 담은 3열 텍스트 — 인용 네트워크(citation network) 포맷을 차용)에서 각 노드의 최근접 2개 이웃만 연결 가능하다고 보는 `nodes_index_matrix`를 만들고, 여기에 sender/receiver 마스크를 곱해 실제 오프로딩이 허용되는 노드 쌍만 남긴다.
- 반복 프로젝션(`iterative_transfer_projection`): 점수를 softmax로 확률분포화한 뒤, 목적지의 부족량(deficit)과 출발지의 잉여량(available) 제약을 번갈아 가며 10회 반복 스케일링(row/column rescaling, Sinkhorn류 iterative proportional fitting과 유사)해 각 제약을 만족하는 연속값 전송량 행렬을 구하고 이를 올림(ceil)해 정수 전송량으로 이산화한다.
- 역할: 단순 임계치 기반 그리디 배정이 아니라, 학습된 spatiotemporal 특징으로 산출한 선호도 점수를 용량 제약을 만족하는 실행 가능한 전송 계획으로 투영(projection)하는 구조다. 학습 시에는 `discriminator_loss`(용량 초과 패널티 + 음수 용량 패널티 + RMS 항)로 이 투영 결과의 타당성을 평가하는 GAN 판별자 스타일의 손실을 함께 사용한다.

### Continuous Adaptation (Node Churn 대응 온라인 마스킹·부분 재학습)
- 원문 표현: README에서 "Online masking to handle node churn"과 "Targeted fine-tuning of only added/removed nodes (1000 epochs, ≤30 s convergence)"라고 설명한다.
- 정의: 저장소의 `ST_add.py`는 노드 수(N)가 바뀔 때 토폴로지 파일을 다시 읽어 `allowed_mask`를 재계산하고, 특정 시점(`OVERRIDE_SEC`)에 지정된 노드(`CONGEST_NODES`)의 모든 연결을 차단하는 방식으로 혼잡/노드 이탈 상황을 시뮬레이션하는 몽키패치된 `iterative_transfer_projection`을 제공한다.
- 역할: 전체 그래프를 처음부터 재학습하지 않고 변경된(추가/제거된) 노드에 대해서만 마스크를 갱신하고 국소적으로 재학습함으로써, 카메라 네트워크 토폴로지가 런타임 중 바뀌어도(노드 증설·이탈) 짧은 시간 안에 적응하도록 설계되었다.

## 4. 구조 및 흐름
1. Controller가 모든 디바이스(카메라/엣지 노드)로부터 워크로드 트레이스(초 단위 부하 지표)를 수집한다.
2. Spatiotemporal 인코더(Generator)가 각 노드의 과거 이력과 토폴로지(`bandwidth.cites` 기반 최근접 이웃 그래프)를 함께 인코딩해 향후 `forecast_horizon` 스텝의 부하(`main_pred`, `aux_pred`)를 예측한다.
3. 예측된 각 미래 스텝에 대해 `compute_schedule`이 학습된 특징으로 노드 쌍 선호도 점수를 산출하고, 허용 연결·용량 제약 하에서 반복 프로젝션으로 오프로딩 매트릭스(전송량 행렬)를 계산한다.
4. Controller가 생성된 오프로딩 매트릭스를 바탕으로 Device Agent에 커스텀 gRPC API로 태스크 재배치 명령(`ContainerLink`의 `data_portion`, `offloading_duration` 등)을 내리고, Device Agent는 컨테이너화된 추론 마이크로서비스(Receiver→Preprocessor→Batcher→Inferencer→Postprocessor→Sender)의 워크로드 분배를 실제로 조정한다.
5. 노드가 추가/제거되거나 네트워크 혼잡이 발생하면 온라인 마스킹으로 허용 연결 그래프를 갱신하고 해당 노드에 한해 모델을 짧게(최대 1000 epoch, 30초 이내라고 주장) 재학습해 스케줄링에 반영한다.
6. 운영 통계는 PostgreSQL 기반 Knowledge Base에 기록되어 다음 스케줄링 사이클과 성능 분석에 재사용된다(OCTOPINF와 동일한 Knowledge Base 구성 요소 공유).

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| OctoCross는 baseline 대비 최대 5.8배의 처리량 향상과 3.2배의 지연 감소를 달성한다 | KAIST Pure 게재 초록: "up to 5.8× higher throughput and 3.2× lower latency compared to baselines"; GitHub README에도 동일 수치("Boost throughput by up to 5.8×", "Reduce end‑to‑end latency by up to 3.2×")가 반복 명시되어 콜리그가 전달한 수치와 정확히 일치함을 확인했다 |
| OctoCross는 최대 100개 노드 규모의 동적 토폴로지에서도 높은 SLO 준수율을 유지한다 | README: "Maintain high SLO compliance in dynamic topologies of up to 100 nodes" |
| 공간·시간 동역학을 공동 학습하는 것이 기존 오프로딩 방법의 한계를 해결한다 | 초록: "existing offloading methods lack the capability to jointly model spatial and temporal dynamics"라는 문제 제기와 "a novel spatiotemporal model that jointly learns spatial and temporal dynamics to generate actionable offloading plans"라는 해결 주장 |
| 노드 추가/제거 시 전체 재학습 없이 빠르게 적응할 수 있다 | README: "Targeted fine-tuning of only added/removed nodes (1000 epochs, ≤30 s convergence)"; 코드 저장소의 `ST_add.py`가 토폴로지 변경 시 마스크 재계산과 국소 재학습 로직을 실제로 구현하고 있음을 확인했다 |
| MTMMC(Campus)와 AI City Challenge 2022(다중 차량 추적) 두 실제 데이터셋으로 평가했다 | README의 "Preparing Data" 절이 두 데이터셋을 명시하고, 저장소에 `jsons/SToffloading_aicity.json`, `Data_analysis/gt_campus.csv`, `Data_analysis/AIcity.csv` 등 두 시나리오용 설정·정답 파일이 실제로 존재함을 확인했다 |

## 6. 한계 및 부족한 점
- ICSOC 2025 논문 원문(Springer LNCS, DOI 10.1007/978-981-95-5012-8_27)은 유료 벽(paywall) 뒤에 있어 본문 전체를 직접 확인하지 못했다. 이 문서의 메커니즘 서술은 (1) KAIST Pure에 게재된 공식 초록, (2) 저자들이 직접 관리하는 GitHub 저장소의 README와 실제 소스 코드(`ST.py`, `ST_add.py`, `ST_train.py`)에 근거했으며, 논문 본문의 수식·실험 설계 세부(하이퍼파라미터 선정 근거, ablation, 통계적 유의성 등)는 검증하지 못했다. arXiv 프리프린트도 검색되지 않았다.
- 5.8배/3.2배라는 수치가 "어떤 baseline 대비"인지(예: 정적 라운드로빈, 그리디 임계치 기반, 아니면 OCTOPINF 자체 등)는 초록과 README에 명시되어 있지 않아 확인하지 못했다.
- 코드 상 `iterative_transfer_projection`의 반복 횟수(10회 고정)나 임계치(threshold=10)가 실험 전반에 고정된 하이퍼파라미터인지, 데이터셋별로 재조정되는지는 README에 명확히 기술되어 있지 않다.
- `ST_add.py`의 혼잡 시뮬레이션은 특정 시점(`OVERRIDE_SEC`)과 특정 노드(`CONGEST_NODES`)를 하드코딩한 실험용 몽키패치 스크립트로 보이며, 이것이 실제 평가에 사용된 정식 메커니즘인지 별도 데모/디버깅 코드인지는 코드만으로는 완전히 판별하기 어렵다.
- Docker 이미지 배포처(`hub.docker.com/r/anonymoussub/octocross`)의 계정명이 "anonymoussub"로 남아 있어, 리뷰 익명성을 위해 사용했던 자료를 게재 후 완전히 정리하지 않은 상태로 보인다 — 저장소가 여전히 활발히 정리 중임을 시사한다.

## 7. 원문 기반 핵심 문장
> "OctoCross introduces a novel spatiotemporal model that jointly learns spatial and temporal dynamics to generate actionable offloading plans" ... 실험 결과 "up to 5.8× higher throughput and 3.2× lower latency compared to baselines"를 달성했다.
(출처: KAIST Pure 게재 초록, https://pure.kaist.ac.kr/en/publications/octocross-workload-aware-request-offloading-scheduling-incross-ca/)

> "OctoCross is a real‑time video analytics scheduling system for distributed camera networks. It learns and predicts fine‑grained spatiotemporal workload dynamics and proactively generates efficient task‑offloading strategies to: Boost throughput by up to 5.8×, Reduce end‑to‑end latency by up to 3.2×, Maintain high SLO compliance in dynamic topologies of up to 100 nodes."
(출처: GitHub `tungngreen/PipelineScheduler`, `OctoCross-ICSOC2025` 브랜치 README)

## 8. PipelineScheduler 저장소 내 구현 위치 및 OCTOPINF와의 관계 (부가 조사)
- **구현 위치 확인**: `https://github.com/tungngreen/PipelineScheduler` 저장소의 브랜치 목록에 `OctoCross-ICSOC2025`라는 전용 브랜치가 실제로 존재함을 GitHub API로 직접 확인했다(다른 브랜치로 `OctopInf-PERCOM2025`, `master`, `jetson-master`, `server-master`, `octopus`, `CHEIS-SEC2026`도 함께 존재). 즉 콜리그가 주장한 "OctoCross 브랜치/디렉터리가 존재한다"는 내용은 정확했고, main(=master) 브랜치가 아니라 별도 브랜치에 있다는 점까지 정확히 일치했다.
- **완성도**: 이 브랜치는 단순 스텁이 아니라 (a) C++로 작성된 전체 실행 프레임워크(Controller, Device Agent, Container Agent, 마이크로서비스 파이프라인, gRPC/Protobuf 통신, TensorRT 추론 엔진, PostgreSQL Knowledge Base 연동)와 (b) Python으로 작성된 spatiotemporal 예측·스케줄링 모델 학습/추론 코드(`libs/controller/Model/ST.py`, `ST_add.py`, `ST_train.py`, `client.py`, `server.py`), (c) MTMMC(Campus)·AI City Challenge 두 데이터셋용 설정 파일과 정답 데이터, (d) Docker 빌드 스크립트와 사전학습 모델 가중치 다운로드 링크(Google Drive)까지 갖춘, 논문 실험을 실제로 재현할 수 있는 수준의 구현으로 판단된다.
- **OCTOPINF와의 관계**: 두 논문은 동일 연구실(Dongman Lee, KAIST)의 같은 `PipelineScheduler` 코드베이스 계열이며 저자진도 상당 부분 겹친다(Thanh-Tung Nguyen, Lucas Liebe, Yuheng Wu, Nhat-Quang Tau, Jinghan Cheng이 공통, OctoCross에는 Pablo Espinosa가 추가). 다만 관심사와 스케줄링 대상 축이 다르다.
  - **OCTOPINF (PerCom 2025)**: 하나의 EVA 파이프라인 안에서 "모델별 배치 크기·실행 위치(엣지/서버) 결정(Cwd)"과 "단일/소수 GPU 위의 여러 모델 실행을 시공간적으로 co-location 스케줄링(Coral)"에 집중한다. 즉 초점은 **노드 내부(intra-node) GPU 자원 co-location 최적화 + 엣지-서버 2단 워크로드 분산**이며, 브랜치의 컨트롤러도 C++로 작성된 `scheduling-ppp/dis/jlf/rim`(자체 알고리즘 및 Distream/JLF/Rim 등 baseline 비교 구현)로 구성되어 있다.
  - **OctoCross (ICSOC 2025)**: 카메라/노드가 다수(최대 100개) 존재하는 네트워크 전체에 걸친 **크로스 카메라(inter-node) 요청 오프로딩 라우팅**에 집중한다. 그래프 기반 spatiotemporal attention으로 각 노드의 미래 부하를 예측하고, 네트워크 토폴로지(대역폭/거리) 제약 하에서 어떤 노드가 어떤 노드로 얼마만큼의 요청을 넘겨야 하는지(전송 매트릭스)를 산출하는 것이 핵심이며, 별도의 Python 기반 그래프 어텐션 모델(`ST.py`)이 이 역할을 담당한다.
  - 요약하면 두 논문은 상호 배타적이라기보다 **스케줄링 계층이 다르다**: OCTOPINF는 "한 노드/파이프라인 안에서 GPU를 어떻게 나눠 쓸지"를, OctoCross는 "여러 카메라/노드 사이에서 어떤 요청을 어디로 보낼지"를 다룬다. 두 시스템 모두 같은 Controller-DeviceAgent-Container 3단 구조와 Knowledge Base(PostgreSQL)를 공유하는 것으로 보이나, 두 브랜치가 독립적으로 유지되고 있어 두 스케줄링 로직이 실제 단일 실행에서 동시에 결합되어 사용되는지(즉 계층적으로 합쳐진 통합 배포가 존재하는지)는 이번 조사 범위에서 확인하지 못했다.
