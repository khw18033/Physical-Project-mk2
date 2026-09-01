# 전체 기술 검증 통합 사전승인서

작성: 2026-09-01

상태: **승인 및 기능 검증 실행 완료** (2026-09-01). 추가 다운로드 0 GiB,
모델 학습·fine-tuning·운영 배포는 수행하지 않았다.

## 1. 검증 범위

이번 작업의 목적은 논문 성능표를 재현하거나 모델을 새로 학습하는 것이 아니다. 소규모
고정 데이터에서 다음만 확인한다.

1. 공식 코드 또는 최소 충실 구현이 실행되는가.
2. 논문의 핵심 구성요소를 켜고 끌 때 예상한 방향의 동작 차이가 발생하는가.
3. 결과를 프레임워크 공통 계약으로 손실 없이 변환할 수 있는가.
4. 기능 부재·실패가 다른 capability를 중단시키지 않는가.

따라서 결과는 `기능 검증(functional validation)`으로 표기한다. 논문 전체 데이터·학습
protocol을 수행하지 않은 결과를 `논문 재현` 또는 논문 대비 성능 우위로 주장하지 않는다.

## 2. 데이터 최소화 원칙

### 공통 주 데이터 — 기존 TAO subset

- annotation:
  `datasets/tao/annotations/annotations-be63b9c27ebddbd774d4deef7e49f50a6c71e144/validation_with_freeform.json`
- frame: `datasets/tao/frames/val/YFCC100M/`
- manifest: `datasets/tao/manifests/val-yfcc100m-annotated.json`
- 현재 상태: 4,178 frames, missing 0, 약 222 MiB
- 사용 대상: 탐지, unknown 처리, 추적, 실행 선택, 결과 schema 검증

공통 manifest에서 다음 두 계층을 코드로 결정한다. 사람이 유리한 장면을 고르지 않는다.

- smoke: video ID를 정렬한 뒤 앞의 3개 video, 최대 300 frames
- validation: 현재 4,178 frames 전체

### 공통 보조 데이터

- 지속학습/OOD 구조 확인: TAO 결과 feature와 기존
  `datasets/mddrobots_subset/` archive 중 manifest가 지정한 소수 frame만 zip streaming
- latency predictor: 기존 `models/onnx/*.onnx`
- synthetic fixture: 경계조건·실패경로 단위 테스트에만 사용하며 성능 결론에는 사용 금지

### 추가 다운로드 제한

- 모델은 공개된 inference checkpoint만 받는다. 새 학습용 backbone·optimizer state는 받지 않는다.
- 논문 전용 dataset은 공통 TAO로 API 실행 자체가 불가능할 때만 공식 archive 내부의
  최소 1~3 sequence 또는 evaluator sample을 선택한다.
- 개별 baseline 추가 다운로드 상한: **10 GiB**
- 전체 추가 다운로드 상한: **40 GiB**
- 상한 초과, gated 접근, 유료 API, 데이터 외부 업로드는 이 승인 범위 밖이다.

## 3. 실행 환경과 비용

| 항목 | 현재 확인값 |
|---|---|
| OS | Ubuntu 26.04 LTS / WSL2 |
| CPU·RAM | i9-12900K 24 threads / RAM 31 GiB / swap 8 GiB |
| 디스크 | 932 GiB 가용 |
| GPU | NVIDIA GeForce RTX 3060 12 GiB, driver 591.86. 호스트 권한에서 확인 |
| 기본 환경 | `perception-framework/.venv`, Python 3.14.4 |
| 격리 환경 | `experiments/external/envs/<baseline>/` 또는 container |

ONNX Runtime GPU 실행에는 샌드박스 밖 장치 접근과 다음 라이브러리 경로가 필요하다.

```bash
export LD_LIBRARY_PATH="$PWD/.venv/lib/python3.14/site-packages/nvidia/cu13/lib:$PWD/.venv/lib/python3.14/site-packages/nvidia/cudnn/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
```

이 조건에서 `CUDAExecutionProvider` session 생성을 확인했다. 각 GPU run은 실제 활성
provider를 `environment.json`에 기록하고 CPU fallback 결과와 섞지 않는다.

- 전체 추가 저장량: 최대 40 GiB
- CPU 검증: baseline당 약 10분~4시간, 전체 약 1~3일
- GPU 검증: RTX 3060에서 baseline당 약 10분~8시간
- 금전 비용: 로컬 자원만 사용하므로 직접 사용료 0원. 클라우드·유료 API 불포함
- 학습, fine-tuning, Stable Diffusion 대량 생성, 전체 benchmark 다운로드는 수행하지 않음

## 4. 공통 산출물

```text
experiments/external/
  source-lock.json
  protocols/<baseline>.md
  manifests/common-smoke.json
  manifests/common-validation.json
  results/<run-id>/
    environment.json
    run.log
    raw/
    normalized/
    metrics.json
    checksums.sha256
```

seed는 공식값, 없으면 42로 고정한다. threshold는 공식 inference 기본값을 사용하고
공통 비교에서는 동일 threshold를 별도 축으로 기록한다. 실패·null·불리한 결과도 보존한다.

## 5. 기술별 검증 계획

| ID | 기술 | 데이터·모델 경로 | 목적·비교 | 객관적 예상 | 추가 비용·산출물 |
|---|---|---|---|---|
| V01 | ByteTrack | 공통 TAO + 기존 detector 출력, 필요 시 공식 tracker 코드만 | IoU / 경량 BYTE / 공식 BYTE의 low-score 연관 확인 | 점수 분포가 연속적이면 track 유지가 나아질 수 있으나 동일·악화 가능 | ≤1 GiB, CPU 1–3h, `results/v01-bytetrack-*` |
| V02 | nn-Meter | `models/onnx/`, predictor만 `models/external/nn-meter/` | 예측 latency와 실제 warm-up latency 비교 | 현재 장치가 사전 predictor 대상과 달라 오차가 클 수 있음 | ≤2 GiB, CPU 2–6h, `results/v02-nnmeter-*` |
| V03 | FOMO | 공통 TAO, checkpoint `models/external/fomo/` | attribute evidence와 unknown 출력/schema 확인; OWL-ViT와 구조 비교 | 일부 unknown 후보 개선 가능, 공식 RWD 성능 결론 불가 | ≤5 GiB, GPU ≤4h, `results/v03-fomo-*` |
| V04 | OW-OVD | 공통 TAO, `models/external/ow-ovd/` | VSAS/HAUF on-off와 known/unknown score 변화 확인 | unknown score가 달라질 수 있으나 AP 개선은 보장 못함 | ≤5 GiB, GPU ≤6h, `results/v04-ow-ovd-*` |
| V05 | OWOBJ | 공통 TAO, 공개 checkpoint가 있을 때만 `models/external/owobj/` | objectness/prior/energy 출력과 adapter 확인 | 자산 미공개면 `BLOCKED_UPSTREAM`; 임의 재구현 결과로 대체 안 함 | ≤5 GiB, GPU ≤6h, `results/v05-owobj-*` |
| V06 | OVTR | 기존 TAO frames, `models/external/ovtr/` | OVTR-Lite inference, track schema 및 modular pipeline 비교 | 의미 일관성이 나아질 수 있으나 subset TETA는 불안정 | ≤8 GiB, GPU ≤8h, `results/v06-ovtr-*` |
| V07 | ApproxDet | 공통 TAO와 synthetic contention trace, `models/external/approxdet/` | 5-knob predictor/scheduler의 SLA 선택 논리 확인 | 선택은 변해야 하나 TX2 latency·mAP 재현은 불가 | ≤3 GiB, CPU 2–6h, `results/v07-approxdet-*` |
| V08 | DACC | 공통 TAO에서 계산한 optical-flow/entropy/edge-pixel | edge-only/random/DACC decision과 feature overhead 확인 | 복잡 frame 선별 가능, 실제 cloud 이득은 주장 불가 | ≤2 GiB, CPU 2–6h, `results/v08-dacc-*` |
| V09 | OCTOPINF | synthetic request trace + 기존 ONNX | scheduler simulator/단일-node smoke와 batching ablation | 고부하에서 개선 가능, 저부하에서는 overhead 가능 | ≤3 GiB, CPU/GPU ≤8h, `results/v09-octopinf-*` |
| V10 | E4 | 공통 TAO + 기존 ONNX | early-exit decision/JIT search를 mock clock profile로 검증 | 선택 논리는 검증 가능, 실제 energy 절감은 검증 불가 | ≤1 GiB, CPU 2–6h, `results/v10-e4-*` |
| V11 | H2ST | TAO/MDD에서 고정 추출한 소규모 feature | C2ST/H2ST의 ID/OOD와 task-id 흐름 확인 | 분포 차이는 찾을 수 있으나 작은 표본은 통계력이 낮을 수 있음 | ≤2 GiB, CPU/GPU ≤6h, `results/v11-h2st-*` |
| V12 | RGR-IOD | 공통 fixture와 미리 공개된 소수 replay sample만 | pseudo-label filtering/SCS/data lineage 흐름 확인 | 선별 동작은 확인 가능, forgetting 개선은 학습 없이 검증 불가 | ≤2 GiB, CPU 2–4h, `results/v12-rgr-iod-*` |
| V13 | DGS | 저장된 소규모 task feature와 공개 adapter가 있을 때만 사용 | grouping/router/consolidation 상태 전이 확인 | 유사 task grouping 가능, AP·forgetting 성능은 검증 불가 | ≤2 GiB, CPU/GPU ≤6h, `results/v13-dgs-*` |
| V14 | Ekya | synthetic workload·accuracy profile | micro-profiler 입력과 Thief allocation을 fixed/random과 비교 | 동적 배분 차이는 확인 가능, 실제 retraining 효용은 검증 불가 | ≤1 GiB, CPU 2–6h, `results/v14-ekya-*` |

## 6. 검증 완료 기준

각 기술은 다음을 모두 만족해야 `기능 검증 완료`로 기록한다.

- 고정 manifest와 명령으로 재실행 가능
- 핵심 알고리즘의 최소 동작과 off/ablation 차이를 자동 테스트로 확인
- raw→normalized 변환 건수와 주요 값 보존
- 실행 환경·source commit·모델 checksum 기록
- 실패·한계와 검증하지 않은 논문 주장을 결과 문서에 명시

논문 수준 정확도, forgetting, energy, 분산 throughput처럼 대규모 데이터·학습·전용
하드웨어가 필요한 항목은 `미검증`으로 남긴다. 작은 데이터 결과를 확대 해석하지 않는다.

## 7. 중단·계속 조건

- 한 기술이 GPU·checkpoint·호환성 문제로 막혀도 다른 기술은 계속 진행한다.
- checksum·라이선스 불명확, 민감정보, 외부 업로드 필요, 개별 10 GiB 또는 전체
  40 GiB 초과 예상 시 해당 기술을 중단하고 `BLOCKED_*`로 기록한다.
- 기존 데이터·산출물 삭제, 운영 배포, 유료 자원 사용은 승인 범위에 없다.

## 8. 승인 문구

다음 문구로 승인하면 V01~V14를 위 범위에서 순차 실행한다.

> 소규모 공통 데이터 기반 기능 검증 계획, 데이터·모델 경로, 환경, 목적, 예상 결과,
> 최대 40 GiB 다운로드, 비용, 산출물 경로와 미검증 범위를 확인했으며 V01~V14 실행을
> 승인합니다.
