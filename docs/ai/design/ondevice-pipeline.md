# 온디바이스 파이프라인 — 모델 선정, 실측, 에이전트별 요구, 하드웨어 스펙

상태: 설계 결정 + 실측 기록. 이동형 에이전트(사족보행) 기준으로 확정, 드론은 무게/전력
제약으로 별도 검토 대상(§3 하단). 프레임워크 코드 반영은
[reference/local_safety.py](../../../perception-framework/perception_framework/reference/local_safety.py),
[reference/fixed_camera_stream.py](../../../perception-framework/perception_framework/reference/fixed_camera_stream.py),
[risk/path_evaluation.py](../../../perception-framework/perception_framework/risk/path_evaluation.py)를 따른다
(`reports/2026-09-08_1131_온디바이스-엣지-기능분리.md` 참고).

**재현성 안내**: 이 문서의 수치 대부분은 `research/oln_training/`(저장소 안, 재현 가능)에서
나왔다. 일부(depth 정확도 비교, §2.4)는 `/tmp/depth_accuracy_check/`(에이전트 임시 작업
공간, 저장소 밖, 휘발성)에서 나왔으므로 스크립트를 다시 받아 재실행해야 재현된다 — 원본
산출물 자체는 남아있지 않을 수 있다.

## 0. 왜 이 구조인가 (한 문단 요약)

말단(로봇)은 네트워크 단절·돌발 접근 같은 즉시 대응만 로컬로 처리하고(AI-N-01), 의미
분류·동일 개체 추적·환경 융합처럼 무겁고 비-실시간인 것은 edge로 비동기 이관한다
(AI-S-01/06, AI-B-10). 이 결정 하나가 아래 모든 절의 전제다: **온디바이스가 최적화해야
할 것은 "인지 전체"가 아니라 "class-agnostic 위험 감지 하나"뿐**이라는 뜻이고, 그래서
K/U(known/unknown) 의미 판별 연구 결과(§1.3)가 실제로는 "왜 온디바이스에 분류기가
필요 없는가"의 근거로 재활용된다.

## 1. 단계별 기능·선정 모델·근거 연구

### 1.1 최종 온디바이스 파이프라인 (확정)

| 단계 | 기능 | 선정 모델/방법 | 상태 |
|---|---|---|---|
| 1 | class-agnostic proposal (공간 위험 후보 박스) | 커스텀 torchvision `fasterrcnn_mobilenet_v3_large_fpn` — **RPN까지만 사용**(backbone+FPN+RPN, ROI head/분류기 미사용), ONNX export | 확정, Pi5 실측 완료 |
| 2 | 후처리 | Hard-NMS(IoU 0.4), `cv2.dnn.NMSBoxes` 기반 `fast_nms` | 확정 |
| 3 | depth/TTC | ZipDepth(`fabiotosi92/ZipDepth`, ECCV2026, MIT) | 확정, TUM RGB-D 실측 완료 |
| 4 | hazard 지속성(hysteresis) | ByteTracker(순수 Python 2단계 IOU greedy matcher, Kalman/Hungarian 없음) | 확정 — 용도가 "동일 위험요소 추세 판단"으로 재정의됨(§3) |
| 5 | 안전 상태 판단 | `LocalSafetyJudge`, `MOBILE_AGENT_OPTIONAL_KINDS=(perception.distance,)` | 확정, 프레임워크 코드 반영 완료 |

의미 분류(classify)·동일 개체 의미 추적(semantic re-id)은 이 목록에 없다 — edge로 이관.

### 1.2 proposal 모델 후보와 탈락 사유

| 후보 | 특징 | 결과 | 판정 |
|---|---|---|---|
| **P0**: NanoDet-Plus-m_416(ShuffleNetV2+GhostPAN, 공식 ONNX, COCO-사전학습, 분류기 포함) | 가볍고 head 안 뗐는데도 빠름 | Recall@100=35.5%(COCO 도메인, frozen baseline) | 한때 1순위였다가 P1의 sparse/empty scene 판별력이 더 낫다는 판단으로 교체 |
| **P1**(최종): `fasterrcnn_mobilenet_v3_large_fpn` RPN-only | COCO recall은 P0보다 낮지만 배경/빈 장면에서 오탐이 적음; PyTorch 네이티브 실행은 Pi5에서 1270ms(0.79FPS)로 처참 — ONNX export 후 6~7배 빨라짐(§2.1) | 실측 168.93ms/5.92FPS로 5Hz 통과 | **최종 채택** |
| OLN class-agnostic fine-tune | COCO로 미세조정해 class-agnostic recall 개선 시도 | Recall@100 33.0%→6.7%로 참사 — COCO의 sparse(~7 obj/img) 라벨링 습관이 LVIS의 dense(~43 obj/img) 분포에 과소적합. 학습 자체는 정상(학습 이미지 자체 recall 68.4%로 확인) | 폐기 |

### 1.3 known/unknown(K/U) 판별 방법 비교 — "온디바이스에 분류기가 필요 없는" 근거

P1은 RPN-only라 분류기가 없다. 배포 전 "그래도 confidence 신호를 조합하면 K/U 판별이
나아지지 않을까"를 4가지 방법으로 직접 실측했다(LVIS 기준 unknown recall@50/@100):

| 방법 | unknown recall@50 | @100 |
|---|---|---|
| **objectness 단독** | **21.5%** | **26.6%** |
| objectness×energy 결합 | 12.4% | 19.6% |
| objectness×기하학적 거리(UADet 스타일) | 12.5% | 18.5% |
| energy-score 단독 | 3.2% | 5.5% |
| softmax-unknown 단독 | 1.1% | 3.8% |

**4가지 조합 전부가 objectness 단독보다 못했다** — 배경/잡음 proposal도 "낮은 확신"이라는
점에서 진짜 unknown 객체와 구별이 안 되기 때문. 이 결과가 실질적으로 의미하는 것: 온디바이스에
분류기를 얹어봤자 K/U 판별이 더 좋아지지 않으므로, 지금 아키텍처처럼 온디바이스는
objectness만 쓰고 의미 판별 자체를 edge로 넘기는 것이 성능 손실 없는 결정이다.

### 1.4 도메인 전이 실측 (LOCO, 실제 물류 현장 데이터)

COCO로 학습된 모델이 완전히 다른 도메인에서 어떻게 되는지 실측(TUM-FML LOCO, CC0):

| 클래스 | 결과 | 원인 |
|---|---|---|
| pallet_truck | IoU 0.523 | 준수한 전이 |
| stillage | IoU 0.495 | 준수한 전이 |
| pallet | recall 16.3%(IoU@0.5) → 66.5%(IoU@0.1) | **모델 실패가 아니라 GT 라벨링 관행 차이** — GT가 적재물 제외한 팔레트 받침(53px)만 박싱, 모델은 "적재물 포함 전체 스택"을 합리적으로 박싱해서 IoU가 낮게 나옴. 육안 확인으로 확정(사용자 지적으로 재검증) |

### 1.5 depth 모델 후보와 탈락 사유

| 후보 | 라이선스 | 정확도(TUM RGB-D, δ1) | 비고 |
|---|---|---|---|
| **ZipDepth**(최종) | MIT | **0.929** | affine-invariant inverse depth라 자체 disparity-space scale+shift 정렬 프로토콜 필요 — naive median-scaling으로 평가하면 δ1 0.321로 완전히 잘못된 결과가 나옴(프로토콜 불일치 함정, 실제로 한 번 걸림) |
| FastDepth | 공식 가중치 서버(`datasets.lids.mit.edu`) 사망, 커뮤니티 재구현은 라이선스 파일 없음 | 0.720 | 정확도·라이선스 모두 ZipDepth에 밀림 |

## 2. Pi5 실측 결과값

실물 Raspberry Pi 5(`pi2`, <DEVICE_IP>, Debian 13, Python 3.13.5, 4-core Cortex-A76,
8GB RAM, GPU 없음)에서 측정. onnxruntime 실행 provider는 `['AzureExecutionProvider',
'CPUExecutionProvider']`뿐 — **ARM 최적화 실행 provider(XNNPACK 등) 없음**이 아래 대부분의
실패 패턴(양자화 역효과 등)의 근본 원인.

### 2.1 proposal-only (640px) — 확정 기준선

| 단계 | mean | p95 |
|---|---|---|
| proposal(ONNX) | 167.54ms | 174.96ms |
| NMS | 0.38ms | - |
| tracking | 1.01ms | - |
| **합계** | **168.93ms → 5.92 FPS** | - |

→ AI-N-01 5Hz(200ms) 기준 **PASS**. (PyTorch 네이티브 실행은 같은 모델로 1270ms — ONNX
export가 필수였던 이유.)

### 2.2 proposal + depth 결합 (512px + 256px, 실제 간섭 포함 실측)

| 단계 | 단독 실행 | 결합 실행(간섭 포함) |
|---|---|---|
| P1(512) | 108.2ms | 125.3ms |
| ZipDepth(256) | 63.5ms | 87.8ms |
| **합계** | - | **213.0ms → 4.69 FPS** |

→ 5Hz(200ms) 대비 13ms(6%) 초과로 **근소하게 FAIL**. 두 모델을 같은 프로세스에서 순차
실행했을 때 단독 측정값의 단순 합보다 실제로 더 걸린다(P1 +17ms, ZipDepth +24ms) — 이것
자체가 "다른 구성에서 측정한 값을 자동으로 합산·전이해서는 안 된다"(AI-B-01)는 실사례.

주의: §2.1(640px)과 §2.2(512px)는 proposal 해상도가 달라 "depth를 얹은 순수 비용"을
바로 뺄셈할 수 없다. P1@640px+depth 결합은 아직 실측하지 않음 — 필요하면 재측정.

### 2.3 시도했던 경량화 — 전부 역효과 또는 무변화

| 방법 | 결과 |
|---|---|
| INT8 동적 양자화 | 결합 339.3ms — **오히려 2배 가까이 느려짐**(ARM 최적 INT8 커널 부재로 스케일/제로포인트 계산 오버헤드가 이득보다 큼) |
| FP16 변환 | ZipDepth 63.5ms→64.2ms, **변화 없음**(같은 이유). P1 FP16 export는 타입 불일치 에러로 미해결 |
| onnxruntime 스레드 분할(2+2) | 213.0ms→223.1ms, **더 느려짐**(순차 실행이라 진짜 동시성 이득이 없고 스레드만 줄어듦) |
| 멀티 Pi 분산 / 단일 Pi 멀티프로세싱 | 리서치 결론: 검증된 로보틱스 패턴 아님, Pi-Pi 통신만으로 33ms 예산 대부분 소진(ROS2/DDS 오버헤드 최대 50%, Pi5 Ethernet 패킷 손실 이슈, WiFi 200-300ms), Pi5는 메모리 대역폭이 병목이라 4코어 확장해도 실측상 ~2배(4배 아님) 그침 |

### 2.4 depth 정확도 (TUM RGB-D `freiburg1_xyz`, 실제 GT, CC BY 4.0)

공식 프로토콜(disparity-space scale+shift 정렬) 기준: **AbsRel 0.071, δ1 0.929**
(오차 25% 이내 픽셀 92.9%) — TTC/안전거리 판단엔 충분한 수준.

## 3. 에이전트별 요구 기능

드론은 이번 라운드 범위 제외(§4의 무게/전력 결론 참고). 사족보행 로봇과 고정 카메라만 확정.

### 3.1 사족보행 로봇(이동형)

- **온디바이스(실시간, §1.1 파이프라인 그대로)**: class-agnostic proposal + depth/TTC +
  hazard-persistence tracking + `LocalSafetyJudge`(비디오 필수, distance만 선택 — 분류·
  semantic track은 애초에 로컬에 없음, "설계상 없음"으로 FULL_AWARENESS 도달 가능하도록
  `MOBILE_AGENT_OPTIONAL_KINDS`로 스코프 축소됨).
- **네트워크 단절 시**: 로컬 안전 루프는 그대로 유지(AI-C-20의 긴급정지 예외 조항과 일치
  — 네트워크 명령만이 안전 기능의 유일 경로가 되어서는 안 됨). 인지 스트림이 지연/유실돼도
  안전에는 영향 없음(애초에 안전 경로 밖).
- **edge로 비동기 전송**: proposal+depth 원시 결과. edge가 의미 분류, 동일 개체 추적
  (semantic re-id), 다중 소스 융합, 환경 지도·인프라 정보 구축(AI-S-01/02/06/08)을
  전담.
- **edge로부터 수신**: 로컬 안전/인지에 실제로 필요한 환경 사전정보만(AI-N-02 채널,
  버전 검증 + last-known-good). **맵 전체·경로 자체는 받지 않는다** — 실제 이동 명령은
  별도 제어 스택이 AI-C-20 물리 명령 채널로 발급.
  - 경로에 대한 AI의 역할은 "후보 평가"까지: 외부(edge/백엔드 경로계획)가 만든 후보에
    대해 이미 확보한 위험/객체 근거로 위험도·근거 충분도만 매긴다
    (`risk/path_evaluation.py`). 후보 생성·순위화·확정은 하지 않는다(AI-C-19).
- **실제 필요 Hz(미확정)**: AI-N-01 원문대로 "이동속도·제동거리·센서 취득·추론·제어
  지연을 합산"해 역산해야 한다 — 로봇 최대 속도·제동 성능 스펙이 있으면 §2.2의 213ms
  예산이 실제로 충분한지 바로 계산 가능. 아직 미수행.

### 3.2 고정 카메라

- AI-N-01의 "이동형 에이전트" 범위 밖 — **안전 판단 자체가 없음**.
- 상시 인지만 수행(`FixedCameraPerceptionStream`), 가능한 범위(분류기 있으면 분류까지,
  없으면 class-agnostic만)로 계속 결과를 낸다.
- **edge로 편도(one-way) 전송** — 응답을 기다리지 않고 계속 publish.
- 완전 무입력은 아님: 카메라 보정 프로파일(AI-E-02)·실행 구성(AI-N-02) 갱신은 별도
  저빈도 이벤트 채널로 예외적으로 수신.

## 4. 성능별 하드웨어 스펙 요구사항

아래는 **벤더 공개 수치 — 우리 커스텀 모델로 재검증 안 됨**(AI-B-01: 다른 구성 성능을
자동으로 같다고 가정 금지). 구매 전 반드시 재측정.

| 옵션 | 가격 | 연산력 | 우리 모델 이식 리스크 |
|---|---|---|---|
| (현재) Pi5 CPU only | $0 | - | 실측 완료 — proposal-only PASS(5.92FPS), 결합 시 근소 FAIL |
| Hailo-8L(Raspberry Pi AI Kit) | $70 | 13 TOPS INT8 | **높음** |
| Hailo-8(Raspberry Pi AI HAT+) | $110 | 26 TOPS INT8, YOLO급 6-7ms(벤더) | **높음** |
| Jetson Orin Nano Super Dev Kit | $399(2026-07 가격 인상 후) | 67 TOPS | **낮음** |
| ~~Coral Edge TPU~~ | ~$70 | 4 TOPS | 2022년 이후 사실상 미지원, 제외 권고 |

**Hailo 리스크가 높은 이유**: Dataflow Compiler가 ONNX ir_version ≤8만 지원(우리 export는
opset17), 커스텀 레이어 제약이 크며, 칩 1개당 모델 1개만 동시 구동(P1/ZipDepth를
타임셰어링해야 함). 우리 P1 export는 이미 `dynamo=True` 실패로 legacy exporter를 써야
했던 비표준 그래프이고, ZipDepth는 export 시점에 어텐션 블록을 수동 패치한 커스텀 구조라
컴파일 통과가 보장되지 않는다 — 이는 돈이 아니라 재설계·재검증 리스크다.

**Jetson 리스크가 낮은 이유**: 표준 ONNX→TensorRT 경로로, 우리가 이미 샌드박스 GPU에서
쓴 것과 같은 계열 툴체인이다. GPU 스트림 기반이라 두 모델의 진짜 동시 실행이 가능해
Hailo의 "한 번에 하나" 제약도 없다.

| 목표 | 필요 조치 | 비용 | 확신도 |
|---|---|---|---|
| 현행 5Hz(proposal only) | 없음 — 이미 통과 | $0 | 실측 완료 |
| 5Hz(proposal+depth) 안정적 통과 | Pi5 CPU만으론 13ms 부족분 못 메움 → 최소 Hailo-8L급 | +$70~110 | 낮음(컴파일 리스크) |
| 30fps(33ms), proposal+depth | Hailo(컴파일 성공 시 저렴하나 불확실) / Jetson(비쌈, 성공 확률 높음) | +$110(도박) 또는 +$399(안전) | Jetson만 중간 이상 |

**결론**: Pi5 CPU 단독으로 30fps는 불가능(시도한 경량화 전부 역효과/무변화). 다음 단계는
로봇 최대 속도/제동거리로 진짜 필요한 Hz를 역산해 "30fps가 정말 필요한 목표인지"부터
재확인하는 것 — AI-N-01 자체가 5Hz를 시작점으로만 규정하고 있다.
