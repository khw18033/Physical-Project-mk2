# Physical AI 분산 인지·디지털 트윈 — 최신 연구 지도 (2026-09 기준)

**관련 문서**: [Physical_AI_분산인지_디지털트윈_전체설계.md](Physical_AI_분산인지_디지털트윈_전체설계.md)(전체 설계),
[ai/architecture.md](ai/architecture.md)(구현 구조), [ai/requirement-traceability.md](ai/requirement-traceability.md)(요구사항 충족 현황)

2026-09-07 기준으로 다시 보면, 전체 설계를 한 논문이 그대로 구현한 SOTA는 아직 없다. 대신 각 계층을
거의 직접 담당하는 최신 연구들이 나왔고, 이들을 조합하면 상당 부분을 기존 구현에서 가져올 수 있다.

특히 새로 중요하게 봐야 할 것은 **Co-GLANCE 2026, GMT CVPR 2026, CATNet CVPR 2026, DisCo 2026,
SCOUT 2026, DGS CVPR 2026, OctoCross**다. 이들을 보면 현재 설계의 각 조각은 상당히 선행되어
있으므로, 새 알고리즘을 처음부터 만들기보다 레이어별 강한 기준선을 재현한 뒤 필요한 부분만
수정하는 전략이 적합하다.

**주의**: 이 문서에 나오는 개별 논문의 검증된 내용(공식 코드 존재 여부, 실제 수치, 재현
가능성)은 `docs/obsidian/papers/`의 각 논문 노트를 기준으로 삼는다 — 이 문서의 표는 지도(map)
역할만 하고, 각 항목의 "정말 그런가"는 링크된 노트에서 원문 검증을 거쳤다. 이 문서 자체는 최초
작성 시점의 리서치 요약이며, 아래 링크된 노트 쪽이 더 최신이거나 더 정확할 수 있다.

## 1. 현재 설계에 대응하는 최신 연구 지도

구현 가능 상태 구분:

- **A**: 공식 코드가 있고 지금 바로 재현하기 좋음
- **B**: 공식 코드가 있지만 현재 시스템에 맞게 상당한 adaptation 필요
- **C**: 최신성은 높지만 현재 공개 구현이 불완전하거나 확인되지 않음

| 우리 설계 계층 | 우선 참고 연구 | 최신성 / 기술적 의미 | 구현성 | 실제 가져올 부분 |
|---|---|---|---|---|
| Pi5 상시 Known/Unknown | [Sato & Law OSOD](obsidian/papers/sato-law-osod.md) | 2026 journal, edge용 작은 YOLO OSOD | A/B | known/unknown detector, unknown crop, 반복 unknown 관리 |
| 최신 경량 OWOD | [YOLO-UniOW-S](obsidian/papers/yolo-uniow.md) | 7.5M params, OWOD+OVD 통합 | B | Wildcard Learning, explicit unknown |
| OWOD 정확도 상한 | [DEUS](obsidian/papers/deus.md) | CVPR 2026 OWOD | C | unknown separation 구조 |
| OWOD 해석가능 상한 | [IPOW](obsidian/papers/ipow.md) | ICML 2026, concept decomposition | A, 서버용 | unknown/known concept decomposition |
| Pi5 Local Tracking | [ByteTrack](obsidian/papers/bytetrack.md) | 구형이지만 경량·범용성 최상급 (이미 `perception/tracking.py::ByteTracker`로 재현됨) | A | detector-independent local track |
| 강한 open-vocab tracking | [COVTrack](obsidian/papers/covtrack.md) | ICCV 2025, continuous OVMOT | A/B | motion+appearance+semantic adaptive fusion |
| 고정 카메라 cross-view | [GMT](obsidian/papers/gmt.md) | CVPR 2026 MCMT | A/B | global trajectory, cross-view association |
| 비동기 시간 정렬 | [TraF-Align](obsidian/papers/traf-align.md) | CVPR 2025 | A/B | delayed evidence의 current-time alignment |
| 최신 비동기 fusion | [CATNet](obsidian/papers/catnet.md) | CVPR 2026 | C | STSync, noise+latency compensation |
| 이종 센서/agent fusion | [DisCo](obsidian/papers/disco-heterogeneous-fusion.md) | Information Sciences, 2026-09-05 | C | arbitrary modality + join/leave |
| 이종 로봇 Active Perception | [Co-GLANCE](obsidian/papers/co-glance.md) | 2026, 현재 아이디어와 매우 근접 (이미 노트 있음, `simulation/pose_graph_alignment.py` 재현 배경) | C | uncertainty→robot allocation→re-observation |
| Unknown/Blind 탐색 | [SCOUT](obsidian/papers/scout.md) | 2026 | C | semantic uncertainty + coverage + travel cost |
| 구현 가능한 multi-robot exploration | [ROAM](obsidian/papers/roam.md) | T-RO 2025 | A/B | map uncertainty 기반 active mapping |
| Capability 기반 agent 선택 | [Semantic Feasibility Reasoning](obsidian/papers/semantic-feasibility-reasoning.md) | 2026-08 | 논문+부록 | capability contract와 allocator 분리 |
| 학습형 heterogeneous coordination | [CASH](obsidian/papers/cash.md) | CoRL 2025 | A | capability-aware robot representation |
| Calibration | [AnyCalib](obsidian/papers/anycalib.md) | ICCV 2025 | A | 모델 독립 single-view calibration |
| 다중 카메라 자원 스케줄링 | [OctoCross](obsidian/papers/octocross.md) | ICSOC 2025/2026 proceedings | A/B | cross-camera workload prediction/offloading |
| Edge inference serving | [OCTOPINF](obsidian/papers/octopinf.md) | PerCom 2025 (이미 `selection/research_execution_baselines.py::OctopinfPlacementPolicy`로 재현됨) | A | resource allocation, batching, SLO |
| 지속학습 | [DGS](obsidian/papers/dgs.md) | CVPR 2026 Highlight (이미 `continual/dgs.py`로 재현됨) | A | class+domain incremental detection |
| Incremental detector | [P²IOD](obsidian/papers/p2iod.md) | CVPR 2026 | A | catastrophic forgetting 억제 |
| 학습/추론 자원 경쟁 | [Ekya](obsidian/papers/ekya.md) | NSDI 2022 (이미 `continual/ekya.py`로 재현됨) | A | retraining/inference resource scheduler |
| UAV+UGV 통합 실험 | [HERCULES](obsidian/papers/hercules.md) | 2026 | A | heterogeneous UAV/UGV simulation |

## 2. Tier 0 — Raspberry Pi 상시 인지는 Sato OSOD부터

현재 요구에 가장 직접적으로 맞는 구현은 여전히 Sato & Law다. 작은 YOLO 기반 OSOD로 known과
unknown을 동시에 검출하고, unknown은 LLM으로 의미를 얻으며, 반복 객체는 MobileCLIP으로
재식별하고 데이터를 축적해 detector를 재학습한다. 저자 스스로 이를 edge device용 fast OSOD로
설계했다.

```text
Camera → Small YOLO OSOD → known / unknown → Local Tracking → Observation
```

단, 저자 hardware는 Pi5가 아니다. Pi5 port 자체가 첫 검증 실험이다.

## 3. YOLO-UniOW-S는 두 번째 필수 후보

OVD와 OWOD를 하나로 통합하며 Wildcard Learning으로 OOD 객체를 unknown으로 취급한다. 공식 S
모델은 7.5M parameters, LVIS minival AP 26.2, 저자 V100 환경 98.3 FPS. 단, "7.5M이므로 Pi5에서
빠르다"라고 가정하면 안 된다 — Pi5 port가 실제 연구 항목이다.

측정 대상: `Known mAP / U-Recall / FPS / p95 / CPU / RAM / Temperature`

## 4. 최신 OWOD 정확도 상한은 DEUS·IPOW

Pi에 넣지는 않더라도 "우리 경량 OSOD가 최신 강한 OWOD 대비 어느 정도인가"를 보여주는 upper
baseline이 필요하다. DEUS(CVPR 2026)는 Energy-based Known Distinction, IPOW(ICML 2026)는 RoI
feature를 discriminative/shared/background concept으로 분해한다.

```text
Pi5: Sato / YOLO-UniOW        GPU Reference: DEUS / IPOW
```

## 5. Pi5 Local Tracking은 ByteTrack 유지가 적절

ByteTrack은 detector output만 넘기면 사용할 수 있고 배포 경로가 이미 존재한다(이미
`perception/tracking.py::ByteTracker`로 재현·검증됨). 최신 연구 비교는 COVTrack(ICCV 2025,
appearance/motion/semantic adaptive fusion)을 edge/server에서 수행한다. COVTrack의 "모든
evidence가 항상 동일하게 신뢰 가능한 것은 아니다"라는 아이디어는 이후 Evidence Fusion 설계에도
참고할 만하다.

## 6. 여러 고정 카메라를 하나의 Persistent Object로 합칠 때는 GMT

GMT(CVPR 2026)는 기존 MCMT(single-camera tracking → 나중에 cross-camera matching)와 달리
처음부터 여러 view의 history를 global trajectory로 만들고 새 target을 거기 association한다.
핵심 모듈: CFCE(Cross-View Feature Consistency Enhancement), GTA(Global Trajectory Associate).
CVMA +13.1%, CVIDF1 +19.2% 보고.

```text
Pi A local_track_3 ─┐
Pi B local_track_8 ─┼→ GMT-style Global Association → zone_object_17
Pi C local_track_1 ─┘
```

GMT는 일반적인 OWOD persistent object framework가 아니므로 cross-camera association 부분만
reference로 쓰고 persistent evidence record는 별도로 유지해야 한다.

## 7. 처리 지연 동안 객체가 움직이는 문제: TraF-Align을 먼저 구현

TraF-Align(CVPR 2025)은 과거 observation의 feature trajectory를 예측해 delayed feature를 ego
agent의 현재 시점까지 이동시킨 뒤 fusion한다. 자동차 BEV cooperative perception용이라 고정
CCTV bbox에 그대로 꽂히지 않는다.

```text
B0  단순 arrival-time fusion
B1  capture_timestamp window
B2  ByteTrack/Kalman object propagation   (← perception/temporal_alignment.py, LRCP 기반, 이미 구현)
B3  TraF-Align-style feature trajectory
```

## 8. 최신 temporal fusion 상한은 CATNet, CVPR 2026

STSync(비동기 feature 동기화) + WTDen(multi-source noise 억제) + AdpSel(유효 feature 선택).
공식 구현 링크 미확인 — TraF-Align은 직접 재현, CATNet은 최신 설계 비교 대상으로만 둔다.

## 9. DisCo는 범용 프레임워크와 매우 관련 있음

*Facilitating heterogeneous sensor information cooperation in multi-agent perception system*,
Information Sciences, Vol. 749, 2026-09-05. Agent마다 센서 구성이 달라도 내부에서 먼저 MFI로
fusion하고 MFP로 통합 collaboration space에 projection하며, agent의 동적 join/leave와 modality
소실까지 다룬다 — 센서 종속성 제거·장치 추가/제거·graceful degradation·heterogeneous agent라는
이 프로젝트의 요구사항과 강하게 겹친다. 다만 논문이 적어둔 공식 code repository는 README와 커밋
1개뿐으로 구현이 아직 없다 — 지금은 복제 대상이 아니라 경쟁 연구/설계 근거로만 둔다.

## 10. Active Perception에서 가장 위협적인 경쟁 연구는 Co-GLANCE

perceptual uncertainty → capability-aware robot allocation → dispatch → informative viewpoint
→ uncertainty resolution. VLM reasoning을 작은 onboard model로 distill해 cloud 없이 동작.
저자 보고: cloud VLM 대비 occlusion segmentation +25%, robot allocation +36%, per-frame latency
약 350× 감소. 실제 Spot + DJI 항공 플랫폼 + 4,000+ 프레임 데이터 공개.

이미 겹치는 부분: "정보 부족 → 적절한 heterogeneous robot 선택 → 재관측"은 Co-GLANCE가 이미
한다 — 신규성으로 주장하면 안 된다. 남는 차이는 Co-GLANCE가 주로 occlusion uncertainty →
robot/viewpoint selection인 반면, 이 프로젝트는 "shape/color/material/geometry 중 무엇이
부족한가"라는 evidence-type specialization이라는 점이다. 프로젝트 페이지의 `Code` 링크는 method
구현이 아니라 website/dataset viewer repository로 연결된다는 점도 주의.

## 11. Blind Spot + Unknown 탐색에는 SCOUT가 가장 개념적으로 가까움

posed RGB-D + prior map → uncertainty-aware 3D scene graph → geometry/open-vocab label posterior
→ viewpoint selection. 점수 = Semantic Certainty Gain + Geometric Coverage Gain − Travel Cost.
현재 arXiv이며 공식 구현 미확인.

## 12. 지금 직접 구현할 active mapping은 ROAM이 더 적합

ROAM(IEEE T-RO 2025)은 실제 코드가 있고, 여러 robot이 depth+semantic segmentation으로 분산
semantic OctoMap을 만들며 중앙 mapping/planning 노드 없이 동작한다. x86-64와 ARM 공식 지원.

```text
Blind Region → active exploration            (ROAM 구현 기준)
Semantic Unknown → evidence-specific 재관측    (별도 확장)
```

## 13. Capability Registry/선택은 최신 연구가 따로 있음

Semantic Feasibility Reasoning for Heterogeneous Multi-Robot Task Allocation(2026-08, MDPI)은
robot/task/place의 capability를 ontology로 표현하고, 여러 allocator가 공유할 수 있는
`ReasonerOutput`을 만든다 — capability filtering과 최종 optimization을 분리하는 아이디어는
그대로 가져올 만하다(현재 `registry/capability_registry.py` + `selection/selector.py` 구조와
정확히 같은 분리). 학습형 heterogeneous coordination이 필요해지면 CASH(CoRL 2025, 공식 코드
있음)가 robot capability를 명시적으로 encode해 unseen robot/team composition에 zero-shot
generalization을 목표로 한다.

## 14. Camera Calibration은 AnyCalib부터

AnyCalib(ICCV 2025)은 특정 camera model에 고정되지 않고 하나의 이미지에서 calibration을
추정하며 pinhole/Brown-Conrady/Kannala-Brandt/UCM/EUCM/division model을 지원한다. 공식
weights/inference/evaluation/training 코드 공개, Apache 2.0. Pi에서 상시 실행하지 말고
Calibration Lifecycle Provider로 edge/server에서 실행한다(이미 `edge/calibration.py`가 그
경계를 갖고 있음 — AnyCalib은 그 안의 교체 가능한 provider 후보).

## 15. 여러 고정 카메라의 자원 관리에는 OctoCross가 더 직접적

OctoCross는 여러 카메라의 spatial/temporal workload dynamics를 학습해 request를 어디로
offload할지 결정한다. 저자 보고: baseline 대비 최대 5.8× throughput, 3.2× 낮은 latency.
PipelineScheduler repository의 OctoCross branch에 구현이 있다. "Fixed Camera A/B/C Pi 중
어느 inference를 local/edge로 보낼 것인가"를 연구할 때 ApproxDet보다 직접적인 baseline이다.

## 16. Edge GPU serving은 OCTOPINF

같은 연구팀의 OCTOPINF(PerCom 2025, 이미 `OctopinfPlacementPolicy`로 재현됨)는 fine-grained
GPU resource allocation, adaptive batching, edge/server workload balancing, spatiotemporal
scheduling, SLO compliance를 제공한다. 최대 10× effective throughput 보고. PipelineScheduler
전체 구현(Controller, Device Agent, Inference Container, profiler, runtime metric)이 상세히
공개돼 있어 Provider execution manager 구조 참고 가치가 크다. 다만 구현이 Docker/TensorRT/
NVIDIA 중심이므로 상위 Capability API를 거기 종속시키면 안 된다.

## 17. 지속학습은 DGS를 1순위로

DGS(CVPR 2026 Highlight, 이미 `continual/dgs.py`로 재현됨)는 class-incremental만이 아니라
class + domain shift를 함께 다룬다(Dynamic Group Subspace, task distribution grouping, adapter
consolidation, LoRA/Adapter/MoE, stability-adaptivity balance). "새로운 물체 + 새로운 카메라
환경"이 같이 발생하는 이 프로젝트 특성상 단순 incremental class learning보다 적합하다.

## 18. Catastrophic forgetting 비교에는 P²IOD도 추가

P²IOD(CVPR 2026)는 old/new class co-occurrence로 인한 prompt confusion을 다룬다. 공식
repository에 Deformable DETR/Co-DETR 기반 두 구현. 지속학습은 `DGS vs P²IOD` 정도면 충분하다.

## 19. 학습과 실시간 인지가 GPU를 경쟁할 때는 Ekya

Ekya(NSDI 2022, 이미 `continual/ekya.py`로 재현됨)는 오래됐지만 여전히 직접적이다.
micro-profiling으로 학습 job의 가치를 추정하고 Thief Scheduler로 자원을 재배치한다. DGS는
"어떻게 학습하나", Ekya는 "학습과 운영 자원을 어떻게 나누나"로 역할을 분리한다.

## 20. 드론+사족보행을 실제 장비 전에 검증하려면 HERCULES

HERCULES(2026)는 Unreal Engine 5 기반 heterogeneous UAV–UGV simulator다. UAV+UGV concurrent
operation, collaborative SLAM/perception, exploration, unified waypoint interface, synchronized
multi-robot sensor logging을 지원하며 공식 MIT 코드 공개.

## 21. 실제 구현 시 선정할 Reference Stack

전부 SOTA로 채우는 것은 권하지 않는다 — 최신 모델이 곧 구현에 적합한 모델은 아니다.

| 기능 | 실제 구현 1차 | 강한 비교군 |
|---|---|---|
| Pi5 Known/Unknown | Sato OSOD | YOLO-UniOW-S |
| Local Track | ByteTrack | COVTrack |
| Cross-camera identity | GMT 구조 | 기존 two-stage MCMT |
| Async compensation | Timestamp+Kalman → TraF-Align | CATNet |
| Persistent Evidence | 기존 프레임워크 구조 (`object_record.py`) | COVTrack multi-cue 방식 |
| Blind-region exploration | ROAM | SCOUT |
| Heterogeneous dispatch | Capability feasibility rule | CASH / Co-GLANCE |
| Calibration | AnyCalib | GeoCalib |
| Cross-camera resource | OctoCross | ApproxDet/DACC |
| Edge serving | OCTOPINF | static/FIFO |
| Continual detection | DGS | P²IOD |
| Training scheduling | Ekya | fixed allocation |
| Simulation | HERCULES | 실제 hardware |

## 22. 구현 순서

1. Sato OSOD를 원 논문 그대로 재현하고 Pi5로 port. YOLO-UniOW-S는 두 번째 Pi 후보, DEUS/IPOW는
   GPU accuracy upper bound로 둔다.
2. Pi5에서 OSOD → ByteTrack → timestamped Observation까지만 완성한다.
3. 고정 카메라 2~3대를 붙이고 GMT의 global-trajectory 아이디어를 참고한 cross-view association을
   구현한다.
4. 비동기 문제는 `No compensation → timestamp → Kalman propagation → TraF-Align` 순서로 올린다.
   처음부터 CATNet 전체를 복제할 이유는 없다.
5. Zone Persistent Object에서 `unknown / missing evidence / blind region`을 만들고, ROAM의
   uncertainty-driven exploration과 Semantic Feasibility Reasoning의 capability filter로 이동형
   Task를 생성한다.
6. Co-GLANCE를 직접 경쟁 baseline으로 놓고 homogeneous robot allocation과 비교한다. 그 위에
   `shape/color/material/geometry`처럼 evidence type별 Capability specialization을 하나씩
   추가한다.
7. Provider가 늘어난 뒤에만 OctoCross/OCTOPINF를 붙여 실행 위치와 자원을 최적화한다.
8. 마지막에 persistent unknown/user confirmation을 `DGS/P²IOD → validation → deployment`로
   연결하고, 학습이 운영 inference를 방해하는 정도는 Ekya 방식으로 비교한다.

이 순서라면 각 단계가 독립적으로 동작하고, 이전 단계의 결과를 얼린 채 다음 연구 아이디어 하나만
추가할 수 있다.

## 23. 특히 주의할 최신 경쟁 연구

겹침이 큰 순서: **Co-GLANCE → SCOUT → DisCo → GMT → OctoCross**.

- Co-GLANCE 때문에 "불확실하면 적절한 heterogeneous robot을 보낸다"는 주장 자체는 이미
  차별점이 아니다.
- SCOUT 때문에 "semantic uncertainty와 blind area를 기준으로 재관측한다"도 단독 novelty가
  약하다.
- DisCo 때문에 "서로 다른 sensor 구성의 agent가 join/leave하며 fusion한다" 역시 독립
  contribution으로는 위험하다.

현재 가장 살아남는 연구 차이:

> Always-on fixed-camera OWOD로 만든 persistent unknown/object state를 기준으로, 현재 부족한
> evidence type을 명시적으로 판별하고, 해당 evidence capability에 특화된 heterogeneous mobile
> agent/provider만 선택적으로 호출하며, 각각의 결과를 독립 provenance를 가진 Evidence로
> 누적하는 구조.

```text
Persistent Object → Missing Evidence Type → Required Capability → Provider/Robot → Evidence
```

를 연구 중심으로 유지한다.

**주의**: 최신 논문과 GitHub 공개 상태가 빠르게 변하는 분야다. 특히 Co-GLANCE method code,
DisCo code, CATNet code, DEUS code, SCOUT code 공개 여부는 계속 재확인할 가치가 있다 — 아래
개별 논문 노트의 "공식 구현" 절이 이 문서보다 최신 진실이다.
