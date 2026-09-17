# TraF-Align: Trajectory-aware Feature Alignment for Asynchronous Multi-agent Perception

## 메타데이터
- categories: Feature-level Trajectory Field Prediction, Deformable Sampling-position Attention, [[Asynchronous BEV Feature Fusion]], [[Cooperative Perception Latency Robustness]]
- domain: [[협력 인지]]
- source: Song, Zhiying, Yang, Lei, Wen, Fuxi, Li, Jun. "TraF-Align: Trajectory-aware Feature Alignment for Asynchronous Multi-agent Perception." Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2025, pp. 12048-12057.
- url: https://arxiv.org/abs/2503.19391 (code: https://github.com/zhyingS/TraF-Align)
- year: 2025
- authors: Zhiying Song, Lei Yang, Fuxi Wen, Jun Li (Tsinghua University 계열 저자 추정, arXiv 메타데이터 기준)
- venue: CVPR 2025

## 1. 핵심 요약
- 협력 인지에서 에이전트 간 latency는 공간적(spatial)·의미적(semantic) feature 정합을 동시에 깨뜨리는데, TraF-Align은 이를 "과거 관측으로부터 ego 현재 시점까지의 feature-level object trajectory"를 예측해 해결한다. 원문: "predicting the feature-level trajectory of objects from past observations up to the ego vehicle's current time."
- 메커니즘은 **feature map 자체를 warp/재합성하지 않는다.** 대신 예측된 trajectory를 따라 "시간순으로 정렬된 샘플링 지점(temporally ordered sampling points)"을 생성하고, 현재 시점 query가 그 지점들의 원본(미변형) feature를 attention으로 읽어와 현재 시점 feature를 재구성한다. 코드로 직접 확인한 구현은 U-Net 기반 `FieldPredictor`(pixel별 position/orientation field 산출) → `OffsetGenerator`(pixel당 kernel×kernel×heads개의 정수 오프셋 산출) → `offset_to_att_indice`(오프셋을 반올림해 flat pixel index로 변환) → `TrafalignTransformer`(그 정수 index들에서 K/V를 gather해 Q와 scaled-dot-product attention) 순서다.
- 공식 코드는 README의 Acknowledgment에서 "TraF-Align is build upon [OpenCOOD]"라고 명시하며, 실제로 `models/`(attfuse.py, cobevt.py, fcooper.py, v2vnet.py, v2xvit.py, where2comm.py 등 OpenCOOD 표준 baseline 구현), `datasets/intermediate_fusion_dataset.py`, yaml 기반 설정 구조가 OpenCOOD의 관례를 그대로 따른다. **동료의 주장대로 OpenCOOD 기반이 맞다** — 이는 자율주행 V2V/V2I LiDAR 협력 인지용 코드베이스이며, 고정형 CCTV bbox 세팅에 그대로 꽂아 쓸 수 있는 general-purpose perception 라이브러리가 아니라는 실무적 한계를 뒷받침한다.
- 평가는 V2V4Real, DAIR-V2X-Seq 두 실제(real-world) 데이터셋에서 수행했으며(OPV2V, V2X-Sim은 논문·리포에 등장하지 않음), 400ms latency에서 AP50 하락폭이 각각 4.87%p(V2V4Real), 5.68%p(DAIR-V2X-Seq)에 불과해 AttFuse/F-Cooper/V2VNet/Where2comm/V2X-ViT/MRCNet/CoBEVT/ERMVP 등 baseline보다 우수함을 보였다.

## 2. 문서 목적
- 해결하려는 문제: 서로 다른 에이전트의 BEV feature가 처리·통신 지연으로 인해 서로 다른 timestamp를 갖게 되면서 발생하는 공간·의미 정합 오류. 원문: "Latencies cause misalignments in both spatial and semantic features, complicating the fusion of real-time observations from the ego vehicle with delayed data from others."
- 기술적 목표: 정렬된 feature map을 명시적으로 합성(warping)하지 않으면서도, 객체의 운동을 feature 공간에서 명시적으로(trajectory 형태로) 표현해 attention이 올바른 과거 위치를 참조하게 만드는 것. 원문: "By generating temporally ordered sampling points along these paths, TraF-Align directs attention from the current-time query to relevant historical features along each trajectory."
- 다루는 범위: position/orientation field로 표현되는 trajectory field의 예측과 그 GT 구성 방법, kernel 기반 offset 생성과 정수 index로의 변환, TrafalignTransformer의 attention 구조, ego/cav 각각의 다중 과거 프레임 활용, V2V4Real·DAIR-V2X-Seq에서의 latency별 3D detection 성능과 ablation(Field Predictor/Offset Generator/Attention Layer 단계적 추가).

## 3. 핵심 개념 상세

### Feature-level Trajectory Field (Position Field + Orientation Field)
- 원문 표현(코드 기반 확인): position field는 "heatmap peaks along the object's trajectory"이고 orientation field는 "the inverse tangent direction of the trajectory"를 담는다. GT는 시간 윈도우 내 여러 프레임의 박스 중심을 "connecting the centers of these bounding boxes"로 이어 만든 궤적을 BEV feature 공간에 보간·투영해 구성한다.
- 구현: `models/modules/deform/field_predictor.py`의 `FieldPredictor`는 작은 U-Net(DoubleConv/Down/Down/Up/Up/OutConv)으로 backbone feature(x)를 받아 `field_dim`(V2V4Real 설정에서 3채널 — position 1 + orientation 2로 추정) 크기의 필드를 Sigmoid 정규화해 출력한다.
- 역할: "trajectory"는 사전에 고정된 광학 흐름(flow)이 아니라, 다중 과거 프레임을 입력으로 받은 CNN이 픽셀 단위로 회귀한 궤적 히트맵/방향이다. GT 자체가 여러 프레임의 박스 중심을 잇는 궤적이므로, LRCP의 "GT flow = 객체 ID 추적 + 박스 간 상대 변환"과 지도(supervision) 소스의 성격은 유사하다.

### Offset Generator + 정수 인덱스 기반 Sampling Position (핵심 메커니즘)
- 구현(`offset_generator.py`): 3×3 conv 2개로 구성된 소형 헤드가 trajectory field(x_traj)를 입력받아, 픽셀당 `2 × kernel × kernel × heads`개의 오프셋 값을 출력한다(V2V4Real 설정: kernel=3, heads=2 → 픽셀당 2×9×2=36값, 즉 18개의 (dx,dy) 후보 오프셋 = `num_random_points=18`과 일치).
- 구현(`traf_align_fusion.py`의 `offset_to_att_indice`): 예측된 오프셋에 고정된 kernel 앵커 그리드(-(k-1)/2 ~ +(k-1)/2)와 픽셀의 절대 좌표를 더한 뒤 **반올림(round)하고 정수로 clamp**해 `h*w` 범위의 flat pixel index로 변환한다. 즉 연속 좌표에서의 bilinear 보간이 아니라 **정수 격자 인덱스로 gather**하는 방식이다.
- 구현(`trafalign_transformer.py`): 이 정수 index들에서 원본(unwarped) feature map의 K, V를 `torch.gather`로 추출하고, 현재 위치의 Q와 scaled dot-product attention(멀티헤드, learnable position encoding 포함)을 수행해 residual + FFN으로 현재 시점 feature를 갱신한다. 즉 "각 query 위치를 하나의 token으로 취급하고, offset generator가 지정한 위치에만 attention을 국한한다."
- 역할: **feature map을 통째로 새로 합성(warp)하지 않고, attention이 읽어올 위치(sampling position)만 예측된 trajectory로 옮긴다는 점에서 LRCP의 "reference point calibration"과 근본적으로 같은 설계 철학을 공유한다.** 차이는 (i) LRCP는 deformable attention의 연속 좌표 reference point(p_n = p'_n + flow_n, 통상 bilinear sampling)를 단일 예측 flow 벡터로 이동시키는 반면, TraF-Align은 픽셀당 kernel×kernel개의 discrete 후보 오프셋을 생성해 정수 인덱스로 반올림한 뒤 다중 후보 위치에 대해 attention으로 가중합한다는 점, (ii) LRCP는 비이산(non-discrete) latency 스칼라 τ_n을 sinusoidal encoding으로 조건화한 별도 flow-prediction 모듈이 "에이전트 하나당 flow map 하나"를 예측하는 구조인 반면, TraF-Align은 latency를 채널에 더해지는 sinusoidal temporal embedding으로 각 과거 프레임(ego 2프레임, cav 4프레임)에 주입한 뒤 U-Net이 다중 프레임을 함께 보고 trajectory field를 직접 회귀한다는 점이다.

### Multi-frame Temporal Embedding과 Ego/Cav 프레임 구성
- 원문(코드 확인, `v2v4real_Trafalign.yaml`): `frame_his: 2`(ego 과거 프레임 수), `cav_frame_his: 4`(cav 과거 프레임 수). DAIR-V2X-Seq도 유사하게 다중 프레임을 사용(ego/infra 각각 설정).
- 구현(`get_temporal_features`): 각 프레임에 (프레임 인덱스 + 해당 에이전트의 delay)를 결합한 sinusoidal 위치 인코딩을 feature 채널에 concat하고, `tfn_layer`(1×1 conv 2개)로 다시 원래 채널 수로 투영한다. 포인트가 존재하는 복셀 위치에만 이 시간 임베딩이 곱해진다(mask 적용).
- 역할: 각 에이전트가 "몇 프레임 전 데이터를 보냈는지"를 시간 임베딩으로 명시해, FieldPredictor가 이산적인 다중 프레임 스택으로부터 연속적인 궤적을 추정할 수 있게 한다. LRCP의 "cached k=5 feature + 연속 latency τ를 별도 조건으로 주는" 방식과 달리, TraF-Align은 latency 정보를 프레임별 임베딩으로 각 프레임 feature 자체에 흡수시킨다.

### Warping 방식과의 명시적 대조 (CoBEVFlow)
- 원문(코드/논문 확인): CoBEVFlow는 "extracts and warps object-specific features to anticipated locations by predicting instance-wise motion vectors"하지만 "generating ROIs and tracking their motion, resulting in a non-end-to-end two-stage method"라는 한계가 있다고 명시한다. TraF-Align은 "by operating directly at the feature level, our approach enables end-to-end training and avoids the complexities of high-dimensional feature prediction."
- 역할: TraF-Align 저자들 스스로도 "feature map을 새로 warp/재합성하는 대신 원본 feature에서 올바른 위치를 attention으로 골라 읽는다"는 설계를 CoBEVFlow 대비 핵심 차별점으로 서술한다 — 이는 LRCP가 CoBEVFlow류 warping을 ablation(Fig. 7b)으로 직접 반박한 것과 같은 방향의 논증이다.

## 4. 구조 및 흐름
1. **Feature encoding**: 각 에이전트의 LiDAR point cloud를 `PillarFeatureNet`(PointPillars 계열 pillar encoder)으로 인코딩하고, 희소 ResNet(`SparseResNet`, spconv 기반)을 backbone으로 사용해 BEV feature를 얻는다.
2. **Regroup + 시간 임베딩**: ego의 과거 `frame_his`개 프레임과 cav의 과거 `cav_frame_his`개 프레임을 분리해 쌓고, 존재 시 sinusoidal 시간 임베딩을 채널에 주입한다.
3. **Trajectory Field 예측**: `FieldPredictor`(소형 U-Net)가 stacked feature로부터 position/orientation field(x_traj)를 회귀한다.
4. **Offset 생성·정수 인덱스 변환**: `OffsetGenerator`가 x_traj로부터 픽셀당 다중(kernel×kernel×heads) 오프셋을 예측하고, 고정 앵커 그리드와 결합해 반올림한 flat pixel index(선택된 attention 위치)로 변환한다.
5. **Trajectory-guided Attention**: `TrafalignTransformer`(멀티헤드, 2 layer, learnable position encoding)가 원본 feature map에서 선택된 index들의 K/V를 gather해 현재 위치 Q와 attention을 수행, 현재 시점 feature를 재구성한다.
6. **Cross-agent Fusion**: 여러 에이전트(ego+cav)의 재구성된 feature를 채널 concat 후 conv(또는 max) fusion으로 합친다.
7. **Detection Head**: ASPP neck과 anchor/center head를 거쳐 3D detection 결과(dets)를 출력한다.
8. **평가**: V2V4Real(V2V, urban), DAIR-V2X-Seq(V2I, 교차로)에서 0~400ms latency 구간에 대해 AP50/AP70으로 AttFuse, F-Cooper, V2VNet, Where2comm, V2X-ViT, MRCNet, CoBEVT, ERMVP와 비교하고, Field Predictor/Offset Generator/Attention Layer를 단계적으로 추가하는 ablation을 수행한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| TraF-Align은 넓은 latency 범위에서 AP 하락폭이 매우 작다 | V2V4Real: AP50/AP70 74.28/44.14(0ms) → 69.41/38.49(400ms), AP50 하락폭 4.87%p. DAIR-V2X-Seq: 76.90/58.31(0ms) → 71.22/52.01(400ms), AP50 하락폭 5.68%p. (수치는 arXiv HTML 버전 본문 Table 1에서 직접 확인) |
| 동일 조건에서 기존 SOTA(ERMVP)보다 모든 latency 구간에서 우수하다 | V2V4Real 400ms: TraF-Align 69.41/38.49 vs ERMVP 57.26/29.31(AP50 12.15%p, AP70 9.18%p 차이). DAIR-V2X-Seq 400ms: TraF-Align 71.22/52.01 vs ERMVP 59.55/43.93(AP50 11.67%p, AP70 8.08%p 차이). AttFuse/F-Cooper/V2VNet/Where2comm/V2X-ViT/MRCNet/CoBEVT도 모두 TraF-Align보다 낮음(V2V4Real 0ms 기준 AttFuse 63.84/33.30 ~ CoBEVT 70.59/38.82). |
| Field Predictor(FP)·Offset Generator(OG)·Attention Layer(AL)를 단계적으로 추가할수록 성능이 일관되게 향상된다 | DAIR-V2X-Seq 인프라 latency 기준(ablation Table 2): baseline 75.35/54.72(0ms)→70.09/49.45(400ms), +FP 76.31/57.02→71.84/51.02, +OG 77.11/58.63→71.96/52.19, Full(+AL) 77.83/59.72→72.89/53.21. latency가 커질수록 각 구성요소 추가의 이득이 더 커지는 경향을 보인다. |
| Feature map을 warp/재합성하지 않고 원본에서 올바른 위치를 attention으로 읽는 방식이 CoBEVFlow류 warping보다 구조적으로 유리하다 | 원문: CoBEVFlow는 "generating ROIs and tracking their motion, resulting in a non-end-to-end two-stage method"인 반면 TraF-Align은 "operating directly at the feature level ... enables end-to-end training and avoids the complexities of high-dimensional feature prediction." (단, 이 논문은 LRCP처럼 자체 ablation으로 "우리 방식 vs 직접 warping"을 수치로 직접 비교하는 실험은 본문에서 확인되지 않았고, CoBEVFlow는 baseline 표가 아니라 서술로만 대조된다.) |

## 6. LRCP와의 명시적 비교 (같은 프레임워크의 temporal_alignment.py가 참고한 비동기 융합 계열)

| 항목 | LRCP (WACV 2025) | TraF-Align (CVPR 2025) |
|------|-------------------|--------------------------|
| feature map 변형 여부 | 원본 stale feature map은 그대로 두고, deformable attention의 **reference point만 이동**(p_n = p'_n + flow_n). Warping은 ablation에서 명시적으로 더 나쁨(2.5%p 하락)을 실측. | 원본 feature map은 그대로 두고, **attention이 참조하는 정수 pixel index만 이동**(offset_to_att_indice). CoBEVFlow의 warping을 서술적으로 열등하다고 주장하나, "warping 대체 실험"을 자체 ablation 수치로 직접 제시하지는 않음. |
| 예측 대상의 표현 | 에이전트당 하나의 dense 2D flow map(H×W×2), 비이산 latency τ_n을 sinusoidal encoding으로 별도 조건화. | 픽셀당 position field(히트맵形) + orientation field, 그리고 픽셀당 kernel×kernel×heads개의 discrete 후보 오프셋. latency는 프레임별 시간 임베딩으로 feature 채널에 흡수. |
| 샘플링 방식 | 연속 좌표 기반 deformable attention (표준적으로 bilinear sampling). | 오프셋을 **반올림·clamp해 정수 index로 gather** — bilinear 보간 없이 이산 위치에서 직접 읽음. |
| 입력 이력 | cached 과거 k(기본 5)개 BEV feature + 연속 latency 스칼라. | ego 과거 2프레임, cav 과거 4프레임(설정값, 데이터셋별 상이)을 시간 임베딩과 함께 stack. |
| GT 지도(supervision) | 객체 ID 추적 + 박스 간 상대 변환(Δx,Δy,Δθ)으로 GT flow 생성, 2단계 학습(먼저 detection, 이후 flow 모듈만 학습). | 다중 프레임 박스 중심을 이은 궤적을 보간·투영해 position/orientation field GT 생성(학습 단계 분리 여부는 코드에서 별도 확인되지 않음, 통합 학습으로 보임). |
| 평가 데이터셋 | V2X-Sim(시뮬레이션), DAIR-V2X(실제) — LiDAR 3D detection, PointPillars+ResNet. | V2V4Real(실제), DAIR-V2X-Seq(실제) — LiDAR 3D detection, PointPillars 계열 pillar encoder + SparseResNet. |
| 코드베이스 | 자체 구현(https://github.com/JesseWong333/LRCP), OpenCOOD 명시적 언급 없음. | **OpenCOOD 기반**(README Acknowledgment에서 명시), baseline 모델 파일명(attfuse.py, v2vnet.py 등)이 OpenCOOD 표준 구성과 동일. |
| 공통점 | 둘 다 "새 aligned feature map을 합성하지 않고, 원본 feature에서 읽어올 위치(reference point/attention index)만 예측된 운동으로 이동시킨다"는 동일한 상위 설계 철학을 공유하며, 두 논문 모두 이 선택이 warping 기반 방법(SyncNet 계열/CoBEVFlow)보다 노이즈·오차 누적이 적다고 주장한다. |

## 7. 한계 및 부족한 점
- 본문은 arXiv HTML(v1, https://arxiv.org/html/2503.19391v1)과 GitHub 공식 리포지토리(zhyingS/TraF-Align, master 브랜치의 Readme.md 및 `models/`, `datasets/`, `hypes_yaml/` 소스 코드)를 직접 열람해 확인했다. CVF Open Access의 공식 PDF는 403으로 직접 열람하지 못해 arXiv 버전과 GitHub 코드로 교차 검증했다.
- **OpenCOOD 의존성의 실무적 함의**: README는 "Following OpenCOOD, TraF-Align uses yaml file to configure all the parameters for training"라고 명시하고, `datasets/intermediate_fusion_dataset.py`·`datasets/Basedataset/`·`models/`의 baseline 구현(attfuse.py, cobevt.py, fcooper.py, mrcnet.py, v2vnet.py, v2xvit.py, where2comm.py, ermvp.py)이 OpenCOOD의 표준 협력 인지 벤치마크 구조를 그대로 따른다. 즉 이 코드베이스는 **차량-차량/차량-인프라 LiDAR 포인트클라우드 입력, BEV 3D detection, 다중 차량 pose·delay 메타데이터를 전제로 설계된 자율주행 협력 인지 프레임워크**이며, 동료가 지적한 대로 "고정형 CCTV bbox 세팅"(단일·고정 카메라, 이미지 평면 bbox, LiDAR/pose 메타데이터 부재)에 그대로 재사용할 수 있는 general-purpose 모듈이 아니다. 재사용하려면 (i) LiDAR pillar encoder를 이미지/BEV-projected feature encoder로 교체, (ii) OpenCOOD의 pose·delay 기반 다중 에이전트 데이터 로더를 고정 카메라 시점 간 시간 지연 구조로 재작성, (iii) 박스 중심 궤적 기반 GT field 생성 로직을 CCTV 환경의 tracking GT로 재구성해야 한다.
- 저자들은 본문에서 "CoBEVFlow 대비 end-to-end라서 유리하다"고 서술하지만, LRCP처럼 "동일 예측 정보로 warping만 했을 때"를 직접 수치로 비교하는 ablation은 arXiv HTML에서 확인한 범위 내에서 발견되지 않았다 — 즉 warping 대비 우위는 CoBEVFlow라는 별도 baseline과의 간접 비교(Table 1)에 의존하며, LRCP의 Fig. 7b처럼 "같은 프레임워크에서 warping 모듈만 교체"한 통제 실험은 아니다.
- 확인한 범위 내에서 latency-robustness 외의 통신 대역폭·pose noise·privacy 관련 논의, 그리고 추론 속도(FPS)·연산량 비교는 본문에서 확인되지 않았다(WebFetch 요약 기준 "No inference latency or runtime speed comparisons are provided").
- 평가 데이터셋이 V2V4Real·DAIR-V2X-Seq 두 개로 한정되며, OPV2V·V2X-Sim 등 시뮬레이션 데이터셋에서의 결과는 확인되지 않았다(LRCP는 반대로 V2X-Sim·DAIR-V2X를 사용해 데이터셋 구성이 겹치지 않는다 — 직접적인 동일 데이터셋 수치 비교는 불가능하다).
- offset이 정수로 반올림(round)·clamp되는 구현은 gradient가 offset 예측 자체에 대해 straight-through 방식으로만 흐를 가능성이 있으나, 이 세부 학습 메커니즘(backward 경로)은 공개 코드 스니펫만으로는 완전히 확정하지 못했다 — 학습 코드(`tools/train.py`, loss 정의)까지 추가로 확인해야 완전히 검증 가능하다.

## 8. 원문 기반 핵심 문장
> "we propose TraF-Align, a novel framework that learns the flow path of features by predicting the feature-level trajectory of objects from past observations up to the ego vehicle's current time. By generating temporally ordered sampling points along these paths, TraF-Align directs attention from the current-time query to relevant historical features along each trajectory, supporting the reconstruction of current-time features and promoting semantic interaction across multiple frames."

> "Experiments on two real-world datasets, V2V4Real and DAIR-V2X-Seq, show that TraF-Align sets a new benchmark for asynchronous cooperative perception, with minimal average precision (AP50) drops of only 4.87% and 5.68% at 400 ms latency on the two datasets, respectively."

> (GitHub README, Acknowledgment) "TraF-Align is build upon [OpenCOOD](https://github.com/DerrickXuNu/OpenCOOD), many thanks to the high-quality codebase." / "Following OpenCOOD, TraF-Align uses yaml file to configure all the parameters for training."

> "by operating directly at the feature level, our approach enables end-to-end training and avoids the complexities of high-dimensional feature prediction." (CoBEVFlow의 "extracts and warps object-specific features ... resulting in a non-end-to-end two-stage method"와 대조하는 문맥)
