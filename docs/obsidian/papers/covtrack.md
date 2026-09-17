# COVTrack: Continuous Open-Vocabulary Tracking via Adaptive Multi-Cue Fusion

## 메타데이터
- categories: C-TAO 연속 주석 데이터셋, Intra/Inter-frame Confidence 기반 Multi-Cue Fusion, Self-attentive Gated Network, Cycle-consistency 기반 Inter-frame Confidence
- domain: [[객체 추적]], [[객체 탐지·분할]]
- source: Qian, Zekun, Han, Ruize, Wang, Zhixiang, Hou, Junhui, Feng, Wei. "COVTrack: Continuous Open-Vocabulary Tracking via Adaptive Multi-Cue Fusion." Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), 2025, pp. 10054-10063.
- url: https://openaccess.thecvf.com/content/ICCV2025/html/Qian_COVTrack_Continuous_Open-Vocabulary_Tracking_via_Adaptive_Multi-Cue_Fusion_ICCV_2025_paper.html (PDF: https://openaccess.thecvf.com/content/ICCV2025/papers/Qian_COVTrack_Continuous_Open-Vocabulary_Tracking_via_Adaptive_Multi-Cue_Fusion_ICCV_2025_paper.pdf ; code: https://github.com/zekunqian/COVTrack)
- year: 2025
- authors: Zekun Qian (Tianjin University / City University of Hong Kong), Ruize Han (Shenzhen University of Advanced Technology, 교신저자), Zhixiang Wang (Tianjin University), Junhui Hou (City University of Hong Kong), Wei Feng (Tianjin University)
- venue: IEEE/CVF International Conference on Computer Vision (ICCV) 2025 — 최초 요청 시점의 "ICCV 2025" venue 주장은 논문 원문·공식 CVF Open Access 페이지·GitHub README로 확인됨 (연도·학회 오류 없음)

## 1. 핵심 요약
- Open-Vocabulary Multi-Object Tracking(OVMOT)의 유일한 대규모 학습 데이터셋인 TAO는 30프레임(1fps)마다만 주석이 있어 연속적인 모션·외형 변화를 학습할 수 없다는 문제를 겨냥해, 저자들은 TAO의 모든 프레임을 사람이 재주석한 **C-TAO**(주석 프레임 26배, 박스 27배 증가, 프레임당 평균 IoU 2.2배 증가·픽셀 이동량 101→6.6px로 93.5% 감소)를 구축했다.
- COVTrack은 appearance·location(motion)·semantic 세 cue를 **intra-frame confidence**(같은 프레임 내 cue 간 상호 신뢰도, Self-attentive Gated Network로 산출)와 **inter-frame confidence**(인접 프레임 간 cycle-consistency 기반 자기교정, 프레임 간 유사도 행렬을 이용)라는 두 개의 독립된 신뢰도로 각각 게이팅한 뒤 곱셈으로 결합하는 학습 가능한 융합 프레임워크다.
- TAO open-vocabulary 벤치마크(validation/test)에서 COVTrack은 novel/base TETA 모두에서 SOTA인 SLAck·OVTrack·MASA를 능가한다(validation novel TETA 34.3 vs SLAck 31.1, OVTrack 27.8).
- 공식 GitHub 저장소(zekunqian/COVTrack)는 학습·평가·커스텀 비디오 추론 코드 전체(303개 파일)를 공개했고, 사전학습 가중치와 C-TAO 주석은 HuggingFace(clarkqian/COVTrack, 약 2.4GB)에서 별도 배포한다 — 코드와 가중치가 분리돼 있을 뿐 완결성 자체에는 결손이 없다.

## 2. 문서 목적
- 해결하려는 문제: OVMOT은 base/novel 카테고리를 함께 탐지·분류·연계(association)해야 하는데, 기존 방법(OVTrack, MASA)은 LVIS 이미지 쌍으로 만든 합성 프레임에 의존해 appearance cue만 쓰고, SLAck은 TAO의 성긴(discontinuous) 주석에서 IoU 매칭으로 만든 pseudo-label을 쓰지만 시간적 일관성이 부족하다.
- 기술적 목표: (1) OVMOT 전용 최초의 프레임 단위 연속 주석 학습 데이터셋(C-TAO)을 구축하고, (2) appearance·motion·semantic 세 cue의 신뢰도가 장면·카테고리마다 달라진다는 점을 반영해, 단순 합산(SLAck 방식)이 아니라 신뢰도 기반으로 동적으로 가중치를 배분하는 융합 기법을 설계하는 것.
- 다루는 범위: C-TAO 데이터셋 구축·통계 비교, appearance/location/semantic head 설계, intra-frame confidence(SGN)와 inter-frame confidence(cycle-consistency) 정식화, Multi-cue Aggregation Network(MAN)와 재연결(refinement) 단계, association loss, TAO validation/test set에서의 SOTA 비교 및 ablation.

## 3. 핵심 개념 상세

### C-TAO 데이터셋
- 원문 표현: "C-TAO enlarges the annotations of TAO by over 26 times (in terms of annotated frames)... cross-frame IoU increases by 2.2 times, area change rate reduces to 1/8 of the original, and average pixel displacement decreases from 101 to 6.6 pixels, a 93.5% reduction."
- 정의: TAO 학습셋의 동일 비디오·카테고리·트랙을 유지한 채, 원래 30프레임 간격으로만 있던 주석의 빈 프레임을 사람이 직접 bbox·카테고리·ID로 재주석한 프레임 단위(490,210 프레임, 1,521,559 박스) 연속 학습 데이터셋. 3단계(주석→카테고리 라벨링→교차검증) 파이프라인으로 제작됨.
- 역할: 이 데이터셋 자체가 방법론과 독립적인 기여이며, Table 4의 P-TAO(주석 2배로만 늘린 절충안) 실험은 "완전 연속 주석"보다 "약간의 연속 주석"만으로도 novel AssocA가 13.7%p 개선되는 diminishing-return 패턴을 보여준다.

### Appearance / Location / Semantic Cue 추출
- 원문 표현: "we adopt the same detector as in OVTrack and SLAck for OV detection and freeze it during training... we fuse CLIP's text and image embeddings via element-wise summation, refine them with an MLP."
- 정의: 고정된 사전학습 OV 탐지기(Faster R-CNN + ResNet-50, LVIS base class로 학습)의 RoI feature로부터 appearance embedding, 정규화된 bbox 좌표로부터 location embedding, CLIP 텍스트·이미지 임베딩을 distill한 semantic embedding을 각각 얻는다.
- 역할: 세 cue는 서로 다른 정보원(시각적 외형, 기하학적 위치, 카테고리 의미)을 대표하며, 이후 신뢰도 기반 융합의 입력이 된다.

### Intra-frame Cue Confidence (Self-attentive Gated Network, SGN) — 실제 정식화
- 원문 표현(Eq. 1): `[c_loc^intra, c_sem^intra] = sigmoid(SGN(concat(e_app, e_loc, e_sem)))`, "SGN is designed as two fully connected layers with a ReLU activation, and the sigmoid activation ensures that the gate values ... are within the range [0, 1]."
- 정의: 같은 프레임 안에서 appearance/location/semantic 세 임베딩을 concat한 뒤 2-layer FC+ReLU 네트워크(SGN)에 통과시키고 sigmoid로 [0,1] 게이트 값 두 개(location용, semantic용)를 얻는다. appearance 자체는 게이팅되지 않고 SGN의 입력(기준)으로만 쓰인다(ablation에서 SGN 입력에서 e_app을 빼면 novel TETA가 34.3→32.0으로 하락해 그 필요성을 확인).
- 역할: "location/semantic cue가 appearance와 비교해 이 프레임에서 얼마나 믿을만한가"를 학습으로 산출하는 게이트. 저자들은 명시적 지도 없이 association loss의 역전파만으로 이 게이트가 학습된다고 설명한다.

### Inter-frame Cue Confidence (Cycle-consistency 기반 자기교정) — 실제 정식화
- 원문 표현(Eq. 2): 인접 프레임 t, t-1의 특징 행렬 `E_app^t`, `E_app^{t-1}` 간 유사도 `S_app = E_app^t · (E_app^{t-1})^T`를 적응적 온도 스케일링 `α = log((δ/(1-δ))·max(n,m))/ε` (δ=0.5, ε=0.1)으로 softmax 정규화한 `Ŝ_app`을 만든 뒤, cycle consistency 행렬 `C_app^cycle = Ŝ_app · (Ŝ_app)^T`를 계산하고, 그 대각선 성분 `c_app,i^inter = [diag(C_app^cycle)]_i`을 i번째 객체의 inter-frame confidence로 삼는다. 동일한 파이프라인을 location, semantic 특징에도 각각 적용해 `c_loc^inter`, `c_sem^inter`을 얻는다.
- 역할: "이 cue가 시간적으로 얼마나 안정적인가"(움직임이 급격하거나 외형이 갑자기 변하면 낮아짐)를 자기지도적(self-supervised) cycle-consistency로 측정한다. Fig. 4 정성 분석: `c_loc^inter`가 낮은 경우는 급격한 위치 변화, `c_sem^inter`가 낮은 경우는 연속 프레임 간 카테고리 불일치, `c_app^inter`가 낮은 경우는 defocus·motion blur로 인한 급격한 외형 변화와 대응된다.

### Multi-Cue Feature Fusion (intra × inter 곱셈 게이팅 + MAN + 재연결)
- 원문 표현(Eq. 3-5): `ẽ_loc = c_loc^intra · c_loc^inter · e_loc`, `ẽ_sem = c_sem^intra · c_sem^inter · e_sem`; `f_m-cue = MAN(concat(e_app, ẽ_loc, ẽ_sem))`; 최종 `f_asso = c_app^inter · e_app + (1 - c_app^inter) · f_m-cue`.
- 정의: location·semantic 임베딩은 자신의 intra-frame 게이트와 inter-frame 게이트를 **곱해서**(단순 가중합이 아니라 두 신뢰도의 곱) 스케일링된 뒤 appearance와 concat되어 2-layer FC 네트워크인 MAN에 입력된다. 마지막으로 appearance의 inter-frame confidence `c_app^inter`가 원본 appearance feature와 MAN 출력(f_m-cue) 사이를 보간하는 게이트로 다시 쓰인다(appearance가 시간적으로 안정적이면 원본 appearance를 더 신뢰하고, 불안정하면 다중 cue 통합 결과를 더 신뢰).
- 선정 이유(대비): SLAck은 `e_fused = e_app + e_loc + e_sem` 단순 합산인데, COVTrack은 이를 "naive equal-weighting"이라 비판하며 novel 카테고리일수록 semantic 분류 정확도가 한 자릿수까지 떨어져 균일 가중치가 노이즈를 유발한다고 지적한다.
- **콜리그 주장 검증 결과**: "intra-frame vs inter-frame confidence에 따라 adaptive하게 fusion한다"는 주장은 정확하다. 다만 정확히는 (a) 두 신뢰도가 완전히 별개 메커니즘(SGN 학습형 게이트 vs cycle-consistency 자기지도 게이트)으로 각각 산출되고, (b) location/semantic feature는 이 둘을 곱한 값으로 스케일링되며(단순 평균이나 softmax 가중합이 아닌 element-wise 곱), (c) appearance feature 자신은 intra confidence로 게이팅되지 않고 오직 inter-frame confidence만으로 원본 대 fused 표현 간 선형 보간(convex combination)에 쓰인다는 점이 세부 차이다.

### TETA (Tracking-Every-Thing Accuracy) 평가지표
- 원문 표현: "we adopt the standard OVMOT metric, tracking-everything accuracy (TETA), which evaluates localization accuracy (LocA), classification accuracy (ClsA), and association accuracy (AssocA)."
- 정의: TAO 벤치마크에서 온 지표로 위치 정확도(LocA)·분류 정확도(ClsA)·연계 정확도(AssocA) 세 하위지표를 분리 평가해, open-vocabulary 상황에서 분류 오류가 추적 성능 전체를 가리는 것을 방지한다.
- 역할: COVTrack 논문은 novel 카테고리에서 ClsA가 여전히 한 자릿수(예: validation novel ClsA 3.5)에 불과함을 인정하면서도, AssocA·LocA 개선이 전체 TETA 개선을 이끈다고 설명한다.

## 4. 구조 및 흐름
1. 사전학습된 OV 탐지기(고정, freeze)에서 각 객체에 대해 appearance/location/semantic 세 임베딩을 추출한다(§4.2).
2. 같은 프레임 t 안에서 SGN이 세 임베딩을 concat·FC·sigmoid로 처리해 `c_loc^intra`, `c_sem^intra` 두 게이트를 산출한다(Eq. 1).
3. 인접 프레임 t, t-1 사이에서 appearance/location/semantic 각각에 대해 유사도 행렬→온도 스케일 softmax→cycle-consistency 행렬을 계산해 `c_app^inter`, `c_loc^inter`, `c_sem^inter`를 얻는다(Eq. 2).
4. location·semantic feature를 각자의 intra×inter 게이트로 스케일링한 뒤 appearance와 concat하여 MAN에 넣어 `f_m-cue`를 만든다(Eq. 3-4).
5. `c_app^inter`를 이용해 원본 appearance feature `e_app`과 `f_m-cue`를 convex combination으로 보간해 최종 연계 특징 `f_asso`를 만든다(Eq. 5).
6. 인접 프레임의 `f_asso` 간 유사도에 softmax cross-entropy 형태의 association loss(Eq. 6)를 적용해 SGN·MAN을 포함한 5개 학습 가능 신뢰도 점수 전체를 end-to-end로 역전파 학습한다(명시적 지도 없이).
7. 추론 시 class-agnostic NMS(프레임당 최대 80객체) 후 bi-softmax 매칭(threshold 0.35, memory queue 30)으로 온라인 추적을 수행하며, TAO validation/test set에서 novel/base로 나눈 TETA·LocA·AssocA·ClsA로 평가한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| C-TAO의 연속 주석이 OVMOT 학습에 실질적 이득을 준다 | 동일 SLAck 모델을 원본 TAO(24.6 novel TETA)로 학습했을 때보다 C-TAO(34.3)로 학습했을 때 novel/base AssocA가 각각 +6.5%p/+6.2%p 개선(Table 3); OVTrack도 원본 TAO 대비 C-TAO에서 novel AssocA +13.7%p(Table 4) |
| Intra/inter-frame confidence 기반 적응적 융합이 SLAck의 단순 합산보다 우수하다 | 원본 성긴 TAO로 학습 시 SLAck 24.6 → COVTrack(동일 데이터) 31.0 novel TETA, AssocA 기준 +10.7%p 개선(Table 3); ablation에서 5개 confidence 성분을 하나씩 제거하면 모두 성능이 하락(Table 2, 최댓값 대비 최대 -2.2 novel TETA) |
| COVTrack이 TAO open-vocabulary validation/test 벤치마크에서 SOTA다 | validation novel TETA 34.3(SLAck 31.1, OVTrack 27.8, MASA 30.0); validation base TETA 39.6(SLAck 37.2); test set에서도 novel TETA 28.9(SLAck 27.1), base AssocA는 SLAck 대비 +6.5%p(base), +2.6%p(novel) 개선 |
| Appearance를 SGN 입력에서 제외하면 confidence 추정 품질이 떨어진다 | Eq.1 입력에서 e_app 제거 시 novel TETA 34.3→32.0, novel AssocA 41.3→36.5로 큰 폭 하락(Table 2, 8행) — appearance가 다른 cue 신뢰도 판단의 기준점 역할을 한다는 근거 |

## 6. 한계 및 부족한 점
- 공식 ICCV 2025 Open Access PDF(10054-10063쪽) 원문을 pypdf로 전체 확인했다.
- Novel 카테고리의 ClsA(분류 정확도)는 COVTrack에서도 validation 3.5, test 3.3에 불과해 여전히 매우 낮다 — 논문이 강조하는 개선은 주로 AssocA·LocA이며, open-vocabulary 분류 자체의 근본적 어려움은 해결되지 않았다.
- Table 4의 관찰("완전 연속 주석은 diminishing return")은 P-TAO(2배 주석)라는 한 가지 절충 비율만 실험했을 뿐, 최적 주석 밀도에 대한 체계적 탐색은 없다.
- 저자들이 명시한 것은 아니지만, C-TAO 구축이 전면 수작업 재주석(사람 3단계 파이프라인)에 의존하므로 새로운 도메인·데이터셋으로 이 접근을 확장하는 비용은 상당히 클 것으로 보인다 — 논문은 이 확장 비용에 대한 논의를 포함하지 않는다.
- 평가가 TAO 계열(동일 비디오·카테고리 분할) validation/test에 한정되며, 다른 open-vocabulary 벤치마크(예: 관련 연구에서 언급된 OVT-B)에서의 일반화는 이 논문 범위에서 보고되지 않는다.
- (참고) 같은 저자 그룹의 후속 연구로 "COVTrack++"(arXiv 2603.24016, 2026년 3월)이 존재하며 Multi-Granularity Hierarchical Aggregation·Temporal Confidence Propagation을 추가한다고 검색됨 — 이는 별도 논문이며 본 COVTrack(ICCV 2025)의 내용이 아니므로 혼동하지 않아야 한다.

## 7. 원문 기반 핵심 문장
> "we introduce COVTrack, a unified framework that effectively integrates motion and semantic features with appearance features, in which the multi-cue feature aggregation strategy dynamically aggregates and balances these features, based on the confidence estimation from both intra-frame and inter-frame contexts."

> "intra-frame confidence assesses the reliability of semantic and location features within a single frame by learning their mutual relationships with appearance features. Second, inter-frame confidence leverages temporal consistency between adjacent frames to evaluate the stability of each feature type across time."

> "f_asso = c_app^inter · e_app + (1 − c_app^inter) · f_m-cue ... When appearance features demonstrate strong temporal consistency (high c_app^inter), the model places greater emphasis on e_app. Conversely, when appearance features show weak temporal consistency (low c_app^inter), the model relies more on the information-rich aggregated feature f_m-cue."
