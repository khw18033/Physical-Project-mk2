# DEUS: Detecting Unknown Objects via Energy-based Separation for Open World Object Detection

## 메타데이터
- categories: ETF 기반 Unknown Subspace 분리, Energy-based Known Distinction Loss, [[Open World Object Detection]]
- domain: [[객체 탐지·분할]], [[지속학습]]
- source: Heo, Jun-Woo, Park, Keonhee, Park, Gyeong-Moon. "Detecting Unknown Objects via Energy-based Separation for Open World Object Detection." IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2026.
- url: https://arxiv.org/abs/2603.29954 (arXiv preprint) / https://openaccess.thecvf.com/content/CVPR2026/papers/Heo_Detecting_Unknown_Objects_via_Energy-based_Separation_for_Open_World_Object_CVPR_2026_paper.pdf (공식 CVPR 2026 proceedings, 직접 fetch는 403으로 차단됨 — arXiv 사본으로 내용 확인)
- year: 2026
- authors: Jun-Woo Heo, Keonhee Park (공동 1저자), Gyeong-Moon Park (교신저자) — Korea University / Seoul National University
- venue: IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR 2026), Denver, 2026-06-03~07

## 1. 핵심 요약
- **검증된 게재 상태**: 협업자가 제시한 "CVPR 2026" 주장은 정확했다. CVPR 2026은 2026-06-03~07 Denver에서 이미 개최되었고(오늘 날짜 2026-09-07 기준 과거), openaccess.thecvf.com에 `CVPR2026` 경로로 정식 게재된 논문이 존재한다. arXiv 버전(2603.29954, v1: 2026-03-31, v2: 2026-05-28)의 abstract 코멘트에도 "Accepted at CVPR 2026"이 명시되어 있어 정식 accepted paper이며 단순 preprint나 under-review 상태가 아니다.
- Open World Object Detection(OWOD)에서 기존 방법들이 known class 예측(objectness/confidence)에만 의존해 unknown object를 놓치는 문제를 지적하고, DEUS는 (1) ETF-Subspace Unknown Separation(EUS)과 (2) Energy-based Known Distinction(EKD) loss 두 모듈을 결합해 unknown 탐지 성능을 크게 높이면서 known class 성능도 유지한다고 주장한다.
- M-OWODB/S-OWODB 표준 벤치마크에서 이전 최고 성능 방법(O1O) 대비 U-Recall(unknown recall)을 큰 폭으로 개선했다고 보고한다(예: M-OWODB Task 1 U-Recall 49.3→65.1).
- 공식 GitHub 코드 저장소는 확인되지 않았다(논문 본문·저자 개인 페이지 모두에 코드 링크 없음).

## 2. 문서 목적
- 해결하려는 문제: OWOD 모델이 known class에 대한 confidence/objectness 예측에만 의존해 unknown object를 탐지하기 때문에, known space만 보는 기존 energy 기반 접근이 unknown 고유의 패턴을 충분히 포착하지 못하는 문제.
- 기술적 목표: known/unknown 표현을 기하학적으로 분리된 subspace(ETF 기반)에 사영하고 두 subspace의 에너지를 함께 활용해 unknown을 더 명확히 분리하며, incremental task 간 classifier 지식 간섭(catastrophic forgetting/interference)을 에너지 기반 대비 손실로 줄이는 것.
- 다루는 범위: EUS 모듈의 ETF 기하 구조 설계, EKD loss의 energy score 정의와 pairwise 대비 항, M-OWODB·S-OWODB·자체 구축한 RS-OWODB(원격탐사, DIOR 기반) 벤치마크 평가.

## 3. 핵심 개념 상세

### Energy-based Known Distinction (EKD) — "Energy-based Known Distinction"의 실제 정의
- 원문 표현(arXiv HTML 발췌): "the negative energy-based score as follows: S(f;H) = −E(f;H) = log∑exp(z_c(f;H))" — 여기서 H는 이전 task 또는 현재 task의 sub-classifier(logit head)를 가리킨다. 즉 표준 energy-based OOD detection에서 쓰는 log-sum-exp negative energy를 classifier head 단위로 재정의한 것이다.
- Loss 구성: 두 개의 pairwise 항을 사용한다.
  - 이전 task의 proposal에 대해서는 `S(f_prev; H_curr) − S(f_prev; H_prev)`가 커지는 것을 penalize.
  - 현재 task의 proposal에 대해서는 `S(f_curr; H_prev) − S(f_curr; H_curr)`가 커지는 것을 penalize.
  - 두 항 모두 `log(1+exp[score_difference])` 형태의 소프트-마진 대비 손실로 구성되어, 이전/현재 classifier가 서로의 영역을 침범하는 "cross-interference"를 최소화한다.
- 역할: 이름과 달리 "known/unknown 분리" 자체보다는 memory replay 과정에서 신규 task 학습이 기존 task의 known-class 지식을 훼손하지 않도록(=incremental 단계 간 지식 간섭 억제) 만드는 손실이다. known vs unknown의 1차 분리는 EUS가 담당하고, EKD는 그 위에서 task 간 classifier 충돌을 줄이는 보조 역할로 이해된다.

### ETF-Subspace Unknown Separation (EUS) — "unknown separation" 아키텍처
- Simplex Equiangular Tight Frame(ETF)을 이용해 두 개의 고정(non-learnable) 기하학적 subspace를 구성한다: known subspace `W^E_K`(K/2개의 ETF basis vector)와 unknown subspace `W^E_U`(나머지 K/2개 vector). 두 subspace는 서로 직교(orthogonal)하도록 설계된다.
- 각 subspace에 대한 에너지 점수를 `E^K(f) = −log∑exp(W^E_{K,i}·f)` (unknown subspace도 동일한 형태)로 계산하고, 두 에너지의 차이(margin) `Δ_u(f)`를 정의해 known proposal은 `Δ_u(f) ≤ −m`, pseudo-unknown proposal은 `Δ_u(f) ≥ m`이 되도록 강제하는 energy-based margin loss를 사용한다.
- 여기에 background proposal을 known/unknown 경계 쪽으로 유도하는 focal loss 항을 추가로 결합한다.
- 선정 이유(논문 주장): 기존 energy 기반 방법들은 known space의 에너지만 보고 unknown을 "known이 아닌 것"으로 간접 추론하는 반면, EUS는 known/unknown 두 subspace의 에너지를 모두 명시적으로 사용해 unknown 고유의 분포 패턴을 직접 포착한다고 주장한다.

### 기반 검출기(base detector)
- 웹 검색 도구의 자동 요약 결과에 따르면 DEUS는 OrthogonalDet을 기반 검출기로 사용하며(objectness/classification/box regression branch 포함), 구현 프레임워크로 MMDetection이 언급된다. 이 두 정보는 원문을 직접 열람해 대조하지 못하고 자동 추출 도구의 요약에 의존했으므로 정확한 표현(특히 MMDetection이 구현 도구인지 별도 언급인지)은 추가 확인이 필요하다.

## 4. 구조 및 흐름
1. Backbone/detector(OrthogonalDet 계열로 추정)가 각 proposal의 feature `f`를 추출한다.
2. EUS가 고정된 ETF 기반 known/unknown subspace에 대해 각각 energy score를 계산하고, margin loss + focal loss로 known/unknown/background 경계를 학습(단, subspace 자체는 학습되지 않고 고정).
3. Incremental task가 진행되며 새로운 known class가 추가될 때, memory replay 데이터에 대해 EKD loss가 이전 task classifier(H_prev)와 현재 task classifier(H_curr) 간 energy score 차이를 대비 손실로 억제해 지식 간섭을 줄인다.
4. M-OWODB(4 task)·S-OWODB(4 task) 표준 프로토콜과 자체 구축 RS-OWODB(DIOR 기반 원격탐사 벤치마크)로 known mAP·U-Recall·H-Score를 평가한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| DEUS는 M-OWODB에서 이전 최고 방법(O1O) 대비 U-Recall을 크게 개선한다 | Task 1: mAP 66.2 / U-Rec 65.1 (O1O: mAP 65.1 / U-Rec 49.3); Task 2: mAP 53.3 / U-Rec 66.2 (O1O: 53.0 / 50.3); Task 3: mAP 50.5 / U-Rec 69.0 (O1O: 46.2 / 49.5); Task 4: mAP 46.0 (O1O: 42.4). Task 4는 OWOD 표준 프로토콜상 held-out unknown class가 남지 않아 U-Recall이 보고되지 않는다. |
| S-OWODB에서도 known 성능을 유지하며 unknown recall이 개선된다 | Task 1: mAP 71.6 / U-Rec 68.7 (O1O: 72.6 / 49.8); Task 2: mAP 52.7 / U-Rec 62.9; Task 3: mAP 50.7 / U-Rec 60.7; Task 4: mAP 48.8 (O1O: 45.9). |
| known/unknown 두 subspace 에너지를 함께 쓰는 것이 known space만 보는 기존 energy 기반 방법(ORE, PROB, Unknown Sniffer, OWOBJ 등)보다 우수하다 | 위 표에서 ORE·OW-DETR·PROB·OrthogonalDet 대비 전 task에서 U-Recall이 큰 폭으로 높다(예: M-OWODB Task 1 U-Rec: ORE 4.9, OW-DETR 7.5, PROB 28.3, OrthogonalDet 36.3 → DEUS 65.1). |

## 6. 한계 및 부족한 점
- **원문 직접 열람 제약**: `openaccess.thecvf.com`의 공식 CVPR 2026 PDF는 403 Forbidden으로 직접 fetch가 차단되어, 본 요약은 arXiv HTML 사본(2603.29954v2)에 대한 자동 추출 도구(WebFetch, 내부적으로 소형 모델이 요약)의 결과에 의존했다. 수식·표는 재구성된 것이므로 최종 공식본과 사소한 표기 차이가 있을 수 있다.
- 위 이유로 표 일부 항목(예: 초기 조회에서 나온 "Task 4 U-Recall 32.8"이라는 값)은 재조회 시 "—"(미보고)로 정정되었다 — 자동 요약 도구의 1차 추출에 오류가 있었음을 확인했고, 표준 OWOD 프로토콜(Task 4는 unknown class가 남지 않음)과 일치하는 2차 추출값을 채택했다. 이런 수치 불일치가 있었다는 사실 자체를 한계로 명시한다.
- 기반 검출기가 정확히 OrthogonalDet인지, MMDetection은 구현 툴킷인지 별도 백본인지는 자동 요약 간에도 약간의 표현 차이가 있어 확정적으로 확인하지 못했다.
- **공식 코드 저장소 없음**: 논문 본문에도, 교신저자 Gyeong-Moon Park의 개인 연구실 페이지(gyeongmoon.github.io)의 출판물 목록에도 DEUS에 대한 GitHub/코드/프로젝트 페이지 링크가 없다. 즉 2026-09-07 기준 공개 구현체는 확인되지 않는다.
- RS-OWODB(원격탐사 벤치마크)에 대한 구체적 수치는 이번 조사에서 추출하지 못했다(M/S-OWODB 표만 확보).

## 7. 원문 기반 핵심 문장
> "S(f;H) = −E(f;H) = log∑exp(z_c(f;H))" — Energy-based Known Distinction의 negative energy score 정의 (arXiv 2603.29954v2 자동 추출).

> "Accepted at CVPR 2026" — arXiv abstract 페이지에 명시된 게재 상태 코멘트.
