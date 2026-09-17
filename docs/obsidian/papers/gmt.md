# GMT: Effective Global Framework for Multi-Camera Multi-Target Tracking

## 메타데이터
- categories: Cross-View Feature Consistency Enhancement, Global Trajectory Association, Multi-Camera Multi-Target Tracking, VisionTrack 데이터셋
- domain: [[객체 추적]]
- source: Zhen, Yihao, Xu, Mingyue, Wang, Qiang, Fan, Baojie, Dong, Jiahua, Zhao, Tinghui, Fan, Huijie. "GMT: Effective Global Framework for Multi-Camera Multi-Target Tracking." IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2026.
- url: https://arxiv.org/abs/2407.01007 (CVF: https://openaccess.thecvf.com/content/CVPR2026/papers/Zhen_GMT_Effective_Global_Framework_for_Multi-Camera_Multi-Target_Tracking_CVPR_2026_paper.pdf) / code: https://github.com/FoxCanned/GMT
- year: 2026
- authors: Yihao Zhen, Mingyue Xu, Qiang Wang, Baojie Fan, Jiahua Dong, Tinghui Zhao, Huijie Fan (Shenyang Institute of Automation, CAS; Shenyang University; University of Chinese Academy of Sciences; Nanjing University of Posts and Telecommunications; Mohamed bin Zayed University of Artificial Intelligence)
- venue: CVPR 2026 (arXiv 2407.01007 — v1 2024-07-01, v2 2025-11-24 camera-ready update; GitHub README explicitly labels it "the official implementation of the CVPR 2026 paper")

## 1. 핵심 요약
- 기존 Multi-Camera Multi-Target(MCMT) tracking은 Single-Camera Tracking(SCT) 후 Inter-Camera Tracking(ICT)을 붙이는 2단계 구조를 쓰는데, 이 구조에서 multi-view 정보는 SCT가 놓친 매칭을 보정하는 역할에 그친다. GMT는 여러 뷰에 걸친 동일 과거 타겟을 하나의 global trajectory로 먼저 통합해 두고, 새로 검출된 타겟을 이 global trajectory 집합에 직접 매칭하는 단일 global-level trajectory-target association 문제로 재정식화한다.
- CFCE(Cross-View Feature Consistency Enhancement) = VFCE(시각 특징 정합) + RPCE(상대 위치 정합) 두 서브모듈로 구성되며, 뷰마다 다른 시각·기하 특징을 trajectory-중심 공간으로 정렬해 GTA에 넘긴다. GTA(Global Trajectory Association)는 DETR 계열 encoder-decoder로 최근 T프레임의 trajectory를 인코딩하고 신규 타겟 특징과 상호작용시켜 유사도 행렬을 만든 뒤 Hungarian 알고리즘으로 매칭한다.
- VisionTrack: 이동 중인 UAV 2대로 촬영한 15개 실제 시나리오, 88 시퀀스, 2-view, 116K 프레임, 1,176K bounding box 규모의 신규 MCMT 데이터셋을 공개했다(기존 EPFL/CAMPUS/WILDTRACK/MvMHAT/DIVOTrack 대비 최대 규모·다양성).
- 성능 향상 폭은 데이터셋마다 다르다. Abstract가 밝힌 "up to 21.3% CVMA, 17.2% CVIDF1"는 WildTrack 결과이며, 논문이 제안한 VisionTrack 자체에서의 2위 대비 향상폭은 CVMA +5.1%p, CVIDF1 +11.3%p이다. 콜리그가 언급한 "CVMA +13.1%, CVIDF1 +19.2%"는 논문의 어떤 표에도 정확히 일치하지 않는 수치로, 출처가 불명확하다(§6 참고).

## 2. 문서 목적
- 해결하려는 문제: 2단계 MCMT 프레임워크에서는 최종 추적 결과가 사실상 SCT 단계에서 결정되고 multi-view 정보는 ICT 단계의 보정에만 쓰여, 여러 카메라가 제공하는 추가 시각 정보의 이점을 충분히 활용하지 못한다. 또한 cross-view association을 독립된 단계로 두면 시점 차이가 크거나 카메라 수가 늘어날수록 오류 위험이 커진다.
- 기술적 목표: 뷰별로 독립적으로 trajectory를 배정하는 대신, 서로 다른 뷰에서 관측된 동일 과거 타겟들을 global trajectory로 인코딩하고, 신규 검출을 이 global trajectory에 대해 직접 매칭하는 global-level trajectory-target association으로 MCMT를 재구성한다.
- 다루는 범위: CFCE(VFCE+RPCE) 모듈 설계, GTA(DETR 기반 encoder-decoder + Hungarian 매칭 + occlusion 복구용 memory bank) 설계, 2단계 학습 절차, VisionTrack 데이터셋 구축·주석 방법, EPFL/CAMPUS/WILDTRACK/MvMHAT/DIVOTrack/VisionTrack 6개 데이터셋에서 SOTA와의 비교 및 ablation, 모델 효율성(파라미터·FLOPs·속도·수렴 속도) 비교.

## 3. 핵심 개념 상세

### CFCE (Cross-View Feature Consistency Enhancement) — VFCE + RPCE
- 원문 표현: "The CFCE module consists of Visual Feature Consistency Enhancement (VFCE) module and Relative Position Consistency Enhancement (RPCE) module... The VFCE module projects the visual features of targets to a unified trajectory-centric space through metric learning... The RPCE module further encodes cross-target relative positional relationships, offering a geometric [complement] to visual features."
- **VFCE 메커니즘**: 검출기(CenterNet+DLA-34)가 출력한 view-centric 시각 특징 F_t를 2-layer MLP projection head로 trajectory-centric 공간 F_t^τ로 사영한다. 각 예측 박스는 IoU가 최대인 GT 박스의 ID를 할당받고, F_t^τ의 ID 일관성을 cross-entropy loss + triplet loss + center loss(L_VFCE = L_CE + L_Triplet + L_Center)로 지도해, 같은 trajectory 내에서 뷰가 달라져도 외형이 일관되도록 강제한다.
- **RPCE 메커니즘**: 서로 다른 뷰에서 촬영된 동일 장면의 타겟 위치 그래프는 affine 변환으로 정렬될 수 있다는 "projective consistency"에 착안한다. i번째 타겟에 대해 정규화된 중심좌표와 주변 M개 이웃 타겟과의 상대 좌표 차이로 구성된 벡터 G_i = [x_i, y_i, Δx_1, Δy_1, ..., Δx_M, Δy_M]를 만들되, overlap 영역 밖의 이웃이 잡음으로 섞이지 않도록 거리 기반 필터링 반경 r = (2 + 2·clip((r_max−√s_i)/(r_max−r_min), 0, 1))·√s_i (s_i는 정규화된 박스 크기, r_max/r_min은 사전 정의된 스케일 경계) 이내의 이웃만 사용한다. G_t를 2-layer MLP로 F_t^p로 인코딩하고 triplet loss + center loss(L_RPCE)로 지도한다(ID 분류가 아니라 공간 관계이므로 cross-entropy는 쓰지 않음).
- F_t^τ와 F_t^p를 concat해 최종 association feature F_t^asso를 만들어 GTA에 전달한다.

### GTA (Global Trajectory Association)
- 원문 표현: "Within GTA, global trajectories from historical frames are further encoded to enrich the temporal contextual information of trajectory features, while the features of new targets interact with the global trajectories to learn discriminative information across different trajectories. Finally, the GTA module computes the similarity matrix between historical trajectories and new targets and performs trajectory-target matching using the Hungarian algorithm."
- 기존 방식(SORT 계열)은 공간적 연속성에 의존해 multi-view 입력을 다루지 못하므로, GMT는 DETR 계열 encoder-decoder 구조로 GTA를 구성한다.
- **인코딩**: 최근 T프레임 동안 같은 trajectory에 속하는 모든 검출 타겟 특징을 concat하고 동일 trajectory에는 공유 ID 임베딩을 부여해 global trajectory 표현 Γ ∈ R^(L×d)를 만들고, 이를 encoder layer로 인코딩한다.
- **디코딩/상호작용**: F_t^asso 내 후보 타겟들이 먼저 서로 상호작용해 문맥 특징을 얻은 뒤 쿼리가 되어 Γ와 상호작용하며 trajectory 간 판별적 정보를 학습해 강화된 특징 F̄_t^asso를 만든다.
- **매칭**: F̄_t^asso와 Γ 간 유사도 행렬 M_s ∈ R^(N×L)을 계산하고, 한 trajectory에 속한 모든 타겟과의 평균 유사도로 target-trajectory 유사도 행렬 M ∈ R^(N×K)을 구성한 뒤 Hungarian 알고리즘으로 최종 매칭한다.
- **장기 폐색 복구**: 최근 T프레임 동안 관측되지 않았지만 그 이전 시간 임계값 내에 관측된 historical trajectory는 memory bank에 저장되고, Γ와 매칭 실패한 타겟은 memory bank와 재매칭을 시도한다.
- **학습 손실**: 유사도 행렬 M_s에 "매칭 없음"을 뜻하는 all-zero 열을 추가한 뒤 같은 시각·같은 뷰의 타겟들에 대해 softmax를 적용한 확률분포 H를 만들고(식 5), 정답 매칭쌍 X_ij에 대한 negative log-likelihood(식 7)로 L_asso를 정의한다.
- **2단계 학습**: RPCE/GTA는 정확한 위치 추정에 의존하므로 stage1(검출기+VFCE, L_det+L_VFCE)과 stage2(전체 모델, L_det+λ1·L_asso+λ2·L_VFCE, λ1=3, λ2=0.5, 단 metric learning 손실은 제외)로 나눠 학습한다(단일 단계 학습도 가능하나 약간의 성능 저하가 있다고 명시).

### "Global-first" 재정식화가 실제 핵심 주장인가
- 확인됨. 원문: "instead of assigning trajectories independently for each view, GMT directly encodes the same historical targets across different views as global trajectories, thereby converting the MCMT tracking task into a global-level trajectory-target matching task." 그리고 "2) The unnecessary cross-view matching is avoided by directly determining which global trajectory the new targets belong to."
- 즉 GMT는 (a) 뷰별 독립 SCT 트랙을 먼저 만든 뒤 (b) 별도의 ICT 단계로 뷰 간 매칭을 수행하는 전통적 2단계 방식이 아니라, 처음부터 여러 뷰의 과거 관측을 하나의 global trajectory로 묶어두고 신규 타겟을 이 global trajectory에 직접 매칭한다. 이 재정식화가 논문이 명시한 핵심 novelty이며, ablation(Table 4, "Local" vs GMT)에서 이 설계 자체의 효과를 별도로 검증한다.

### VisionTrack 데이터셋
- 이동 중인 UAV 2대로 촬영(고정 지상 카메라를 쓰는 기존 데이터셋과 대비), 30FPS, 1920×1080 해상도.
- 규모: 15개 실제 시나리오, 88 시퀀스, 2 views, 116K 프레임, 1,176K bounding box. 학습/테스트 약 1:1 분할.
- 비교 표(논문 Table 1) 기준: EPFL(5 scenes/4 views/97K frames/625K boxes), CAMPUS(4/4/83K/490K), MvMHAT(1/4/31K/208K, moving camera), WILDTRACK(1/7/3K/40K), DIVOTrack(10/3/54K/560K, moving camera, UAV 1대), VisionTrack(15/2/116K/1,176K, moving camera, UAV 2대) — scene 수·box 수 기준 최대 규모이며, "두 대의 이동 UAV" 조건은 VisionTrack만 해당.
- 주석 절차: (1) 동일 시각 t의 서로 다른 뷰에서 겹치는 시야에 있는 동일 타겟에 사람이 직접 고유 ID 부여, (2) 반자동 추적 주석 도구(Darklable/DarkLabel로 추정)로 t−1 시각의 기존 주석과 연결해 시간축으로 ID를 전파.

## 4. 구조 및 흐름
1. 시각 t에 c대의 카메라에서 검출기(CenterNet+DLA-34 backbone)가 박스 집합 B_t와 특징 F_t를 산출한다.
2. CFCE: VFCE가 F_t를 trajectory-중심 공간 F_t^τ로 사영(metric learning 손실로 지도), RPCE가 거리 기반 필터링을 적용한 상대 위치 그래프 G_t를 F_t^p로 인코딩한다. 둘을 concat해 F_t^asso를 만든다.
3. GTA: 최근 T프레임의 같은-trajectory 특징을 모아 global trajectory Γ를 만들고 encoder로 인코딩한다. decoder에서 F_t^asso가 self-interaction 후 Γ와 상호작용해 F̄_t^asso를 얻고, 유사도 행렬(M_s → 평균 후 M)을 계산해 Hungarian 알고리즘으로 target-trajectory 매칭을 수행한다. 매칭 실패 타겟은 장기 폐색 memory bank와 재시도한다.
4. 학습은 2단계(stage1: 검출기+VFCE, stage2: 전체 파이프라인 + L_asso)로 분리해 RPCE/GTA가 정확한 위치 정보에 의존하는 문제를 완화한다.
5. 평가: EPFL/CAMPUS/WILDTRACK/MvMHAT/DIVOTrack/VisionTrack 6개 데이터셋에서 단일뷰 지표(MOTA, HOTA, IDF1, ASSA)와 cross-view 지표(CVMA, CVIDF1, Han et al. AAAI2020 정의 인용)로 SOTA와 비교하고, CFCE 구성요소별·global trajectory 사용 여부별 ablation, 파라미터/FLOPs/속도/수렴 속도 비교를 수행한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| Global 프레임워크(뷰 독립 트랙 대신 global trajectory에 직접 매칭)가 성능 향상의 핵심 요인이다 | Table 4 ablation: VisionTrack의 각 뷰를 독립적으로 평가한 뒤 평균한 "Local" 대비 global trajectory를 쓰는 GMT가 IDF1 +4.0%p, ASSA +4.5%p 향상; 유사 구조의 다른 DETR 기반 단일뷰 트래커 대비로도 HOTA +4.8%p, IDF1 +6.2%p, ASSA +6.3%p 향상(검출 성능(MOTP)은 오히려 더 낮음에도) |
| CFCE의 두 서브모듈(VFCE, RPCE)이 각각 유의미하게 기여한다 | Table 3 ablation(VisionTrack): VFCE의 metric-learning 손실 제거 시 CVMA -2.8%p(75.2→72.4), CVIDF1 -3.2%p(81.3→78.1), IDF1 -4.9%p(82.1→77.2); RPCE 제거 시 CVMA -1.2%p, CVIDF1 -1.5%p; L_RPCE나 거리 임계값만 제거하면 RPCE 전체 제거보다 더 나쁜 경우도 있어 두 구성요소가 잡음 필터링에 실질적으로 기여함을 시사 |
| GMT는 6개 데이터셋 전반에서 기존 SOTA를 능가하지만, 향상 폭은 데이터셋마다 크게 다르다 | Table 2(2위 방법 대비, %p): VisionTrack CVMA +5.1/CVIDF1 +11.3; DIVOTrack +5.1/+4.1; WildTrack +21.3/+17.2(논문 abstract의 "up to" 수치의 출처); MvMHAT +3.2/+5.2; CAMPUS·EPFL은 논문이 gain %를 명시하지 않았으나 표 값으로 계산하면 각각 약 +1.0/+14.4, +3.1/+7.6이며 CAMPUS의 MOTA만 2위. WildTrack처럼 뷰·타겟 수가 많을수록 기존 방법 대비 격차가 커짐 |
| GMT는 추가 모듈에도 불구하고 기존 방법과 비슷한 추론 효율을 유지하며 더 빠르게 수렴한다 | Table 5: GMT 30.0M 파라미터/227.6G FLOPs/14.6fps로 CrossMOT(24.3M/227.1G/14.2fps)와 유사한 추론 비용이지만 학습 시간은 7.3시간으로 CrossMOT(16.5h)·MVMHAT++(11h)보다 짧고, Fig. 6에서 수렴 속도도 더 빠름 |

## 6. 한계 및 부족한 점
- pdftotext로 arXiv v2(2025-11-24 갱신, CVPR 2026 카메라레디와 사실상 동일 텍스트로 추정) 8쪽 본문 전체를 직접 확인했다. CVF 공식 HTML(`openaccess.thecvf.com/content/CVPR2026/html/...`)과 PDF는 자동화 접근이 403으로 차단되어 직접 열람하지 못했고, 대신 웹 검색 결과에 해당 URL이 실제로 존재함을 확인해 간접적으로 출판 사실을 뒷받침했다. 즉 venue 확인은 (1) arXiv 논문 자체가 "CVPR 2026" 카메라레디로 개정된 정황(v2 날짜, 저자 소속 표기 스타일), (2) GitHub README가 "official implementation of the CVPR 2026 paper"라 명시, (3) CVF 사이트의 논문 전용 URL이 검색엔진에 존재하는 점에 근거하며, CVF 페이지 자체의 스크린샷 수준 검증은 아니다.
- 콜리그가 제시한 "CVMA +13.1%, CVIDF1 +19.2%" 수치는 논문의 어떤 데이터셋 결과와도 정확히 일치하지 않는다. 실측: VisionTrack +5.1/+11.3, DIVOTrack +5.1/+4.1, WildTrack +21.3/+17.2(abstract가 인용한 "up to" 수치), MvMHAT +3.2/+5.2, CAMPUS·EPFL은 표에서 계산 시 약 +1.0/+14.4, +3.1/+7.6. 이 수치는 출처 불명이며 잘못 인용되었거나 다른 버전/설정의 결과와 혼동된 것으로 보인다.
- GitHub README 내부에 상충되는 문구가 있다: To-Do 목록에는 "~~Release the VisionTrack dataset.~~"로 취소선 처리(완료)되어 있고 실제 커밋 로그에도 "2026-07-05 Release VisionTrack and backbone weight"가 있어 데이터셋이 배포된 것으로 보이지만, Data Preparation 섹션 하단에는 "VisionTrack dataset will be released soon."이라는 문구가 그대로 남아있어 README 갱신 누락으로 판단된다. OneDrive/BaiduNetdisk 다운로드 링크가 실제로 제공되므로 데이터셋 자체는 공개된 것으로 보는 편이 합리적이나, 파일 내용물(실제 프레임 수·라벨 정확성)까지 직접 내려받아 검증하지는 않았다.
- 저자가 명시한 별도의 "Limitations" 절은 본문(8쪽 CVPR 포맷)에 없으며 부록(Appendix)으로 위임되어 있으나, 부록 내용은 이번 조사에서 확인하지 못했다.
- 주석 도구명("Darklable")은 원문 그대로 표기했으며 오탈자(DarkLabel의 오기)일 가능성이 있으나 원문을 그대로 인용했다.

## 7. 원문 기반 핵심 문장
> "Existing methods typically adopt a two-stage framework, involving single-camera tracking followed by inter-camera tracking. However, in this paradigm, multi-view information is used only to recover missed matches in the first stage, providing a limited contribution to overall tracking."

> "instead of assigning trajectories independently for each view, GMT directly encodes the same historical targets across different views as global trajectories, thereby converting the MCMT tracking task into a global-level trajectory-target matching task... 2) The unnecessary cross-view matching is avoided by directly determining which global trajectory the new targets belong to."

> "Compared to the two-stage framework, GMT achieves significant improvements on existing datasets, with gains of up to 21.3 percent in CVMA and 17.2 percent in CVIDF1. Furthermore, we introduce VisionTrack, a high-quality, large-scale MCMT dataset providing significantly greater diversity than existing datasets."

> "Since the SORT-based trackers used by existing methods rely heavily on spatial consistency and cannot handle multi-view inputs, we construct the GTA module following the DETR-based trackers."
