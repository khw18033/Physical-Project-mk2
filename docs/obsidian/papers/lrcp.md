# LRCP: Latency Robust Cooperative Perception using Asynchronous Feature Fusion

## 메타데이터
- categories: Flow Prediction Module, Deformable Attention Reference Point Calibration, [[Asynchronous BEV Feature Fusion]], [[Cooperative Perception Latency Robustness]]
- domain: [[협력 인지]]
- source: Wang, Junjie, Nordström, Tomas. "Latency Robust Cooperative Perception using Asynchronous Feature Fusion." Proceedings of the IEEE/CVF Winter Conference on Applications of Computer Vision (WACV), 2025, pp. 4862-4871.
- url: https://openaccess.thecvf.com/content/WACV2025/html/Wang_Latency_Robust_Cooperative_Perception_using_Asynchronous_Feature_Fusion_WACV_2025_paper.html
- year: 2025
- authors: Junjie Wang, Tomas Nordström (Department of Applied Physics and Electronics, Umeå University; RISE Research Institutes of Sweden)
- venue: WACV 2025 (Winter Conference on Applications of Computer Vision)

## 1. 핵심 요약
- 협력 인지(cooperative perception)에서 서로 다른 에이전트가 보낸 BEV(bird's-eye view) feature는 처리·통신 지연으로 timestamp가 어긋나는데, 기존 방법은 명시적 motion 표현이 없거나(V2X-ViT, SyncNet) flow로 정렬된 feature map을 새로 생성하는 과정에서 오차가 누적되는(CoBevFlow) 한계가 있었다.
- LRCP는 정렬된(aligned) feature map을 별도로 생성하지 않고, cached된 과거 BEV feature들과 latency 값을 입력받는 **flow prediction module**로 비이산(non-discrete) 시간 간격의 flow를 예측한 뒤, 이 flow로 deformable attention의 **reference point를 보정(calibration)**해 비동기 feature를 직접(directly) fusion한다.
- V2X-Sim, DAIR-V2X 두 공개 데이터셋에서 0~500/600ms 범위의 latency에 대해 강건성을 검증했고, 500ms(DAIR-V2X 기준)에서 latency 없는 이상적 상황 대비 AP@0.5는 1%p, AP@0.7은 4%p 이내로만 성능이 저하됨을 보였다.
- Feature encoder는 ResNet backbone을 얹은 PointPillars이며, LiDAR 포인트클라우드 입력 기반 3D object detection 태스크로 평가했다. 코드는 https://github.com/JesseWong333/LRCP 에 공개.

## 2. 문서 목적
- 해결하려는 문제: 협력 인지 시스템에서 에이전트 간 데이터 처리·통신 지연으로 서로 다른 timestamp의 BEV feature를 fusion해야 하는 temporal asynchrony 문제. 저자들은 기존 방법의 두 가지 한계를 지적한다 — "1) the absence of explicit motion representation between frames and 2) the potential accumulation of errors."
- 기술적 목표: 정렬된 feature map을 별도로 합성(생성)하는 중간 단계 없이, 비동기 BEV feature를 직접 fusion하면서도 동작(motion)을 명시적으로 모델링하는 latency-robust 프레임워크를 설계하는 것. 핵심 아이디어는 "to directly fuse asynchronous BEV feature maps instead of estimating temporally aligned feature maps."
- 다루는 범위: temporal asynchrony의 수식적 정의, deformable attention 기반 fusion decoder의 reference point calibration 메커니즘, 비이산 시간 latency를 인코딩하는 flow prediction module 설계, 2단계 학습 스킴, V2X-Sim/DAIR-V2X에서의 latency별 3D detection 성능 비교와 ablation, 속도별 객체에 대한 보정 성능(부록).

## 3. 핵심 개념 상세

### Temporal Asynchrony의 정식화
- 원문 표현: "the latency τn is non-discrete as the sampling timestamps of different agents are not aligned. The latency τn in our experiments can vary from a minimal delay of less than 100 ms to a maximum of 500 ms."
- 정의: 에이전트 n이 timestamp t_n에 얻은 feature F^{t_n}_n을 ego 좌표계로 projection한 F'^{t_n}_n을 ego의 현재 시점 t와 비교했을 때의 시간차 τn. 각 에이전트의 프레임 간격은 고정(sensor sampling rate)이지만 에이전트 간 timestamp는 정렬되어 있지 않아 τn 자체는 이산적이지 않다.
- 역할: 논문 전체의 문제 설정을 수식(Eq. 1~4)으로 고정한다. 특히 "no latency 이상적 상황" 대비 성능 저하를 측정하는 모든 실험의 기준이 되는 정의다.

### Deformable Attention 기반 Fusion Decoder
- 원문 표현: "Deformable operators predefine a set of reference points and predict offsets to augment the spatial sampling locations. The offsets are learned based on the target tasks ... in an end-to-end manner, with no additional supervision required."
- 정의: BEV query가 각 agent feature map 위의 reference point 주변에서 학습된 offset만큼 이동한 위치를 샘플링(cross-attention)해 정보를 모으는 연산(Eq. 5). LRCP는 이 decoder를 4개의 deformable cross-attention layer + 2개의 deformable self-attention layer로 쌓는다(8 head, 8 sampling point).
- 역할: LRCP의 fusion 백본 자체이며, "Deformable attention" 단독(= reference point calibration 없이)만으로도 latency=0에서 SOTA 성능을 낼 만큼 강력한 baseline이라고 논문은 명시한다. LRCP의 기여는 이 decoder에 무엇을 추가하느냐(=reference point calibration)에 있다.

### Reference Point Calibration (LRCP의 핵심 메커니즘)
- 원문 표현: "For the received feature F'^{t-τn}_{n,n≠ego} from a non-ego agent, we calibrate the reference points p_n to align feature maps from different timestamps. ... flow_n = f_calibrate(F^{t-τn,...,t-τn-k-1}_n, τn); p_n = p'_n + flow_n."
- 정의: non-ego 에이전트로부터 받은, 여전히 과거(비동기) 시점 그대로인 feature map F'^{t-τn}_n 자체는 건드리지 않고, 그 feature map 위에서 deformable attention이 샘플링할 reference point의 위치를 예측된 flow만큼 이동시켜 "옳은" 위치를 가리키도록 만드는 절차다. Ego 에이전트의 reference point는 보정하지 않는다("Reference point calibration is only applied to non-ego agents").
- 역할: **이것이 바로 "정렬된 feature map을 새로 생성하는 대신, 비동기 feature를 직접 fusion한다"는 논문의 핵심 주장을 구현하는 지점이다.** Warping(예: CoBevFlow 방식)처럼 flow로 새로운 aligned feature map을 합성(생성)하는 것이 아니라, 원본 stale feature map에서 attention이 읽어올 위치만 flow로 보정한다. 논문은 이 차이가 노이즈·오차 누적을 줄인다고 주장하며, ablation(Fig. 7b)에서 동일한 예측 flow로 "warping"만 했을 때는 LRCP 대비 2.5%p 성능이 낮음을 실측으로 보인다.

### Flow Prediction Module
- 원문 표현: "our framework relies on k BEV feature maps F'^{t-τn,...,t-τn-k-1}_n and the latency τn to predict a flow from timestamp t to t-τn ... Unlike MotionNet [28] which employs multiple regression heads for discrete timestamps, this module necessitates predicting flow for any given non-discrete time interval."
- 정의: cached된 과거 k개(기본값 k=5)의 BEV feature map을 프레임 순서를 나타내는 positional encoding과 함께 입력받고, 별도의 학습 가능한 "flow query" 그룹(Q_flow)에 latency τn을 사인/코사인 함수 기반 sinusoidal encoding(Eq. 8, Transformer의 positional encoding과 동일한 형식)으로 주입한 뒤, 3개의 cross-attention layer + 2개의 self-attention layer(기본 설정)로 구성된 deformable attention을 통해 2D flow map(flow_n ∈ R^{bev_h×bev_w×2})을 출력하는 모듈이다.
- 역할: "non-discrete time delay"를 하나의 head로 처리할 수 있게 해 임의의 τn 값에 대해 flow를 예측하며(이산적인 고정 시간 간격만 다루던 MotionNet과 대조), 3D convolution 기반 시간 특징 집계 대비 계산 복잡도를 O(kHWd³C²)에서 O(N_qC² + kHWC²)로 낮춰 효율을 확보한다.

### 2단계 학습 스킴 (Two-stage Training)
- 원문 표현: "Stage 1: ... the flow module remains untrained, and the calibration of reference points ... utilizes the ground truth flow. Stage 2: We maintain the previously trained components ... unchanged, while the flow module is trained under the supervision of the ground truth flow."
- 정의: 1단계에서는 feature encoder·fusion decoder·detection head를 ground-truth flow로 reference point를 보정한 상태에서 검출 태스크로 먼저 학습하고, 2단계에서는 나머지를 고정한 채 flow prediction module만 ground-truth flow supervision으로 학습한다.
- 역할: detection 성능을 먼저 안정화시킨 뒤 flow 예측을 별도로 학습해 수렴을 빠르게 하는 절차적 장치다. V2X-Sim은 원래 flow(motion) 라벨이 없어 논문이 직접 객체 ID 추적 + bounding box 간 상대 변환(Δx, Δy, Δθ)으로 GT flow를 생성했고, DAIR-V2X는 unique track ID가 없어 greedy 추적 + gradient descent 기반 변환 추정으로 GT flow를 만들었다.

## 4. 구조 및 흐름
1. **Feature encoding**: 각 에이전트가 자신의 raw 데이터(LiDAR point cloud)를 ResNet backbone을 얹은 PointPillars로 인코딩해 BEV feature F^{t_n}_n ∈ R^{H×W×C}를 얻고, non-ego feature는 ego 좌표계로 projection된다(F'^{t_n}_n).
2. **BEV query 초기화**: 학습 가능한 grid 형태의 BEV query Q를 초기화하고 positional embedding을 더해 fusion decoder에 입력한다.
3. **Flow prediction**: non-ego 에이전트마다, cached된 과거 k개 feature와 latency τn을 flow prediction module에 넣어 t→t-τn 방향의 2D flow map을 예측한다.
4. **Reference point calibration**: 예측된 flow로 deformable cross-attention의 reference point를 이동시킨다(ego 에이전트는 변경 없음).
5. **Asynchronous fusion decoder**: 보정된 reference point를 사용하는 4개 deformable cross-attention layer(멀티 에이전트 feature 집계) + 2개 deformable self-attention layer(fused BEV feature 정제)를 거쳐 최종 fused BEV feature를 얻는다. Multi-scale feature 전략을 채택해 ResNet의 여러 해상도 feature를 함께 집계한다.
6. **Detection head**: fused BEV feature를 3D object detection head(anchor 기반, [11,22,32,33]과 동일한 head/loss 사용)에 넣어 최종 검출 결과를 산출한다.
7. **평가**: V2X-Sim(latency 0~600ms, 5Hz 기준)과 DAIR-V2X(latency 0~500ms, 10Hz 기준)에서 AP@0.5·AP@0.7로 openv2v, Where2comm, CoBevFlow, SyncNet, V2X-ViT 등과 비교하고, 캐시 프레임 수 k·flow module 레이어 구성·warping과의 비교 등 ablation을 수행한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| LRCP는 넓은 latency 범위(최대 500/600ms)에서 성능 저하가 거의 없다 | "we achieved robust performance across a range of latencies up to 500 ms, with a performance degradation of only 1 percent point for AP@0.5 metric and 4 percent points for AP@0.7 metric at 500 ms." 실측 표(부록 Tab.7, DAIR-V2X): LRCP AP@0.5 80.5(0ms)→79.1(500ms), AP@0.7 69.5(0ms)→66.5(500ms). 반면 순수 Deformable Attn baseline(보정 없음)은 같은 조건에서 AP@0.5 80.9→68.3, AP@0.7 70.1→58.9로 12.6%p/11.3%p 급락한다. |
| Warping 방식으로 정렬된 feature map을 새로 만드는 것보다, reference point를 flow로 직접 보정하는 방식이 더 낫다 | Fig. 7b ablation: 동일한 예측 flow를 "warping with flow"(CoBevFlow류 방식)에 쓰면 LRCP 대비 2.5%p 성능 하락. GT flow로 reference point를 보정한 상한(LRCP with GT flow)과 실제 예측 flow를 쓰는 LRCP의 차이는 0.5%p에 불과해 flow 예측 모듈 자체의 품질도 검증된다. |
| LRCP는 SyncNet류(LSTM 기반 aligned feature 예측)보다 낮은 성능 저하를 보인다 | 본문: "SyncNet [16] employs an LSTM-based model to predict aligned feature maps from cached features. However, both approaches [V2X-ViT, SyncNet] lack the ability to explicitly represent motion between frames." Table 1(공식 구현 기준, 400ms 평균 저하): V2X-ViT 11.9%p, SyncNet 4.5%p, CoBevFlow 9.2%p, How2comm 14.1%p, LRCP 2.3%p. 부록 Table 6/7의 "DeformableAttn+SyncNet"(같은 fusion backbone에 SyncNet 방식만 이식한 fair-comparison baseline)도 고latency에서 LRCP보다 3.8~5.4%p(AP@0.7 기준, 각각 V2X-Sim 600ms·DAIR-V2X 500ms) 낮다. |
| Latency 보정에는 cached 과거 프레임 수와 flow module의 attention layer 구성이 영향을 준다 | Fig. 7a: k(cached frame 수)가 클수록 AP@0.5가 일관되게 향상되어 k=5를 기본값으로 채택. Table 2: flow module에서 순수 self-attention보다 cross+self-attention 조합이 근소하게 우수(3cross+2self가 AP@0.5 79.1/AP@0.7 66.5로 최고, 3cross 단독은 78.6/65.9). |

## 6. 한계 및 부족한 점
- CVF Open Access의 본문 PDF(10페이지, pp.4862-4871)와 supplemental PDF(2페이지, 부록 A~D 포함 상세 latency-AP 표)를 pypdf로 전체 텍스트 추출해 직접 확인했다.
- 저자가 직접 명시한 한계: "V2X communication faces limited bandwidth constraints, while pose estimation for moving agents often introduces noise. ... a disparity remains compared to utilizing ground truth flow, necessitating further exploration into predicting non-discrete timestamp flows. Additionally, emerging concerns regarding privacy and adversarial robustness during data sharing require greater attention, as they have not been thoroughly addressed." — 즉 대역폭 제약, pose 추정 노이즈, GT flow 대비 여전히 남는 격차, 프라이버시/적대적 강건성은 이 논문의 범위 밖이다.
- 부록 Table 3(DAIR-V2X, 속도별 성능)에 따르면 "in extreme scenarios with both high latency and high-speed objects, the compensation performance of LRCP begins to deteriorate" — 매우 빠른 객체(v≥10m/s)이면서 latency도 클 때는 LRCP도 성능 저하를 완전히 막지 못한다(예: AP@0.7이 500ms에서 79.1→58.2로 하락).
- 저자 스스로 "Due to the variation in experimental setups, fair comparisons between methods as described in recent literature are difficult to achieve"라고 인정한다. Table 1의 타 방법 수치는 각기 다른 데이터셋·구현에서 가져온 것이라 완전히 동일 조건 비교는 아니며, 이를 보완하기 위해 저자들은 별도로 "DeformableAttn+SyncNet"(같은 backbone에 SyncNet 방식만 이식) fair-comparison 실험을 부록에 추가했다.
- Flow 예측 자체의 품질 이슈로 "minor inconsistencies within the flow predictions, such as jitters where backgrounds adjacent to objects exhibit unintended motion"이 관찰되며, "Developing strategies to refine flow predictions will be an essential focus of our future work"라고 명시한다.
- 평가는 V2X-Sim(시뮬레이션, V2V만 고려)과 DAIR-V2X(실제, ego-infrastructure 1쌍) 두 데이터셋, 그리고 1-round communication 설정([22,33]과 동일)에 한정되며, 논문이 확인한 범위 내에서 V2I 다중 에이전트나 다중 라운드 통신 조건에서의 일반화는 별도로 검증되지 않는다.

## 7. 원문 기반 핵심 문장
> "The intuition of LRCP is to directly fuse asynchronous bird's-eye view (BEV) features instead of estimating aligned features. To achieve this, we first propose a novel flow prediction module that uses cached past BEV features to predict the flow with a non-discrete time delay at the BEV feature level. Then, the predicted flow is employed to guide the spatial sampling location of interests."

> "We identified two key limitations in existing methods that may hinder compensation performance: 1) the absence of explicit motion representation between frames and 2) the potential accumulation of errors. Encoding delay information, as proposed in [32], does not directly capture motion dynamics ... While estimating aligned BEV features [16] offers a potential solution, it does not explicitly model intrinsic motion and may introduce additional noise to the features."

> "V2X-ViT [32] incorporates delay-aware positional encoding to consider time delay information, while SyncNet [16] employs an LSTM-based model to predict aligned feature maps from cached features. However, both approaches lack the ability to explicitly represent motion between frames."

> "we achieved robust performance across a range of latencies up to 500 ms, with a performance degradation of only 1 percent point for AP@0.5 metric and 4 percent points for AP@0.7 metric at 500 ms on two public datasets (V2X-Sim and Dair-V2X)."
