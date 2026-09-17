# IPOW: Interpretable Open-World Object Detection via Concept Decomposition Model

## 메타데이터
- categories: Concept Bottleneck Model 기반 RoI 분해, Neural Collapse 기반 판별 개념, LLM 기반 공유 개념 마이닝, Concept-Guided Rectification
- domain: [[객체 탐지·분할]]
- source: Lv, Xueqiang, Zhang, Shizhou, Xing, Yinghui, Xu, Di, Wang, Peng, Zhang, Yanning. "Knowing the Unknown: Interpretable Open-World Object Detection via Concept Decomposition Model." arXiv preprint, 2026.
- url: https://arxiv.org/abs/2602.20616
- year: 2026
- authors: Xueqiang Lv, Shizhou Zhang, Yinghui Xing, Peng Wang, Yanning Zhang (Northwestern Polytechnical University, Xi'an), Di Xu (Huawei Technologies)
- venue: arXiv preprint (2602.20616, submitted 2026-02-24). 논문 본문의 "Keywords" 줄과 GitHub 저장소 설명이 "ICML 2026"을 자칭하지만, arXiv 페이지 자체에는 accepted/comments 표기가 없고 OpenReview·ICML 2026 accepted-paper 목록 표본에서도 확인되지 않아 **동료가 전달한 "ICML 2026" venue는 독립적으로 검증되지 않음** — 정확히는 "ICML 2026 제출/자칭, 수락 여부 미확인"으로 정정해야 한다.

## 1. 핵심 요약
- Open-World Object Detection(OWOD)의 기존 방법들은 unknown recall을 높이는 데 집중할 뿐 해석 가능성을 다루지 않아 known-unknown confusion과 예측 신뢰도 저하 문제를 안고 있다.
- IPOW는 Faster R-CNN RoI feature를 discriminative(판별)·shared(공유)·background(배경) 세 concept 공간으로 명시적으로 분해하는 Concept Decomposition Model(CDM)을 제안하고, known-unknown confusion이 "unknown 객체가 known class의 discriminative space에 잘못 들어가는 현상"에서 비롯됨을 규명한 뒤 이를 완화하는 Concept-Guided Rectification(CGR)을 제안한다.
- M-OWODB·S-OWODB 두 벤치마크, Task 1~4 전 구간에서 ORE/OW-DETR/PROB/CAT/RandBox/OrthogonalDet/CROWD 대비 unknown recall과 known mAP를 모두 개선했다고 보고한다(예: M-OWODB Task1 U-Recall 50.1, 최강 baseline CROWD* 대비 +7.2pt).
- 공식 GitHub 저장소(qiangzai-lv/IPOW)는 MMDetection 3.3 기반 실제 모델 코드(concept head, GMM 기반 RPN, concept embedding 파이프라인)를 포함하지만, 논문이 보고한 4-task × 2-dataset 실험을 그대로 재현할 수 있는 config·체크포인트는 갖추지 않은 부분적 구현이다.

## 2. 문서 목적
- 해결하려는 문제: OWOD 모델이 unknown 객체를 찾아내는 성능(recall)만 최적화하고, "왜 이 영역을 unknown/known으로 판단했는가"를 설명하지 못해 known class와 unknown class를 혼동하는 known-unknown confusion이 반복되는 문제.
- 기술적 목표: RoI feature를 사람이 해석 가능한 concept 단위(discriminative/shared/background)로 분해하는 concept bottleneck 구조를 OWOD에 도입하고, 이 concept 활성화 패턴을 이용해 known-unknown confusion을 사후 교정하는 것.
- 다루는 범위: Concept Decomposition Model의 수학적 정의(직교 분해, discriminative/shared/background concept 학습), Concept-Guided Rectification의 rectified confidence 공식, M-OWODB/S-OWODB 4-task incremental 실험, WI·A-OSE 기반 confusion 정량 평가, GitHub 공식 구현의 실제 완성도.

## 3. 핵심 개념 상세

### Concept Decomposition Model (CDM) — RoI feature의 직교 분해
- 원문 표현: "we decompose it into two distinct vectors, namely the foreground feature $\mathbf{f}_{\mathrm{fg}}$ and the background feature $\mathbf{f}_{\mathrm{bg}}$ ... $\mathbf{z}=\mathbf{f}_{\mathrm{fg}}+\mathbf{f}_{\mathrm{bg}}$" (Eq. 4); "the extracted foreground feature is projected via orthogonal projections $P_{\mathcal{U}}$ and $P_{\mathcal{V}}$ into two orthogonal vectors: $\mathbf{u}=P_{\mathcal{U}}(\mathbf{f}_{\mathrm{fg}}), \mathbf{v}=P_{\mathcal{V}}(\mathbf{f}_{\mathrm{fg}})$" (Eq. 5); "the complete formulation of the concept feature is expressed as: $\mathbf{z}=\mathbf{u}+\mathbf{v}+\mathbf{f}_{\mathrm{bg}}$" (Eq. 9).
- 정의: 각 RoI feature $\mathbf{z}=\mathrm{ConceptHead}(\mathrm{RoIAlign}(\mathrm{FPN}(\mathrm{ResNet}(I)), x_i))$ (Eq. 2–3)를 우선 foreground/background로 분리하고(상호 배타적이므로 자연히 직교), foreground를 다시 고정된 상호 직교 행렬 $\mathbf{Q}_{\mathcal{U}}, \mathbf{Q}_{\mathcal{V}}$로 span된 두 부분공간 $\mathcal{U}$(discriminative)와 $\mathcal{V}$(shared)로 사영해 $\mathbf{z}=\mathbf{u}+\mathbf{v}+\mathbf{f}_{\mathrm{bg}}$ 세 항으로 재구성한다.
- 역할: known 객체는 discriminative concept $\mathbf{u}$로 분류하고, unknown 객체는 $\mathbf{u}^{\mathrm{unk}}$를 모델링하지 않는 대신 known class와 공유되는 shared concept $\mathbf{v}^{\mathrm{unk}}$(예: "네 다리", "바퀴" 같은 category-agnostic 속성)와 배경과 대비되는 background concept $\mathbf{f}_{\mathrm{bg}}$만으로 탐지한다("$\mathbf{z}^{\mathrm{unk}}=\mathbf{u}^{\mathrm{unk}}+\mathbf{v}^{\mathrm{unk}}+\mathbf{f}_{\mathrm{bg}}$", Eq. 10). 즉 "unknown class를 직접 배우지 않고도 known class로부터 전이된 shared/background concept로 탐지"하는 것이 핵심 아이디어다.

### Discriminative Concepts — Neural Collapse 기반 판별 개념
- 원문 표현: "we define discriminative concepts as the most discriminative positive–negative concept pairs between every two known categories, thereby driving known class representations toward an ETF structure" (§4.3).
- 정의: Neural Collapse 이론(class mean이 수렴 시 Equiangular Tight Frame(ETF)을 이룸, Eq. 11)에 착안해, LLM으로 두 known class 간 가장 구별되는 속성을 뽑아 positive/negative concept 쌍 $(\mathcal{C}_i^{u+}, \mathcal{C}_i^{u-})$을 만들고, CLIP 텍스트 인코더로 임베딩한 뒤 discriminative feature $\mathbf{u}$와의 코사인 유사도로 활성화 $a(\mathcal{C}_i^u)$를 계산한다(Eq. 12). 학습은 margin 기반 contrastive loss $\mathcal{L}_{\mathrm{disc}}=\sum_i[\|a(\mathcal{C}_i^{u+})-a(\mathcal{C}_i^{u-})\|_2^2-\delta]$ (Eq. 13)로 이루어지고, 최종 분류는 이 활성화 벡터에 선형 분류기를 얹어 수행한다(Eq. 14).
- 역할: known class만을 위한 최대 판별 공간을 만들되, 바로 이 공간이 unknown 객체(예: "사람 vs 고양이"를 다리 개수로 구분하도록 학습된 모델이 "네 다리 말"을 고양이로 오분류)를 잘못 흡수하는 known-unknown confusion의 근원이 된다는 점을 논문이 명시적으로 지적한다.

### Shared / Background Concepts — unknown 전이의 근거
- 원문 표현: "Shared Concepts generalize to unknown object detection through LLM-derived concepts and residual concepts learned via the reconstruction process." "Background Concepts ... are leveraged to identify regions that are inconsistent with the surrounding context."
- 정의: Shared concept은 LLM이 known class 전반에서 요약한 공통 속성 $\{\mathcal{C}_i^v\}$을 CLIP 유사도로 활성화하고(Eq. 15) BCE로 학습하되(Eq. 16), LLM이 놓친 속성을 보완하기 위해 sparse autoencoder로 잔차 concept을 추가 발굴한다($\alpha=\mathrm{Enc}(\mathbf{v})=\mathbf{W_e v}$, Eq. 17)하고 정렬 손실 $\mathcal{L}_{\mathrm{align}}$(Eq. 20)로 LLM concept과 잔차 concept이 중복 없이 상호 보완하도록 규제한다. Unknown-ness는 전체 shared concept 중 최대 활성값 $S_{\mathrm{unk}}^{\mathrm{share}}=\max_i a(\mathcal{C}_i^v)$로 정의된다. Background concept은 배경 RoI feature에 PCA를 적용해 얻은 정규직교 기저 $\mathbf{D}_{\mathrm{bg}}$(Eq. 21)이며, 임의 RoI를 이 기저로 재구성했을 때의 오차 $r(\mathbf{z})=\|\mathbf{z}-\hat{\mathbf{z}}\|_2$(Eq. 22)가 크면 배경과 다른 전경(잠재적 unknown)으로 판단한다.
- 역할: known class 학습만으로도 unknown class에 "전이 가능한" 근거(공통 속성·배경 이탈도)를 명시적으로 분리해 별도 unknown 라벨 없이 unknown 후보를 찾는다.

### Concept-Guided Rectification (CGR) — full activation vs. partial activation
- 원문 표현: "known objects must exhibit full-set activation of their predefined semantic concepts, whereas unknown objects may fall into the discriminative space $\mathcal{U}$ of known categories but typically trigger only partial activation within the shared space $\mathcal{V}$." (§4.6)
- 정의: known class $j$에 대한 교정된 신뢰도는 원래 분류 확률 $S_{\mathrm{cls}}^j$(Eq. 14)에 해당 class의 shared concept 집합 $\mathcal{C}_j$에 대한 활성화들의 기하평균(거듭제곱 $\eta$로 강도 조절)을 곱한 값이다: $S_{\mathrm{known}}^j = S_{\mathrm{cls}}^j \cdot \left(\prod_{c_k \in \mathcal{C}_j} \hat c_k\right)^{\eta/|\mathcal{C}_j|}$ (Eq. 23). Unknown 점수는 shared/background unknown 점수의 최댓값에 "가장 강한 known 신뢰도의 여집합"을 곱해 억제한다: $S_{\mathrm{unk}} = \max(S_{\mathrm{unk}}^{\mathrm{share}}, S_{\mathrm{unk}}^{\mathrm{bg}}) \cdot (1 - \max_j S_{\mathrm{known}}^j)$ (Eq. 24).
- 역할: known 객체는 자신의 shared concept 세트를 "전부" 활성화해야 높은 점수를 받고(full activation 요구), unknown 객체는 discriminative space에는 잘못 들어가더라도 shared concept은 "일부만" 활성화되므로(partial activation) known 신뢰도가 억제되고 unknown 점수가 상대적으로 부각된다. 이는 사후처리(post-hoc rectification)가 아니라 학습된 concept 활성화 자체를 재사용하는 해석 가능한 교정이다.

## 4. 구조 및 흐름
1. Backbone/RPN: ResNet+FPN으로 특징을 추출하고, known class에 편향되는 일반 RPN 대신 GMM 기반 RPN(부록 C)으로 proposal을 생성해 known-class bias를 완화한다.
2. Concept Head: 각 RoI feature를 1×1 conv + 2개 선형층으로 구성된 Concept Head에 통과시켜 concept feature $\mathbf{z}$를 얻는다.
3. Concept Decomposition: $\mathbf{z}$를 foreground/background로 나누고, foreground를 다시 discriminative concept 공간 $\mathcal{U}$와 shared concept 공간 $\mathcal{V}$로 직교 분해한다.
4. 세 concept 학습: discriminative concept은 LLM이 뽑은 pairwise 속성 + CLIP 임베딩 + margin contrastive loss로, shared concept은 LLM 요약 속성 + sparse-autoencoder 잔차 + BCE + 정렬 손실로, background concept은 배경 RoI들의 PCA 기저로 각각 학습·구성한다.
5. 추론 및 교정: known 분류는 discriminative concept 활성화 기반 분류기로, unknown 후보는 shared/background unknown 점수로 산출한 뒤, Concept-Guided Rectification이 known confidence(전체 shared concept 활성화의 기하평균)와 unknown score(최대 known confidence로 억제)를 동시에 재계산해 known-unknown confusion을 완화한다.
6. 평가: M-OWODB·S-OWODB에서 Task1→4 incremental 학습을 수행하며 각 task마다 U-Recall(unknown)과 mAP(이전/현재/전체 known)를 측정하고, WI(Wilderness Impact)·A-OSE(Absolute Open-Set Error)로 known-unknown confusion을 별도로 정량화한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| CDM 기반 concept 분해가 unknown recall과 known mAP를 동시에 개선한다 | M-OWODB Task1: IPOW U-Recall 50.1 / known mAP 62.4, 최강 baseline CROWD* 42.9 / 61.7 대비 +7.2pt/+0.7pt; Task2 U-Recall 41.9(+10.5pt vs CROWD* 31.4), Task3 U-Recall 46.3(+11.6pt vs CROWD* 34.7); S-OWODB에서도 전 Task에서 CROWD*·OrthogonalDet·PROB·CAT·OW-DETR·ORE·RandBox 대비 U-Recall·mAP(Both) 모두 최고치 달성(Task1 34.7/73.6, Task2 32.6/55.1, Task3 44.3/50.5) |
| Discriminative concept 공간이 known-unknown confusion의 근원이며, CGR로 이를 정량적으로 줄일 수 있다 | "CGR significantly reduces known–unknown confusion, achieving a reduction of 19.7%, 65.7% and 60.2% in WI and 41.7%, 61.0% and 57.5% in A-OSE across 3 tasks."(§5 ablation, Table 2/3 계열) |
| Neural Collapse 이론에 기반한 discriminative concept 설계가 known class 분리에 유효하다 | ETF 성질(class mean의 norm 동일·pairwise 코사인 유사도 $-1/(K-1)$, Eq. 11)을 명시적 목표로 삼아 margin contrastive loss(Eq. 13)로 discriminative concept을 학습, 이는 기존 방법들이 objectness score 하나로 unknown을 뭉뚱그려 판정하던 것과 대비해 known class 분리도를 높인다고 주장 |
| Shared/background concept만으로도 별도 unknown 라벨 없이 unknown 객체에 전이 가능한 근거를 얻을 수 있다 | "$\mathbf{v}^{\mathrm{unk}}$ and $\mathbf{v}^{\mathrm{known}}$ are expected to be highly overlapping within the shared subspace" — 이 가정 위에서 shared concept 최대 활성화(Sunk-share)와 배경 재구성 오차(Sunk-bg)만으로 unknown 후보를 판정하고, 실제로 baseline 대비 큰 폭의 U-Recall 향상을 보고함 |

## 6. 한계 및 부족한 점
- arXiv HTML(v1, 2602.20616) 본문 전체와 공식 GitHub 저장소(qiangzai-lv/IPOW, master 브랜치 파일 트리 821개 항목)를 직접 확인했다.
- **venue 검증 결과**: 논문 자체(Keywords 줄)와 GitHub 저장소 설명("official PyTorch implementation of our ICML 2026 paper")이 ICML 2026을 자칭하지만, arXiv 제출 정보에는 accepted/comment 필드가 없고, ICML 2026(2026-07 서울 개최, accepted paper 표본 목록)에서 해당 제목을 확인하지 못했으며 OpenReview 검색으로도 결정 상태를 찾지 못했다. 즉 "ICML 2026 논문"이라는 동료의 전제는 현재 시점(2026-09) 기준 독립적으로 검증되지 않으며, 정확히는 "2026-02-24 제출된 arXiv 프리프린트, ICML 2026 제출/자칭"으로 표기해야 한다. (같은 저자 그룹의 다른 저장소들도 AAAI 2026·CVPR 2025를 자칭하는 패턴이 있어 자체 표기를 그대로 신뢰하기보다 별도 확인이 필요함을 시사한다.)
- **저장소 완성도**: 공식 코드는 MMDetection 3.3 위에 `mmdet/models/detectors/faster_ipow.py`, `mmdet/models/roi_heads/ipow_roi_head.py`, `bbox_heads/ipow_convfc_bbox_head.py`(PCA 기반 배경 재구성 함수 `get_fg_score_pca_no_center` 등 논문의 Eq. 21-22에 대응하는 실제 구현 포함), `utils_ipow/`의 GMM-RPN·concept 임베딩 파이프라인, 사전 계산된 concept/embedding 파일(`.pt`/`.pth`, `concept_map.json`, `attribute_bank.json`)을 실제로 포함하는 부분적으로 동작하는 구현이다. 그러나 (1) `configs/ipow/`에는 M-OWODB Task1용 config 3개(t1, t1_80, t1_120)만 존재하고 Task2~4, S-OWODB용 config는 전혀 없어 논문이 보고한 4-task × 2-benchmark 전체 실험을 저장소만으로 재현할 수 없다. (2) README의 학습 명령어 자체가 `configs/itow/itow_owod_mowodb_t{1..4}.py` 경로를 가리키는데 실제 디렉터리명은 `configs/ipow/`이고 t2~t4 파일도 없어 README 그대로 실행하면 즉시 실패한다("itow"/"ipow" 오타 내지 미정리 흔적). (3) 사전학습 체크포인트·학습 로그·U-Recall/WI/A-OSE를 계산하는 전용 평가 스크립트가 공개되어 있지 않다(`tools/`는 MMDetection 원본 범용 도구들이며 OWOD 지표 평가 코드는 확인되지 않음). (4) `faster_ipow_backup.py`처럼 정리되지 않은 백업 파일이 그대로 남아 있다. 종합하면 "핵심 아이디어의 뼈대 코드는 실재하지만 논문 결과를 그대로 재현 가능한 완결된 릴리스는 아닌 stub에 가까운 부분 구현"이다.
- CGR의 하이퍼파라미터 $\eta$(교정 강도)와 shared concept 개수 $K+M$의 민감도, LLM이 뽑은 concept의 오류(속성 오분류)가 전체 성능에 미치는 영향에 대한 별도 분석은 확인한 범위에서 두드러지지 않는다.
- Discriminative/shared 부분공간의 직교성은 고정 직교 행렬 $\mathbf{Q}_{\mathcal{U}}, \mathbf{Q}_{\mathcal{V}}$로 강제되는데, 이 행렬을 어떻게 구성하는지(무작위 초기화인지 학습되는지)에 대한 상세는 확인한 본문 범위에서 명확히 드러나지 않았다.

## 7. 원문 기반 핵심 문장
> "we propose a concept-driven InterPretable OWOD framework (IPOW) by introducing a Concept Decomposition Model (CDM) for OWOD, which explicitly decomposes the coupled RoI features in Faster R-CNN into discriminative, shared, and background concepts... Leveraging the interpretable framework, we identify that known–unknown confusion arises when unknown objects fall into the discriminative space of known classes. To address this, we propose Concept-Guided Rectification (CGR) to further resolve such confusion."

> "known objects must exhibit full-set activation of their predefined semantic concepts, whereas unknown objects may fall into the discriminative space $\mathcal{U}$ of known categories but typically trigger only partial activation within the shared space $\mathcal{V}$."
