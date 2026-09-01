# 외부 연구 baseline 재현 및 프레임워크 통합 구현 계획

작성·재검토: 2026-09-01

대상: `docs/obsidian/papers/`의 논문 14편, 각 논문의 원문·공식 저장소,
[최신 요구사항 정의서의 `진나영` 탭](https://docs.google.com/spreadsheets/d/1-A7Xtjn7sbbvbnfJKoe8nGxbsPDSLqVlyFdec8iYUa0/edit?gid=1974586969#gid=1974586969)

상태: **계획 확정 전 초안**. 이 문서는 구현·실험 완료 보고서가 아니다.

## 1. 목적과 완료의 정의

목표는 논문의 일부 아이디어를 비슷하게 구현하는 것이 아니라, 먼저 공식 구현을 독립
환경에서 재현하고 그 결과를 `perception-framework`의 교체 가능한 baseline으로
연결하는 것이다. 다음 네 상태를 구분한다.

1. **출처 확인**: 원문, 공식 코드, 라이선스, 데이터, checkpoint, 실행법을 확인한다.
2. **원본 재현**: 고정 commit과 공식 설정으로 최소 1개 대표 결과를 생성한다.
3. **어댑터 통합**: 원본 코드를 수정하지 않고 공통 입력·출력 계약으로 감싼다.
4. **비교 검증**: 동일 manifest와 평가 코드로 baseline 간 결과를 비교한다.

단위 테스트 통과만으로 논문 재현을 완료 처리하지 않는다. 논문 수치와 다르더라도 환경
차이와 편차를 설명하고 원시 결과를 보존하면 재현 결과로 인정할 수 있다. 수치만 기록하고
실행 코드·manifest가 없으면 검증 완료가 아니다.

현재 승인 대상은 대규모 학습·전체 benchmark 재현이 아니라 소규모 공통 데이터에서의
**기능 검증**이다. 구체 범위는 `master-experiment-approval.md`를 따른다. 아래의 논문별
전체 재현 단계는 장기 확장 계획이며, 현재 기능 검증 결과와 혼동하지 않는다.

## 2. 최신 요구사항 연결

최신 기준은 로컬 `CLAUDE.md`의 과거 51개 요구사항이 아니라 Google Sheets
`진나영` 탭이다. 이 탭에는 AI-L-01~AI-L-08 `학습·MLOps` 요구사항이 추가되어
지속학습의 전체 흐름을 명시한다. 구현 전에 로컬 요구사항 문서와 traceability도 이
최신 원문에 맞춰 동기화해야 한다.

| 요구사항 | 구현 계획에서의 책임 | 대응 연구 |
|---|---|---|
| AI-L-01 학습 필요성·후보 데이터 선별 | 미확인 객체, 반복 오류, 환경 변화, 성능 저하를 이유와 원본 참조가 있는 후보로 표시 | H2ST, DGS task grouping |
| AI-L-02 학습 후보 격리·품질 관리 | 자동 후보와 검증된 학습 데이터를 분리하고 pseudo-label을 자동 정답 승격하지 않음 | RGR-IOD pseudo-label filtering |
| AI-L-03 사용자 확인·의미 정보 반영 | AI 후보와 사용자 확인 정보를 분리하고 객체·관측·후보에 연결 | FOMO, OW-OVD, OWOBJ 결과의 확인 흐름 |
| AI-L-04 학습 실행·전략 분리 | 학습 대상·알고리즘·실행 위치를 교체 가능한 Learning Provider로 구현 | DGS, RGR-IOD, Ekya |
| AI-L-05 학습 결과 검증·기존 지식 보존 | 신규 성능, forgetting, 지연·자원·호환성과 실패 조건을 기존 정상 버전과 비교 | DGS, RGR-IOD, H2ST |
| AI-L-06 관리자 판단 정보·적용 승인 요청 | lineage와 성능·위험·적용 범위를 구조화하고 검증 실패 후보는 승인 요청 금지 | 모든 학습 결과 |
| AI-L-07 단계적 적용·운영 검증·롤백 | shadow/canary 등 provider를 통한 제한 적용, 승격, last-known-good 복구 | Ekya와 기존 model deployment lifecycle |
| AI-L-08 학습·적용 계보 추적 | 사건→객체·관측→후보·데이터→학습→검증·승인→적용을 버전·참조로 연결 | 모든 지속학습 baseline |

함께 적용되는 기존 범위는 AI-B-01/B-04/B-05/B-06/B-07/B-08, AI-E-01,
AI-S-01/S-02/S-04/S-05/S-06/S-08, AI-O-01/O-02/O-03 및 AI-C-01/C-03/C-19다.
특히 AI-C-19는 학습 후보 선정·학습·검증은 AI 책임이지만 최종 가용성, 물리 제어,
승인 기록과 UI는 각각 백엔드·하드웨어·가시화 경계를 따라야 한다고 규정한다.

알고리즘·threshold·보존 기간처럼 요구사항이 의도적으로 고정하지 않은 값은 임의로
요구사항을 추가하는 대신, 실험으로 비교할 정책 또는 파트 간 상세 설계 항목으로 남긴다.

## 3. 직접 확인한 공식 출처와 재현성

| Baseline | 원문 | 공식 구현 | 현재 판정 |
|---|---|---|---|
| ApproxDet | [SenSys 2020](https://doi.org/10.1145/3384419.3431159) | [StarsThu2016/ApproxDet](https://github.com/StarsThu2016/ApproxDet) | TX2, TF-GPU 1.14, NumPy≤1.16.4 및 장치별 재프로파일링 필요 |
| DACC | [Computer Networks 2026](https://doi.org/10.1016/j.comnet.2026.112130) | [twerppan/DEOF](https://github.com/twerppan/DEOF) | 공개 코드는 선행 DEOF 기반이므로 논문-코드 대응 감사 필요 |
| nn-Meter | [MobiSys 2021](https://doi.org/10.1145/3458864.3467882) | [microsoft/nn-Meter](https://github.com/microsoft/nn-Meter) | archive 상태. 구형 프레임워크를 별도 환경에 고정 |
| FOMO | [arXiv 2312.05745](https://arxiv.org/abs/2312.05745) | [orrzohar/FOMO](https://github.com/orrzohar/FOMO) | RWD benchmark·공식 script 기준 재현 |
| OW-OVD | [CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Xi_OW-OVD_Unified_Open_World_and_Open_Vocabulary_Object_Detection_CVPR_2025_paper.html) | [xxyzll/OW_OVD](https://github.com/xxyzll/OW_OVD) | YOLO-World 기반 학습·평가 환경 필요 |
| OWOBJ | [CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Open-World_Objectness_Modeling_Unifies_Novel_Object_Detection_CVPR_2025_paper.html) | [AI4Math-ShanZhang/OWOBJ](https://github.com/AI4Math-ShanZhang/OWOBJ) | checkpoint/config/script 공개 상태 재확인 필요 |
| ByteTrack | [ECCV 2022](https://arxiv.org/abs/2110.06864) | [FoundationVision/ByteTrack](https://github.com/FoundationVision/ByteTrack) | 공식 YOLOX·MOT 평가 가능. 현재 구현은 축약형 |
| OVTR | [ICLR 2025](https://arxiv.org/abs/2503.10616) | [jinyanglii/OVTR](https://github.com/jinyanglii/OVTR) | 코드·checkpoint·OVTR-Lite 제공, TAO 준비 필요 |
| DGS | [CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Boosting_Vision-Language_Models_Towards_Cross-Domain_Incremental_Object_Detection_CVPR_2026_paper.html) | [Never-wx/dgs](https://github.com/Never-wx/dgs) | MMDetection 3.3/GroundingDINO 별도 환경 필요 |
| H2ST | [CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Liu_H2ST_Hierarchical_Two-Sample_Tests_for_Continual_Out-of-Distribution_Detection_CVPR_2025_paper.html) | [YuhangLiuu/H2ST](https://github.com/YuhangLiuu/H2ST) | 공식 continual/TIL 분할과 통계 검정 보존 |
| RGR-IOD | [CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Revisiting_Generative_Replay_for_Class_Incremental_Object_Detection_CVPR_2025_paper.html) | [qiangzai-lv/RGR-IOD](https://github.com/qiangzai-lv/RGR-IOD) | 생성 replay·pseudo-label·SCS까지 포함해야 재현 |
| Ekya | [NSDI 2022](https://www.usenix.org/conference/nsdi22/presentation/bhardwaj) | [edge-video-services/ekya](https://github.com/edge-video-services/ekya) | Ray 기반 시스템이며 단일 함수로 축약 불가 |
| OCTOPINF | [PerCom 2025](https://doi.org/10.1109/PerCom64205.2025.00032) | [tungngreen/PipelineScheduler](https://github.com/tungngreen/PipelineScheduler) | C++/Docker/gRPC/PostgreSQL/TensorRT·복수 장치 필요 |
| E4 | [AAAI 2025](https://arxiv.org/abs/2503.04865) | 확인된 공식 저장소 없음 | 원문 명세 재구현은 가능하나 ‘공식 재현’ 표기 금지 |

각 저장소는 다운로드 전에 commit SHA, 라이선스, submodule/LFS, 외부 다운로드 URL과
예상 용량을 `source-lock.json`에 기록한다. 출처가 바뀌면 기존 결과와 섞지 않는다.

## 4. 디렉터리와 공통 산출물

```text
experiments/external/
  source-lock.json                 # URL, commit, license, paper version
  manifests/<run-id>.json          # 데이터 목록·hash·split·seed
  protocols/<baseline>.md          # 원본 명령, 환경, 지표, 허용 편차
  adapters/<baseline>.py           # 공통 계약 변환만 담당
  evaluators/                      # 공정한 공용 채점 코드
  results/<run-id>/
    environment.json               # OS, CPU/GPU, driver, package lock
    raw/                            # 공식 코드가 만든 수정 전 출력
    normalized/                     # 공통 schema로 변환한 출력
    metrics.json
    run.log
    checksums.sha256
perception-framework/perception_framework/
  selection/
  perception/providers/
  perception/tracking.py
```

외부 저장소와 대형 데이터·가중치는 Git에 넣지 않는다. source lock, protocol,
manifest, adapter, evaluator와 작은 결과 요약은 Git에 보존한다. 원시 대용량 산출물은
checksum이 포함된 로컬/아카이브 참조를 남긴다.

## 5. 공통 계약

논문마다 입력 의미가 다르므로 하나의 과도한 `SelectionStrategy`로 합치지 않는다.

- `PerformancePredictor.predict(context, candidate) -> PerformanceEstimate`
- `ExecutionPolicy.choose(estimates, constraints) -> ExecutionDecision`
- `PerformanceEstimate`: latency_ms, accuracy_proxy, energy_j, uncertainty,
  profile_id, provenance
- detector는 기존 `PerceptionProvider.detect()`를 사용한다.
- `Tracker.update(detections, frame_meta) -> list[Track]`를 도입한다.
- 원본 출력은 손실 없이 보존하고 마지막 단계에서만 공통 schema로 변환한다.
- OCTOPINF/Ekya는 원본 controller를 대체하지 않고 외부 system provider로 연결한다.
- H2ST의 p-value/task-id, DGS/RGR-IOD의 model artifact, Ekya의 allocation schedule은
  서로 다른 schema로 보존한 뒤 배포 요청에서만 결합한다.

## 6. Baseline별 상세 구현 계획

### 6.1 ApproxDet

1. 실제 장치·driver 조건과 ILSVRC VID/weight checksum을 고정한다.
2. shape, proposal 수, sampling interval, tracker, downsample ratio의 다섯 knob와
   contention generator를 원본 그대로 실행한다.
3. detector/tracker latency·accuracy predictor와 switching overhead를 각각 재현한다.
4. 검증 뒤 `ApproxDetPredictor`와 `ApproxDetPolicy` adapter를 구현한다.
5. 완료 기준: 공식 teaser 2종, branch별 로그, SLA 위반률·mAP·p50/p95 latency,
   static branch 비교 결과를 생성한다.

### 6.2 DACC

1. DEOF 코드에서 Accuracy Predictor, Lyapunov 최적화, heuristic genetic algorithm이
   DACC와 일치하는 파일·commit을 표로 매핑한다.
2. UA-DETRAC/VisDrone2019, EdgeYOLO/YOLOv7, 네트워크 조건을 고정한다.
3. optical flow, entropy, edge-pixel feature와 계산 비용을 함께 기록한다.
4. offload ratio 결정과 복잡 frame 선택을 분리해 ablation한다.
5. 완료 기준: edge-only/all-cloud/random/DEOF/DACC의 F1, 전송량, latency,
   deadline miss, predictor overhead를 동일 evaluator로 산출한다.

### 6.3 nn-Meter

1. archive된 commit과 지원되는 구형 Python/프레임워크를 격리한다.
2. 사전 predictor로 공식 sample을 재현하고, 현재 ONNX/대상 장치에는 Builder로
   predictor를 새로 만든다.
3. `NnMeterPredictor`는 단위를 바꾸지 않고 latency_ms와 device/version을 반환한다.
4. 완료 기준: absolute/relative error, ±10% 적중률, profiling 횟수·시간을 보고한다.

### 6.4 FOMO

1. 공식 RWD 구성과 known/unknown split을 준비한다.
2. attribute 생성·선택·refinement와 checkpoint/evaluator를 재현한다.
3. 현재 OWL-ViT는 FOMO가 아닌 `owlvit-wide-vocab` 비교군으로 둔다.
4. 완료 기준: 공식 RWD metric, known AP, unknown recall/precision과 checksum이다.

### 6.5 OW-OVD

1. YOLO-World 환경, LLM attribute, VSAS·HAUF 설정을 고정한다.
2. M-/S-OWODB의 task별 학습·평가 순서를 보존한다.
3. VSAS 제거와 HAUF 제거 ablation을 포함한다.
4. 완료 기준: task별 U-Recall, U-mAP, known mAP, wilderness impact와 OVD 성능이다.

### 6.6 OWOBJ

1. 코드·config·checkpoint가 실행 불가능하면 수치를 복사하지 않고
   `BLOCKED_UPSTREAM`으로 기록한다.
2. 가능하면 PROB 위 variational objectness, dynamic Gaussian prior, energy margin을
   공식 설정으로 학습하고 두 핵심 요소를 ablation한다.
3. 완료 기준: M-/S-OWODB U-Recall과 known mAP. FSOD/OV-LVIS는 후속 범위다.

### 6.7 ByteTrack

1. 현재 구현은 `BYTE-style lightweight`로 구분한다.
2. 공식 YOLOX, Kalman filter, Hungarian assignment, tracked/lost/removed 상태와
   high/low score 연관을 공식 코드로 재현한다.
3. 공식 출력과 현재 `Detection`/`Track` 사이의 변환 테스트를 추가한다.
4. 완료 기준: MOT17 validation의 MOTA, IDF1, HOTA, ID switches, FPS이며 같은
   detection으로 IoU/lightweight BYTE/official ByteTrack을 비교한다.

### 6.8 OVTR

1. TAO video ID 단위의 작은 smoke set을 먼저 구성하고 전체 용량은 사전 고지한다.
2. 공식 checkpoint로 OVTR-Lite 뒤 full OVTR을 실행한다.
3. TAO base/novel split과 TETA evaluator를 변경하지 않는다.
4. 완료 기준: base/novel별 TETA, LocA, AssocA, ClsA, FPS 및 동일 subset의
   modular detector+ByteTrack 비교다.

### 6.9 DGS

1. AI-L-04의 교체 가능한 Learning Provider로 MMDetection 3.3/GroundingDINO
   환경을 lock하고 운영 추론과 격리한다.
2. COCO incremental smoke 뒤 CDIOD(DIOR/PascalVOC/RUOD)로 확장한다.
3. task distribution, group assignment, adapter 생성·consolidation 이력을 저장한다.
4. 완료 기준: task별 current/old/overall AP, forgetting, forward transfer, parameter
   증가량과 GPU-hours다.

### 6.10 H2ST

1. 공식 TIL setting, feature layer와 source/target sample을 고정한다.
2. C2ST, hierarchical test, calibration을 각각 재현한다.
3. 단일 입력 confidence threshold로 변환하지 않는다.
4. 완료 기준: AUROC/FPR95, task-id accuracy, overhead와 표본 수별 statistical power다.

### 6.11 RGR-IOD

1. Stable Diffusion version, prompt, seed와 클래스별 생성 수를 고정한다.
2. old/new pseudo-label, filtering, SCS, mixed-domain training을 재현한다.
3. 합성 이미지는 라이선스·보관 정책 승인 뒤 저장한다.
4. 완료 기준: VOC 15-5 smoke의 old/new/overall mAP, forgetting, 생성·학습 시간과
   저장량이며 이후 multi-step/COCO로 확장한다.

### 6.12 Ekya

1. 공식 Ray 환경과 공개 데이터 중 가장 작은 구성을 선택한다.
2. micro-profiler의 accuracy projection과 Thief Scheduler를 각각 검증한다.
3. inference-only/fair/random/fixed-retrain scheduler를 함께 실행한다.
4. 완료 기준: window 평균 accuracy, deadline miss, training completion, allocation
   trace, scheduler overhead와 GPU-hours다.

### 6.13 OCTOPINF

1. release/tag, Docker image, PostgreSQL schema, C++ build와 NVIDIA 환경을 고정한다.
2. 단일 장치 pipeline smoke 뒤 복수 장치로 확장한다.
3. adaptive batching, workload distribution, GPU co-location, autoscaling ablation을 한다.
4. 프레임워크는 controller API/metric adapter만 제공한다.
5. 완료 기준: throughput, p50/p95/p99 latency, SLO attainment, GPU utilization,
   queue length, network bytes와 controller overhead다.

### 6.14 E4

1. 공식 코드가 없으므로 수식·모델·exit·frequency·계측 조건에 원문 페이지를 붙인
   구현 명세를 먼저 만든다.
2. attention cascade/accumulated pooling과 JIT coordinate descent를 분리 구현한다.
3. DVFS·전력 계측이 가능한 승인된 장치에서만 실행한다.
4. 완료 기준: fixed-exit/fixed-clock/early-exit-only/DVFS-only/E4의 accuracy,
   latency, joule/frame, profiler overhead이며 `independent reimplementation`으로 표기한다.

## 7. 구현 순서와 Gate

1. **Phase 0—요구사항·출처 감사**: 최신 Sheet의 AI-L-01~08을 로컬 요구사항과
   traceability에 동기화하고 14개 source lock과 protocol 초안을 만든다. 실험 없음.
2. **Phase 1—공통 기반**: manifest, 환경 capture, checksum, schema, evaluator와
   AI-L-08 lineage 계약을 구현한다.
3. **Phase 2—inference**: ByteTrack → nn-Meter → FOMO/OW-OVD → OVTR-Lite.
4. **Phase 3—장치·분산**: ApproxDet → DACC → OCTOPINF → E4.
5. **Phase 4—학습·MLOps 계약 검증**: AI-L-01~08 순환을 유지하며 H2ST →
   RGR-IOD → DGS → Ekya의 후보 선별·상태 전이·검증·lineage 계약을 소규모 fixture로
   확인한다. 현재 범위에서는 모델 학습·fine-tuning을 수행하지 않는다.

각 baseline은 G0 출처, G1 clean install/smoke, G2 공식 evaluator 원본 결과, G3 공통
schema 무손실 변환, G4 capability 격리, G5 고정 manifest 비교, G6 명령·환경·결과·
한계·checksum·traceability 문서화를 차례로 통과해야 한다. 장비가 없으면 mock으로
완료 처리하지 않고 `BLOCKED_HARDWARE`로 남긴다.

## 8. 테스트와 공정성 규칙

- 단위 테스트는 schema, 경계값, optional dependency와 fallback을 검증한다.
- golden test는 공식 출력 fixture의 정규화 전후 값을 비교한다.
- integration test는 외부 프로세스 실패·timeout·빈 결과에서 기능 격리를 검증한다.
- 공식 evaluator와 공용 evaluator 결과를 모두 저장한다.
- 같은 비교에서는 파일 목록, split, sampling, seed, detector 출력, threshold와 실행
  provider를 고정한다. detector 비교와 tracker 비교를 분리한다.
- 데이터셋이 다르면 수치를 한 표에 놓더라도 우열을 단정하지 않는다.
- 실패·null·불리한 결과도 삭제하지 않고 원시 artifact와 함께 보고한다.

## 9. 실험 승인 절차

전체 baseline을 연속 실행하기 위한 구체적인 데이터·환경·목적·비용·산출물은
[`master-experiment-approval.md`](master-experiment-approval.md)에 고정한다. 해당 문서의
V01~V14 전체를 명시적으로 승인받으면 문서에 적힌 고정 protocol 실행은 아래 정보 공개와
승인 요건을 충족한 것으로 보며 baseline별 재승인 없이 순차 실행한다. 독립 baseline의
실패나 blocker는 나머지 진행을 중단시키지 않는다.

통합 승인에 포함되지 않은 실행 또는 실질적으로 변경된 재실행은 다음을 다시 출력하고
**그 실행에 대한 명시적 승인 후** 시작한다.

1. 데이터·annotation·weight의 정확한 경로와 예상 추가 용량
2. CPU/GPU/RAM/OS/driver/CUDA/container와 execution provider
3. 목적, 가설, 비교군과 controlled variable
4. 유리·불리·무효 결과를 포함한 객관적 예상
5. 실행 명령, seed, threshold, 반복 수와 예상 시간·비용
6. raw/normalized/metric/log 산출물 경로
7. 알려진 한계와 원 논문 환경 차이

데이터, 모델, split, threshold, 방법 또는 장비가 바뀌면 이전 승인을 재사용하지 않는다.

## 10. 현재 상태와 다음 작업

- V01~V14의 논문 핵심 결정 규칙을 vendor-neutral 모듈로 구현했고, 고정 fixture와
  `common-smoke.json` manifest를 사용하는 공통 실행기로 기능 검증했다. 각 실행의 입력,
  정규화 결과, 지표, 환경, checksum은 `experiments/external/results/`에 보존한다.
- 경량 `ByteTracker`와 FOMO/OW-OVD/OWOBJ/OVTR inference proxy 통과는 공식 학습,
  checkpoint 또는 논문 성능 재현 완료를 의미하지 않는다. 실행 결과도 이 한계를 명시한다.
- RTX 3060 12 GiB가 WSL2 호스트 권한에서 확인됐고, CUDA 13/cuDNN 9 라이브러리
  경로를 지정한 OWL-ViT 단일 프레임 검증에서 실제 활성 provider가
  `CUDAExecutionProvider`임을 확인했다. 산출물은
  `experiments/external/results/gpu-runtime-smoke/`에 있다.
- 기능 검증 범위의 구현과 회귀 검증은 완료했다. 공식 논문 수치 재현(G1~G5 중 외부
  checkpoint·공식 evaluator·학습이 필요한 항목)은 이번 승인 범위 밖이며 미완료다.
  다음 단계로 확장하려면 baseline별 데이터·모델·비용을 다시 제시하고 승인받는다.
