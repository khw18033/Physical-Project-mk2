# 사람이 개입하는 데이터·가중치 관리 — 기존 연구 조사와 채택 판단

상태: 조사 및 채택 결정 기록 (2026-11-04).
요구사항: **AI-L-01** (학습 필요성·후보 선별), **AI-L-02** (후보 격리·품질), **AI-L-03**
(사용자 확인·의미 정보 반영), **AI-L-05** (검증·기존 지식 보존), **AI-L-06** (관리자 판단
정보), **AI-L-07** (단계적 적용·롤백), **AI-L-08** (학습·적용 계보), **AI-L-09** (운영
스트림 학습), **AI-L-10** (조건 기반 모델 배정).
관련 AI-B-01(실행 구성 신원과 측정), AI-B-09(새 조합은 재검증), AI-C-16(폐쇄망 조달),
AI-C-19(권한 경계), AI-S-03/04(근거 충분도·미확인 객체), AI-O-05(미측정 ≠ 0).
구현 위치: `continual/stream_learning.py`, `continual/parameter_evaluation.py`,
`continual/lineage.py`, `continual/operational_stream.py`, `continual/stream_ingest.py`,
`continual/{h2st,dgs,ekya,replay,p2iod}.py`, `runtime/learned_version.py`,
`runtime/model_assignment.py`, `runtime/mlops_pipeline.py`, `runtime/model_trial.py`,
`contracts/profile.py`(§`ExecutionConfiguration`), `tools/fms_console/labeling.py`,
`tools/fms_console/{twin,deployment,overlay}.py`.
각 모듈 docstring 첫 줄의 `implements:` 가 정본이다.

이 문서가 하는 일은 `docs/research/automatic-camera-calibration.md` 와 같다 — **무엇이
최고인가가 아니라 우리 현장에서 입력이 실제로 들어오는 방법이 무엇인가**를 가리고, 들어오지
않는 방법은 왜 들어오지 않는지를 적는다. 다만 한 가지가 보정 조사와 다르다. 보정은
"추정값을 얻는가" 가 문제였고, HITL 데이터·가중치 관리는 **사람의 시간이 가장 비싼
자원**이라는 제약이 문제다. 그래서 거절 사유에 "품질이 낮다" 보다 "사람의 시간을 그만큼 쓸
근거가 없다" 가 더 자주 나온다.

AI-L 계열이 방법을 고르라고 하지 않는 것도 보정과 같다:

> AI-L-04: "학습 방법과 실행 위치를 특정 알고리즘이나 특정 온디바이스·엣지·서버에 고정해서는
> 안 된다."
> AI-L-09: "특정 학습 프레임워크·최적화 방법을 핵심 계약의 필수 의존성으로 두어서는 안 된다."

---

## 1. 판정 기준 — 벤치마크가 아니라 우리 현장

각 기법은 자기 논문의 벤치마크 점수로 평가하지 않는다. 아래 여덟 줄로 평가한다.

| 축 | 우리 현실 |
|---|---|
| 라벨 예산 | **사람 한 명, 간헐적.** 관제 웹에서 저장된 프레임을 열어 상자를 고치는 것이 전부다(`tools/fms_console/labeling.py`). 라운드를 수십 번 도는 AL 루프를 돌릴 사람이 없다 |
| 데이터 | 대부분 **라벨 없는 운영 캡처.** `stream_data/<소스>/<실행>/` 의 연속 스트림이고 라벨 후보는 비전 모델의 검출에서 나온다 |
| 정답 | **깊이 정답이 없다.** 거리는 측정되지 않았고(`unmeasured_no_fitted_formula`) 대규모 라벨 집합도 없다. 공개 데이터셋은 `external_dataset` 출처로 따로 세고 기기 캡처와 섞지 않는다 |
| 연산 | 엣지 CPU + onnxruntime 기준. 말단은 추론·로컬 안전만(AI-B-10). 학습용 GPU 클러스터를 전제할 수 없다 |
| 조달 | 폐쇄망 프로파일에서는 공개 인터넷 내려받기가 **없다**(AI-C-16). 레지스트리 SaaS·모델 허브는 기능 전제가 될 수 없다 |
| 승격 | **검증되지 않은 추론 결과는 정답이 아니다**(AI-L-02). 사람 확인 또는 외부 라벨만 학습에 들어간다 |
| 사람의 확인 | 구성이 바뀌어도 살아남아야 한다 — 모델 교체가 "저것은 소화기다" 를 다시 묻게 만들면 안 된다(`contracts/profile.py::KnowledgeRecord.binding`) |
| 산출 | 측정한 것만 선언한다. 미측정은 0 도 미달도 아니다(AI-O-05). 그래서 "성능이 좋다" 가 아니라 "무엇을 어느 구성에서 쟀다" 만 쓸 수 있다 |

둘째·셋째 줄이 조사 결과를 가장 많이 걸러냈다. 문헌의 절대다수는 **큰 라벨 풀**과 **깨끗한
검증 집합**을 전제한다. 그 전제를 쓰는 기법은 틀린 것이 아니라 **우리에게 없는 것**이고, 이
문서는 두 거절 사유를 끝까지 구분한다 — 보정 조사가 GeoCalib 을 "품질 때문이 아니라 조달
때문에" 보류한 것과 같은 구분이다.

---

## 2. 이미 있는 것 — 정확한 경계

새로 무엇을 더할지 말하기 전에 있는 것부터 정확히 적는다. 과장하면 다음 사람이 없는 것을
있다고 믿는다.

**후보 생성**: `continual/operational_stream.py` 가 운영 스트림(디스크 run 폴더 + Redis
`vision_stream:<소스>:<모델>`)을 읽어 `StreamSample` 로 바꾼다. 비전 결과에서 온 것은 **예외
없이** `AUTO_INFERENCE` 이고, 이 모듈에 그것을 확인 상태로 바꾸는 함수가 없다.
`continual/stream_ingest.py` 는 회전 스캔 규약 전용 두 번째 입구이고, 중복 프레임이 하나라도
있으면 **판 전체를 버린다.**

**사람의 확인**: `tools/fms_console/labeling.py` 가 `predicted`(모델)와 `corrected`(사람)를
나란히 들고 IoU·중심 이동·class 변경을 계산한다. `BoxVerdict` 여섯(`UNREVIEWED` /
`CONFIRMED` / `ADJUSTED` / `RELABELED` / `REJECTED` / `ADDED`)이 "지운 것" 과 "손대지 않은
것" 을 가른다. `tools/fms_console/twin.py` 가 운영자 정정을 `HUMAN_CONFIRMED` 후보로 올리고
계보를 연다. 운영자 수정은 선언을 덮지 않고 append-only 장부에 쌓인다(`overlay.py`).

**학습**: `continual/stream_learning.py` 가 `LearningProvider` 경계를 세우고 기본 구현은
`PrototypeLearningProvider`(클래스별 특징 평균 프로토타입 + 유사도 하위 분위 임계)다.
**기울기 학습이 아니다.** 후보는 `InputConditions.group_key`(기기·카메라·해상도·가속기)별로
분리 보관되고 `ParameterSet.version` 은 내용 sha256 이다.

**검증**: `continual/parameter_evaluation.py` 가 `new`(새 집합)와 `regression`(기존 집합의
기준 대비 하락)을 **두 축으로 따로** 재고 둘 다 통과해야 PASS 다. 평가 집합이 없으면
`NOT_MEASURED` 이고 PASS 가 아니다.

**승격·배포**: `runtime/learned_version.py` 가 게이트를 통과한 후보를 `ModelVersion` 으로
등록하고 네 가지를 거절한다(미통과 / 성적표-후보 불일치 / 다른 기기 검증 범위 / 미측정
지연·메모리). `runtime/model_assignment.py` 가 검증 범위 안에서만 배정하고,
`runtime/mlops_pipeline.py` 가 `VERIFICATION → … → OPERATIONAL` 로 넓히며 구버전을 나란히
남긴다. `continual/lineage.py` 가 그 전부를 append-only 상태기계로 적는다.

**비교**: `runtime/model_trial.py` 가 정답 없는 프레임의 비교를 `descriptive` 로 두고 **우열을
말하지 않는다.**

**없는 것 — 이 조사의 범위다**:

1. **사람에게 무엇을 보여줄지 고르는 것이 없다.** `FrameLabelSource._listing()` 은 프레임을
   **파일명 정렬**로 내고 `MAX_LISTED_FRAMES = 300` 에서 자른다. 획득 함수(acquisition)가 없다.
2. **확인된 음성을 쓰는 자리가 없다.** `REJECTED`(거짓 양성이라는 정답)는 라벨이 `"absent"`
   문자열이 되고, 학습기·평가기 어디에도 "이것은 그 클래스가 아니다" 를 받는 칸이 없다.
   `ConfirmedAcceptanceScorer` 의 docstring 이 이 공백을 스스로 적고 있다.
3. **표본 단위 회귀가 없다.** 회귀는 `baseline.ratio - retained.ratio` 로 **집계**다.
4. **학습 데이터의 내용 신원이 없다.** 계보는 `sample_ids` 를 적지만 그 표본의 **라벨 내용**을
   가리키는 해시가 없다. 같은 표본이 뒤에 다시 라벨되면 같은 id 가 다른 정답을 가리킨다.
5. **관리자 판단 정보 묶음이 없다.** AI-L-06 이 열거한 항목(학습 사유·데이터 출처·대표 사례·
   성능 변화·알려진 실패·검증/미검증 범위·복구 가능한 이전 버전)을 **한 자료형으로** 내는
   자리가 없다.
6. **가중치 파일의 무결성·서명이 없다.** `runtime/airgap.py` 가 조달 경로를 검사하지만 모델
   산출물 자체의 서명·검증 단계가 없다.
7. **사람 둘 이상이 같은 프레임을 보는 경로가 없다.** `labeled_by` 는 한 칸이다.
8. **drift 감지가 라벨을 요구한다.** `continual/h2st.py` 는 특징 2표본 검정이라 라벨이 필요
   없지만, 호출자가 참조 특징을 미리 등록해야 한다. 운영 중 자동으로 도는 경로가 없다.

---

## 3. 사람에게 무엇을 보여줄 것인가 — 능동 학습

### 3.1 불확실성 계열(엔트로피·margin·least-confidence)과 그 실패 모드

- 조망: [A Survey on Deep Active Learning: Recent Advances and New Frontiers,
  arXiv 2405.00334](https://arxiv.org/pdf/2405.00334);
  [Deep Active Learning for Computer Vision: Past and Future, arXiv 2211.14819](https://arxiv.org/pdf/2211.14819).
- **cold start**: 첫 라운드 예산이 작으면 전략이 **무작위보다 나쁘다.** 비전 쪽 보고는
  [Bai et al., To Address Cold Start Problem in Vision Active Learning,
  arXiv 2210.02442](https://arxiv.org/pdf/2210.02442), 의료영상 쪽은
  [HaCon, PMLR v227](https://proceedings.mlr.press/v227/chen24a/chen24a.pdf). 원인으로 지목된
  것은 편향된 첫 질의이고, 그 편향이 다음 라운드의 모델로 이어져 복리로 커진다.
- **표집 편향**: 라벨된 집합이 원 분포에서 뽑힌 것이 아니게 되어 **불편 평가와 모델 선택이
  어려워진다** — 이 지적의 출처는
  [Navigating the Pitfalls of Active Learning Evaluation, arXiv 2301.10625](https://arxiv.org/pdf/2301.10625)
  이고, 같은 논문이 **질의 크기(query size)** 가 결과를 좌우한다고 적는다(작은 질의 크기가
  BALD 의 cold-start 에 대한 효과적 대응이었다고 보고). 같은 평가에서 **다섯 데이터셋 전부에서
  무작위를 일관되게 이긴 방법은 없었다**고도 보고한다 — 벤치마크 결론을 그대로 옮기지 말라는
  경고로 읽어야 한다.
- 판정: **미채택(불확실성 단독).** 거절 사유는 품질이 아니라 **우리가 정확히 cold-start
  구간에 있다**는 것이다. 사람의 확인이 아직 수십 건 단위이므로 문헌이 "무작위보다 나쁘다" 고
  보고한 그 구간이다. 그리고 우리가 비교해야 하는 기준선은 무작위조차 아니다 — §9.1 을 보라.

### 3.2 BADGE (Ash, Zhang, Krishnamurthy, Langford, Agarwal, ICLR 2020)

- 마지막 분류층에 대한 교차엔트로피 **기울기 임베딩**(의사 정답은 모델의 최빈 예측)을 만들고
  거기에 **k-means++ 초기화**를 적용해 중심에 해당하는 표본을 고른다. 기울기 크기가
  불확실성을, 기울기 공간의 분리가 다양성을 준다. **손으로 맞추는 하이퍼파라미터 없이**
  둘을 절충하는 것이 기여다.
  ([arXiv 1906.03671](https://arxiv.org/pdf/1906.03671),
  [ICLR 페이지](https://iclr.cc/virtual_2020/poster_ryghZJBKPS.html),
  [code](https://github.com/JordanAsh/badge))
- arXiv 2301.10625 는 BADGE 가 **모든 질의 크기에서 실패 모드 없이** 일관되게 좋았다고
  보고한다(조건: 그 논문의 평가 틀, 분류 과제).
- 판정: **미채택(설계 입력으로는 1순위).** 거절 사유는 **없는 것**이다 — 기울기 임베딩은
  분류층의 역전파를 요구하고 우리 기본 학습기는 기울기를 쓰지 않는다(§8). 다만 BADGE 의
  **구조**(불확실성 × 다양성을 한 번에, 임계 없이, 군집 초기화로)는 기울기 없이도 옮길 수
  있다 — 프로토타입 공간에서 `1 - cos(x, prototype)` 로 가중한 k-means++ 가 같은 모양이고,
  그것은 §12 의 제안이다.

### 3.3 Core-set (Sener & Savarese)

- 라벨된 집합이 풀 전체 분포를 덮도록 **k-center-greedy** 로 고른다. 전수로 확인하지 못하고
  2차 자료를 통해서만 확인했다(arXiv 2211.14819 의 다양성 표집 절에서 인용).
- 판정: **미채택.** 거절 사유는 비용이다 — k-center-greedy 는 풀 전체의 쌍 거리를 요구하고,
  우리 "풀" 은 운영 캡처 전체(300 장 잘림이 아니라 수만 프레임)다. 엣지 CPU 에서 라벨 화면을
  열 때마다 돌 비용이 아니다. 다양성 축 자체는 §3.2 로 더 싸게 얻는다.

### 3.4 탐지 전용 능동 학습 — 상자 단위인가 영상 단위인가

이 절이 우리에게 가장 직접적이다. 우리 과제는 분류가 아니라 **탐지**이고, 사람이 보는 단위도
상자가 아니라 **프레임**이다.

- Kao et al., **Localization-Aware Active Learning**: 분류 불확실성은 **영상 안 모든 상자의
  최댓값**으로 잡고, 국소화는 **tightness**(상자가 얼마나 꽉 끼는가)와 **stability**(입력에
  잡음을 넣었을 때 IoU 가 유지되는가)로 잰다
  ([arXiv 1801.05124](https://arxiv.org/pdf/1801.05124)).
- Choi et al., ICCV 2021: 국소화와 분류 불확실성을 확률 모형으로 함께 두고 영상마다 정규화된
  불확실성 네 값을 얻는다. **두 불확실성을 합치는 것이 영상 선택을 개선**했다고 보고
  ([CVF PDF](https://openaccess.thecvf.com/content/ICCV2021/papers/Choi_Active_Learning_for_Deep_Object_Detection_via_Probabilistic_Modeling_ICCV_2021_paper.pdf)).
- **Box-Level Active Detection**: 영상 단위 평가가 편향돼 있다고 지적하고, **예측 객체
  밀도만 세는 `BoxCnt` 라는 단순 기준선이 영상 단위 예산에서 정교한 AL 기법들을 일관되게
  앞선다**고 보고한다 ([arXiv 2303.13089](https://www.alphaxiv.org/abs/2303.13089)).
- DeLR 은 상자 단위로 국소화·분류 불확실성을 각각 재서 **상자 확인과 class 확인 중 어느 것을
  사람에게 물을지**를 가른다 ([arXiv 2312.16931](https://arxiv.org/pdf/2312.16931)).
- 판정: **부분 채택 — `BoxCnt` 계열(검출 수/밀도 기반 프레임 순위)만.** 이유는 §1 의 첫 줄과
  §3.1 의 cold start 다. 우리에게 지금 필요한 것은 "최적 획득 함수" 가 아니라 **파일명 정렬보다
  나은 아무것**이고, 문헌이 "정교한 것들을 일관되게 앞섰다" 고 보고한 가장 단순한 기준선이
  마침 **추가 데이터도 추가 모델도 요구하지 않는다** — 검출 수는 `results.jsonl` 에 이미 있다.
  tightness/stability 와 Choi 의 확률 모형은 **미채택**이고 사유가 각각 다르다: stability 는
  프레임당 여러 번 추론해야 해서 엣지 CPU 예산 밖이고(zipdepth 단독으로 384 입력에서 219.7 ms
  — AI-B-01 행의 실측), Choi 는 탐지기 자체를 확률 모형으로 다시 학습해야 해서 우리에게
  **없는 것**이다. DeLR 의 "상자를 물을까 class 를 물을까" 분리는 우리 `BoxVerdict` 가 이미
  `ADJUSTED` 와 `RELABELED` 로 갈라 두고 있어 **설계가 수렴한 자리**다.

---

## 4. 라벨 품질과 불일치

### 4.1 사전 라벨이 사람을 끌어당긴다 — anchoring

우리 라벨 책상은 모델 상자를 먼저 그려 주고 사람이 고치게 한다. 그것이 **정확히** anchoring
문헌이 경고하는 배치다.

- [Bias in the Loop: How Humans Evaluate AI-Generated Suggestions, *Harvard Data Science
  Review* 8.2 (2026)](https://hdsr.mitpress.mit.edu/pub/nrcn4h7d/release/2) 는 사전 라벨을
  판정하는 작업자를 연구해 **자동화에 더 회의적인 작업자가 시스템 오류를 더 많이 잡았다**고
  보고한다. 저자들은 자기 모형 결과가 다소 모호하다고 적는다 — 그 유보를 함께 옮긴다.
- 불확실성 기반 검수 연구는 automation bias 를 "신뢰할 만하다고 표시된 출력을 과신하고 표시되지
  않은 것의 검사를 멈추는 경향" 으로 정의한다
  ([arXiv 2605.12303](https://arxiv.org/pdf/2605.12303), 2026 preprint).
- 판정: **채택(측정 항목으로).** 알고리즘이 아니라 **지표**를 받는다. 우리 `BoxVerdict` 는
  `CONFIRMED`(모델이 맞았다)를 이미 따로 세고 `summary()` 가 `by_verdict` 로 낸다. 그러면
  **작업자별 `CONFIRMED` 비율**이 곧 수락률이고, 그것이 1.0 에 붙으면 "모델이 완벽하다" 가
  아니라 "검수가 끝까지 보지 않았다" 의 신호다. 이 해석을 쓸 수 있는 이유는 우리가 이미
  `UNREVIEWED` 를 GT 에서 빼 두었기 때문이다 — 안 본 것과 보고 맞다고 한 것이 섞여 있으면
  수락률이 아무것도 말하지 않는다.
- **주의해서 적는다**: 이 사실은 AI-L-02 의 경계를 약화시킨다. 코드에서 `confirmed` 는
  이진값이고 "사람이 확인했다" 는 강한 보증처럼 읽힌다. anchoring 문헌은 그 보증이 **모델이
  이미 맞다고 말한 것에 대해서는 약하다**고 말한다. 자료형을 바꿀 문제가 아니라 **수락률을
  관리자 판단 정보(AI-L-06)에 적어 사람이 그 약함을 알게 할 문제**다.

### 4.2 불일치는 잡음이 아니라 신호다

- [Learning from Disagreement: A Survey (Uma et al., *JAIR*)](https://www.jair.org/index.php/jair/article/download/12752/26751/29240)
  가 이 계열의 조망이다. 초기 NLP 는 불일치를 제거할 잡음으로 다뤘고, 이후 연구는 해석 변이를
  나타내는 의미 있는 신호로 모형화한다. 구호("disagreement is signal, not noise")의 출처는
  Aroyo & Welty 계열이다.
- **약한 관점주의 / 강한 관점주의**(Basile et al. 2021 계열): 전자는 작업자 차이를 인정하되
  단일 라벨로 집계하고, 후자는 집계를 버리고 **분포 자체를 대상으로** 둔다. 조망은
  [Beyond Consensus, arXiv 2601.09065](https://arxiv.org/pdf/2601.09065) (2026 preprint).
  LeWiDi 공동과제는 다수결이 아니라 **작업자 분포의 재현**으로 시스템을 평가했다.
- 반대편 증거도 적는다: 불일치는 주관성·모호성·개념 난이도에서도 오고 **항목이나 지침이
  나쁜 신호일 수도** 있어서 신호와 잡음을 가르는 모형이 드물다
  ([arXiv 2604.19943](https://arxiv.org/html/2604.19943)). 다중라벨 감정 주석의 2026
  preprint 는 **hard label 이 F1 을 최대화하고 soft 감독은 다른 절충을 준다**고 보고한다
  ([arXiv 2606.21069](https://arxiv.org/pdf/2606.21069)) — 즉 soft label 의 이득은
  **지표에 달려 있다.**
- 판정: **미채택 — 우리에게 **없는** 것이다.** 사람이 한 명이고 `labeled_by` 가 한 칸이므로
  사람-사람 불일치가 구조적으로 발생하지 않는다. 중요한 것은 **왜 이것이 공백으로 남아도
  되는지**다: 우리가 들고 있는 불일치는 다른 축이다 — `predicted` 대 `corrected`, 즉
  **모델-사람** 불일치다. §4.4 가 그것이 문헌이 수렴한 모양인지 따진다.

### 4.3 라벨 오류 탐지 — confident learning

- [Northcutt, Jiang, Chuang, "Confident Learning: Estimating Uncertainty in Dataset Labels",
  *JAIR* 70:1373–1411 (2021)](https://www.jair.org/index.php/jair/article/view/12125)
  ([arXiv 1911.00068](https://arxiv.org/pdf/1911.00068)): 관측된(잡음 섞인) 라벨과 미지의
  참 라벨의 **결합분포를 직접 추정**한다. 가정은 **class-conditional 잡음**이고, 절차는
  잡음 가지치기 → 확률 임계로 세기 → 학습 표본 순위화다. 구현은
  [cleanlab](https://github.com/cleanlab/cleanlab).
- [Pervasive Label Errors in Test Sets Destabilize ML Benchmarks (NeurIPS 2021 D&B,
  arXiv 2103.14749)](https://arxiv.org/pdf/2103.14749): 흔히 쓰는 **10개 벤치마크의 시험
  집합**에 confident learning 을 돌리고 그 후보를 crowdsourcing 으로 사람이 검증했다. 결과는
  **평균 하한 3.3% 라벨 오류**이고 **알고리즘이 표시한 후보 중 51% 가 실제 오라벨로 확인**됐다.
  조건을 함께 적는다: 이 수치는 **시험 집합**이고 **분류** 과제이며 **crowdsourcing 검증**을
  통과한 것이고, 51% 라는 정밀도는 "사람이 봐야 할 후보의 절반은 헛수고" 라는 뜻이다. 하한
  수치는 arXiv 판(3.3%)과 학위논문·요약(3.4%)이 다르게 적으므로 인용할 때 판본을 밝힌다.
- 판정: **미채택(현재), 보류(후보 집합이 커지면 1순위).** 거절 사유는 **없는 것**이다 —
  confident learning 은 표본별 **out-of-sample 예측 확률**과 클래스마다 충분한 표본 수를
  요구하고, 우리 확인 후보는 조건 묶음별로 수십 건이라 결합분포 추정의 표본이 아니다. 그리고
  51% 정밀도는 사람의 시간이 가장 비싼 우리 배치에서 **지금은** 지불할 수 없는 값이다. 다만
  문헌이 주는 교훈 하나는 조건 없이 옮길 수 있다: **우리 자신의 정답에도 오류가 있다**는 것을
  자료형이 부정하지 않아야 한다. `labeling.py` 가 GT 를 덮어쓰지 않고 `GroundTruthRecord` 로
  쌓고 `overlay.py` 가 append-only 인 것이 그 대비다.

### 4.4 `predicted` 옆에 `corrected` — 문헌이 수렴한 모양인가

task 가 묻는 질문에 직접 답한다. **그렇다, 다만 이유가 라벨 품질 쪽이 아니다.**

- 라벨 품질 문헌(§4.2)이 나란히 두라고 하는 것은 **여러 사람의** 라벨이다. 우리가 나란히 둔
  것은 모델과 사람이므로 그 수렴이 아니다.
- 수렴은 **탐지 능동 학습**과 **회귀 없는 모델 갱신**에서 온다. 전자는 상자 수정량을 학습
  가치로 쓰고(§3.4 의 tightness, DeLR 의 상자/class 분리), 후자는 **표본별 변화**를 보라고
  한다(§7.2 의 negative flip). 둘 다 `predicted` 를 지우면 계산이 불가능하다. 즉
  `labeling.py` docstring 의 근거("틀린 정도가 바로 학습 가치")는 문헌과 같은 결론이다.
- 더해야 할 것이 하나 있다. **사람의 상자 자체에 잡음이 있다.**
  [Label Convergence, arXiv 2409.09412](https://arxiv.org/pdf/2409.09412) 는 탐지·instance
  segmentation 의 실제 주석 변이를 다섯 데이터셋에서 분포로 내고 **수정 mAP 와 작업자 간
  일치도를 묶어 성능 상한을 추정**한다. 같은 논문이 Cohen's Kappa·Krippendorff's Alpha 를
  탐지에 그대로 쓰기 어렵다고 적는다(국소화를 셈해야 하기 때문).
  [Noise-Aware Evaluation of Object Detectors (WACV 2025)](https://openaccess.thecvf.com/content/WACV2025/papers/Llerena_Noise-Aware_Evaluation_of_Object_Detectors_WACV_2025_paper.pdf)
  는 COCO 에서 모서리별 주석 잡음을 추정해 **noise-aware IoU** 를 만든다.
  [Drawing the Same Bounding Box Twice?, arXiv 2309.09742](https://arxiv.org/html/2309.09742)
  는 반복 라벨로 정답을 추정하고 변이가 과제 난이도·작업자 일관성·예산에 달려 있다고 보고한다.
  (반면 "40% 상자 잡음에서 평균 IoU 0.45" 같은 수치의 출처
  [arXiv 2003.01285](https://arxiv.org/pdf/2003.01285)는 **합성 잡음** 연구이므로 사람 변이의
  근거로 쓰면 안 된다.)
- 판정: **채택(해석 규약으로).** `disagreement()` 의 IoU 는 **사람 변이의 바닥 위에서만**
  뜻이 있다. 지금 코드는 IoU 를 그냥 내고 임계가 없어서 이 문제가 **아직** 없다. 임계를 두는
  날(예: "IoU < 0.7 이면 어려운 사례") 그 임계는 문헌 수치가 아니라 **우리 작업자가 같은
  프레임을 두 번 라벨한 실측**에서 나와야 한다. 그 실측이 없으므로 §11 에 남긴다.

### 4.5 약지도 / 프로그램적 감독 — Snorkel

- [Ratner et al., "Snorkel: Rapid Training Data Creation with Weak Supervision", VLDB 2017
  (arXiv 1711.10160)](https://arxiv.org/pdf/1711.10160): 사람이 라벨을 그리는 대신 **라벨링
  함수**를 쓴다(기권 가능). 생성 모형이 **정답 없이** 함수들의 일치·불일치에서 각 함수의
  정확도와 함수 간 상관을 추정해 확률적 학습 라벨을 만들고, 그것으로 판별 모형을 학습해
  라벨링 함수를 넘어 일반화한다. 생성 모형을 적합할 가치가 있는지 다수결로 충분한지를
  heuristic 으로 가른다. 확장판은
  [VLDB Journal 2020](https://cs.brown.edu/people/sbach/files/ratner-vldbj20.pdf).
  "과제당 11~33개 라벨링 함수로 대규모 수작업 라벨 모델의 3.60% 안" 이라는 수치는 **2차
  자료에서만 확인**했고 원문으로 검증하지 못했다.
- 판정: **미채택.** 거절 사유는 품질이 아니라 **적용 지점이 없다**는 것이다. 라벨링 함수는
  "문서에 '폐암' 이 있으면 양성" 처럼 **값을 읽어 규칙으로 라벨을 만드는** 과제에 맞는다.
  우리 과제는 "이 상자가 소화기인가" 이고, 그것을 규칙으로 쓸 수 있으면 애초에 탐지기가 필요
  없다. 그리고 결정적으로 **라벨링 함수의 출력은 검증되지 않은 자동 라벨**이다 — 그것을 학습
  정답으로 승격하는 것이 AI-L-02 가 금지하는 바로 그 일이다. 설계 참고로 남길 가치가 있는
  한 가지는 **기권(abstain)을 1급 상태로 두는 것**이고, 우리는 그것을 이미 가지고 있다
  (`PrototypeScorer.predict` 가 임계를 넘는 것이 없으면 `None` 을 내고 가장 가까운 클래스를
  억지로 붙이지 않는다 — AI-S-04 와 같은 판단).

### 4.6 선택적 예측 / 사람에게 넘기기 — conformal, learning to defer

- conformal prediction 은 **교환가능성(exchangeability)** 가정 아래 분포 무관·유한표본 coverage
  보증을 준다. 선택적 예측과 묶은 최근 작업:
  [Selective Conformal Risk Control, arXiv 2512.12844](https://arxiv.org/abs/2512.12844)
  (확신 있는 표본만 받아들이고 그 부분집합에 risk control 을 적용, 거절은 큰 예측집합 대신
  **이월**),
  [No Need for Learning to Defer?, arXiv 2509.12573](https://arxiv.org/html/2509.12573v3)
  (재학습 없이 conformal 집합만으로 여러 전문가에게 이월; **단일원소 예측집합**을 혼자 처리해도
  좋다는 증거로 본다),
  [비용 민감 conformal + HITL abstention, arXiv 2607.27143](https://arxiv.org/pdf/2607.27143)
  (class-conditional/Mondrian 집합과 비용 최소화를 묶어 사람에게 보낼 **손익분기 임계**를 유도).
- 임상 triage 쪽 적용은 [*Scientific Reports* (2026)](https://www.nature.com/articles/s41598-026-40637-w)
  이고, 같은 논문이 **분포 변화 아래에서 교환가능성 가정이 긴장된다**고 적는다.
- 사람 쪽 효과는 엇갈린다 — conformal 집합을 검수자에게 보여 주는 것이 팀 성능을 올렸다는
  보고와 자동으로 결정을 개선하지는 않는다는 유보가 함께 있다
  ([arXiv 2608.14617](https://arxiv.org/pdf/2608.14617), 2026 preprint).
- 판정: **미채택(보류).** 거절 사유는 **없는 것**이고 그 없는 것이 정확히 무엇인지가 중요하다 —
  conformal 은 **교정 집합(calibration set)** 을 요구하고, 그 집합은 시험 자료와 교환가능해야
  한다. 우리에게는 보류 집합이 조건 묶음별로 수 건이고(§2 의 `_split_for_holdout`), 그것으로
  유한표본 보증을 주장하면 보증의 형식만 빌리고 내용은 없다. **다만 이 계열이 AI-S-03(근거
  충분도)·AI-L-06(판단 정보)과 같은 질문을 풀고 있다**는 점은 기록해 둔다. 교정 집합을 모을
  수 있는 규모가 되면(§12 의 (b) 항목) 1순위 후보다.

---

## 5. 데이터셋 버전과 출처

### 5.1 내용 주소화 — DVC / git-annex / DataLad

- DVC 는 추적 대상 파일·디렉터리마다 **내용 해시**를 계산해 실체는 캐시·원격에 두고 Git 에는
  작은 포인터(`.dvc`)만 커밋한다. `dvc.lock` 이 의존·산출의 해시를 고정한다. 그래서 각 Git
  커밋이 그때 쓰인 데이터 버전에 해시로 묶인다
  ([기술 가이드 PDF](https://datos.gob.es/sites/default/files/documentacion/files/Guia_DVC_en.pdf),
  [CASRAI 가이드](https://casrai.org/guides/dvc-data-version-control-research-datasets-ml-pipelines)).
- **한계가 문헌에 적혀 있다**: `.dvc` 파일만으로는 FAIR 출처 요건에 못 미치고 PROV-JSON 출력이나
  RO-Crate 포장을 함께 쓰라는 권고가 같은 자료에 있다. 기계가 해석 가능한 출처는 PROV 계열,
  장기 큐레이션은 DataLad 로 비교표를 적는다.
- 판정: **미채택(도구), 채택(원리).** 도구를 거절하는 이유는 우리 데이터 평면이 이미 정해져
  있다는 것이다 — 원본 프레임은 미디어 경로의 것이고 업무·관측 경로에 픽셀을 싣지 않는다
  (AI-C-08). 학습 후보에는 `frame_ref` 와 특징만 남는다. DVC 를 들이면 **픽셀을 Git 인접
  저장소로 다시 끌어오는** 평면 위반이 되고, 폐쇄망에서 원격 캐시를 세우는 일도 따로 남는다.
  **원리는 받는다**: 데이터 버전은 이름이 아니라 **내용 해시**여야 한다. 우리는 이미 두
  자리에서 그렇게 한다(`ParameterSet.version`, `ExecutionConfiguration.fingerprint`). 비어
  있는 것은 **라벨 내용의 해시**다(§9.3).

### 5.2 기계가 읽는 메타데이터 — Croissant 1.1, PROV-O, RO-Crate

- [Croissant Format Specification 1.1 (2026-01-29)](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.1.html)
  ([원문 md](https://raw.githubusercontent.com/mlcommons/croissant/main/docs/croissant-spec-1.1.md),
  [논문 arXiv 2403.19546](https://arxiv.org/html/2403.19546v2)): JSON-LD 인코딩이고, **출처와
  사용 조건 기구를 W3C 표준(PROV-O, ODRL) 위에 세운다.** 1.1 이 PROV-O 출처 모형을 채택해
  데이터셋·파일·레코드를 그 원천과 처리 단계에 잇고 책임 주체(사람 또는 소프트웨어)를 적게
  한다. MLCommons 는 이것을 "데이터 중심 AI 시스템의 chain-of-custody 점검과 감사" 로 설명한다
  ([공지](https://mlcommons.org/2026/02/croissant-1-1-standard/)). 명세 라이선스는 CC BY-ND 4.0,
  구현·예제는 Apache 2.0.
- RO-Crate 는 경쟁이 아니라 보완으로 서술된다 — 연구 객체 포장(출처 + 파일 구조)이고 Croissant
  는 ML 적재에 맞춘 데이터셋 구조다.
- 판정: **부분 채택 — PROV-O 의 **관계 어휘**만, Croissant 포맷은 미채택.** 포맷을 거절하는
  이유는 조달·대상 둘이다. Croissant 는 **공개·공유되는 데이터셋**을 기술하려고 만들어졌고
  우리 후보는 기기별로 쪼개진 운영 캡처이며 공개 대상이 아니다. JSON-LD 와 schema.org 어휘를
  들이는 것은 의존성이고, 그것이 사는 길은 외부 데이터셋을 들여올 때(`external_dataset` 출처)
  **읽는 쪽**이다 — 그때 이 포맷을 읽으면 출처를 지어내지 않아도 된다. 반대로 PROV-O 의
  세 축(`Entity`/`Activity`/`Agent` 와 `wasDerivedFrom`/`wasGeneratedBy`/`wasAttributedTo`)은
  **우리 `LearningLineage` 가 이미 하고 있는 것의 이름**이다 — `LineageEvent` 가
  `actor`(Agent) · `evidence_ref`(Entity) · `state`(Activity 의 결과)를 들고, 그것을 PROV 어휘로
  **번역할 수 있다는 사실**이 AI-L-08 의 "저장소나 전송 기술 자체를 필수 구현으로 고정하지
  않는다" 를 만족하는 증거다. 어휘 대조표를 두는 것이 §12 의 값싼 항목이다.

### 5.3 데이터·모델 문서 — Datasheets, Model Cards

- [Mitchell et al., "Model Cards for Model Reporting" (FAT* 2019,
  arXiv 1810.03993)](https://arxiv.org/pdf/1810.03993): 학습된 모델에 대한 1~2쪽 문서로,
  의도된 용도·환경 조건·성능 측도·윤리 고려를 **일관된 형식**으로 적게 한다. 핵심 주장 하나는
  **집단별로 분해한 평가(disaggregated evaluation)** 를 보고하라는 것이다.
- Gebru et al., "Datasheets for Datasets" (CACM 2021): 전자부품 데이터시트에 비유해
  동기·구성·수집·유지보수에 걸친 **57개 질문**을 둔다.
- 기계가 읽는 층이 없다는 지적: Hugging Face 의 사람용 카드가 일관된 schema·ontology 를 갖지
  않는다는 문제를 [MRM3, arXiv 2505.13343](https://arxiv.org/pdf/2505.13343) 이 적는다.
- 판정: **채택 — AI-L-06 의 항목 목록으로 그대로 쓴다.** 이것이 이 조사에서 가장 값싸고 가장
  직접적인 채택이다. AI-L-06 이 열거한 것(학습 사유 · 데이터 출처와 확인 상태 · 대표 사례 ·
  학습 대상과 기존 버전 · 검증 과정 · 신규·기존 성능 변화 · 자원·지연 변화 · 알려진 실패 사례 ·
  **검증된 범위와 미검증 범위** · 복구 가능한 이전 정상 버전)은 model card 의 절 목록과 거의
  일대일이고, 우리 쪽에는 그것을 담는 **한 자료형이 없다**(§9.4). 다만 하나는 우리가 **더
  강하게** 요구한다 — model card 는 "미검증 범위" 를 요구하지 않고 우리는 요구한다(AI-B-01 ·
  AI-O-05). 그래서 카드를 그대로 베끼지 않고 **미측정·미검증을 1급 칸으로 둔 카드**가 된다.
  "집단별 분해 평가" 는 우리에게 **기기·입력 조건별 분해**로 번역되고, 그 축은
  `InputConditions.group_key` 로 이미 있다.

### 5.4 가중치 파일의 무결성 — Sigstore model signing

- [google/model-transparency](https://github.com/google/model-transparency) 는 두 축을 가른다 —
  **model signing** 은 모델 허브에 게시된 **뒤**의 변조를, **SLSA** 는 **빌드 중**의 변조를
  막는다. [model-signing 1.0](https://blog.sigstore.dev/model-transparency-v1.0/) 은
  sigstore-python 위에 서고 서명 bundle 을 protobuf/JSON 으로 낸다. 서명 사건은 **추가 전용
  투명성 로그(Rekor)** 에 적히고 검증자는 포함 증명으로 확인한다. Sigstore 를 기본으로 권하되
  **PKI·자가서명도 지원**한다.
- 한계도 적혀 있다 — SLSA·Sigstore 는 첫 걸음이고 만병통치가 아니다
  ([ReversingLabs](https://www.reversinglabs.com/blog/ai-and-transparency-how-ml-model-creators-can-protect-against-supply-chain-attacks)).
  Red Hat 은 모델 산출물과 분리 서명을 **OCI 컨테이너에 담아** 공급망 구성요소와 같이 다루는
  쪽을 쓴다
  ([Red Hat Emerging Technologies](https://next.redhat.com/2025/04/10/model-authenticity-and-transparency-with-sigstore/)).
- 판정: **부분 채택 — 해시·분리 서명 검증은 채택, 공개 투명성 로그는 미채택.** 투명성 로그를
  거절하는 이유는 품질이 아니라 **폐쇄망**이다(AI-C-16: 공개 인터넷 나가는 연결을 핵심 기능의
  전제로 두지 않는다). Rekor 공개 인스턴스에 포함 증명을 물으려면 외부 연결이 필요하므로 그
  기능은 **선택**으로만 선언할 수 있다. 반면 **내용 해시 + 분리 서명 + 조달 경로 검증**은
  외부 연결 없이 성립하고, 우리 `runtime/airgap.py` 가 이미 조달 경로를 보고 있으며
  AI-B-02 가 "실행 이미지와 외부 구성은 버전과 식별 가능한 무결성 정보를 유지" 하라고 이미
  요구한다. **모델 산출물이 그 요구에서 빠져 있는 것**이 공백이다(§9.5). Red Hat 의 OCI
  동봉 방식이 우리 `runtime/deployment_bundle.py` 와 같은 자리를 노린다.

---

## 6. 가중치 레지스트리와 lifecycle

### 6.1 MLflow Model Registry — stage 에서 alias 로

- [MLflow Model Registry](https://mlflow.org/docs/2.8.0/model-registry.html) 는 이름·버전·계보·
  메타데이터를 중앙에 두는 모델 저장소다. 버전 페이지가 **signature**(입·출력 schema), 원
  run, 생성 시각을 보여 준다.
- **stage 는 폐기됐다.** 2차 자료들이 **MLflow 2.9.0 부터 stage 가 deprecated** 이고
  `candidate`/`champion` 같은 **alias**(움직이는 포인터)로 승격을 통제하라고 적는다. Databricks
  계열에서는 Unity Catalog 가 alias 를, 구 workspace registry 가
  stage(`Staging`/`Production`/`Archived`)를 쓴다.
- 판정: **미채택(도구), 채택(두 교훈).** 도구 거절 사유는 조달과 책임 경계 둘이다 — 폐쇄망에서
  추적 서버를 세우는 일이 따로 남고(AI-C-16), 더 중요하게 **우리 승격 권한은 레지스트리가
  아니라 운영자·백엔드에 있다**(AI-C-19, AI-L-06). alias 를 쓰면 "champion 을 가리키는 것"
  자체가 배포 결정이 되어 승인 상태와 포인터가 **두 곳의 진실**이 된다 —
  `runtime/mlops_pipeline.py` docstring 이 "두 번째 상태 기계를 만들지 않는다" 로 이미 적은
  금지와 같다. **받는 교훈 둘**: (1) **signature(입·출력 schema)를 버전에 붙여 다닌다** — 우리
  `ModelVersion` 은 하드웨어 태그와 입력 조건을 들지만 출력 schema 는 들지 않고, 개방어휘
  탐지기는 어휘가 곧 출력 공간이라 이것이 실제 위험이다(어휘 축은 이미
  `ExecutionConfiguration.prompt_ref` 로 지문에 들어가 있어 절반은 닫혀 있다). (2) **stage 가
  폐기된 이유** — 고정된 단계 열거형이 배치마다 다른 승격 경로를 담지 못했다. 우리
  `mlops_pipeline.next_scope()` 는 열거형이지만 **주인이 하나**이고 화면이 따로 계산하지
  않는다. 이름이 고정이라는 같은 취약점을 갖고 있으므로, 새 범위가 필요해지는 날 **alias 처럼
  데이터로 바꿀 자리**로 기억해 둔다.

### 6.2 단계적 적용 — shadow / canary

- 보정 조사 때와 달리 이 축은 **우리가 이미 문헌과 같은 결론에 있다.** `mlops_pipeline` 은
  새 버전을 `VERIFICATION` 에서 기존 버전과 **나란히** 올리고, 기존 버전이 물러나는 것은
  범위가 `OPERATIONAL` 로 넓어지는 순간이다. 근거는 docstring 에 이미 적혀 있다 — "비교 대상이
  이미 내려가 있으면 비교할 것이 없다."
- `continual/dgs.py` 의 `forgetting_max` 게이트는 Netflix/Google 의 Kayenta canary 분석을 근거로
  삼았다고 적혀 있고, **기본값이 꺼져 있으며 held-out 평가가 아니라 adapter state 이동량의
  대리지표**라고 스스로 적는다. 그 정직함은 유지하되 §9.2 에서 다시 다룬다.
- 판정: **채택(기존 유지).** 추가할 것은 알고리즘이 아니라 **비교 지표**다(§7.2).

---

## 7. drift 아래의 지속학습과 그 평가

### 7.1 망각 완화 — replay / 정칙화 / 파라미터 격리

- 조망: [Online Continual Learning in Image Classification: An Empirical Survey,
  arXiv 2101.10423](https://arxiv.org/pdf/2101.10423);
  [Recent Advances of Continual Learning in Computer Vision, arXiv 2109.11369](https://arxiv.org/pdf/2109.11369).
- **작은 버퍼에서는 클래스 균형이 reservoir 를 이긴다.**
  [Chaudhry et al., On Tiny Episodic Memories in Continual Learning,
  arXiv 1902.10486](https://arxiv.org/pdf/1902.10486) 은 reservoir 표집 기반 경험 재생이 전반에서
  가장 좋았으나 **메모리가 클래스당 3 표본 미만일 때는 클래스당 표본 수를 구조적으로 보장하는
  표집이 더 좋았다**고 보고하고, 일부 클래스가 너무 적어질 때까지 reservoir 를 쓰는 **혼합**을
  제안한다. 조건: 분류 과제, 그 논문의 벤치마크. 변형은
  [Balanced Reservoir Sampling, arXiv 2010.05595](https://arxiv.org/pdf/2010.05595) 이고
  같은 논문이 **버퍼가 작을 때 이 기법들의 이득이 특히 크다**고 적는다.
- 판정: **부분 채택 — 클래스 균형 보존만. replay 학습 자체는 미채택.** replay 를 거절하는 이유는
  우리 기본 학습기가 기울기를 쓰지 않아 "재생할 배치" 라는 개념이 없다는 것이다(§8). 하지만
  **클래스 균형 교훈은 그대로 적용된다** — `CandidateStore.add` 는 `per_group_limit = 500` 을
  넘으면 **오래된 것부터 버린다**(순수 FIFO). Chaudhry 의 결론을 우리 상황에 대입하면 이것이
  정확히 피하라고 한 모양이다: 한 클래스가 몰려 들어오는 구간이 있으면 다른 클래스의 확인
  표본이 **먼저 잘려 나가고**, 우리 조건 묶음은 클래스당 표본이 한 자릿수라 문헌이 "클래스
  균형이 더 좋다" 고 말한 그 구간이다. 이것은 §9.6 의 항목이다.
- 정칙화(EWC 계열)와 파라미터 격리는 **미채택**이고 사유는 §8 과 같다 — 기울기와 Fisher 정보를
  요구한다. `continual/p2iod.py` 가 파라미터 격리 계열의 **융합 규칙만** 순수 numpy 로 옮겨
  두었고, docstring 이 학습 루프·손실·데이터셋·AP 수치를 **재현하지 않는다**고 스스로 적는다.

### 7.2 어떻게 평가하는가 — 이것이 AI-L-05 의 핵심이다

- 표준 지표는 GEM 계열이다. [Lopez-Paz & Ranzato, Gradient Episodic Memory for Continual
  Learning (NIPS 2017, arXiv 1706.08840)](https://arxiv.org/pdf/1706.08840) 이 시험 정확도 행렬
  `R(i, j)`(과제 i 까지 학습한 뒤 과제 j 의 정확도)에서 **평균 정확도**(마지막 행의 평균)와
  **backward transfer(BWT)** 를 정의한다. 음의 BWT 가 망각이다. **average forgetting** 은
  BWT 와 별개 지표로, 각 이전 과제의 최고 성적과 현재 성적의 격차다. **인용할 때 정의를
  확인해야 한다** — 논문마다 색인과 정규화가 다르고 `1/t` 와 `1/(T-1)` 이 섞인다. 지표가 망각
  하나로 좁다는 비판은
  [Don't forget, there is more than forgetting, arXiv 1810.13166](https://arxiv.org/pdf/1810.13166).
- **표본 단위로 보라는 축이 따로 있다.**
  [Yan et al., "Positive-Congruent Training: Towards Regression-Free Model Updates" (CVPR
  2021)](https://openaccess.thecvf.com/content/CVPR2021/papers/Yan_Positive-Congruent_Training_Towards_Regression-Free_Model_Updates_CVPR_2021_paper.pdf)
  는 **negative flip**(옛 모델이 맞혔는데 새 모델이 틀린 표본)을 정의하고 오류율과 함께 그것을
  줄이는 학습(focal distillation)을 제안한다. 보충자료의 수치가 이 축의 필요를 그대로 보여
  준다 — **ImageNet 전체 학습 집합으로 재학습한 ResNet-50 이 정확도를 약 12% 올렸는데도 표본의
  3.56% 가 negative flip 이었다**(조건: 영상 분류, ImageNet, 새 모델을 옛 가중치에서 초기화한
  경우에도 발생). 후속 연구들이 이 축을 이어받는다 —
  [Backward-Compatible Prediction Updates (NeurIPS 2021)](https://proceedings.neurips.cc/paper/2021/file/012d9fe15b2493f21902cd55603382ec-Paper.pdf),
  [NLP 갱신의 Gated Fusion, arXiv 2302.02080](https://arxiv.org/pdf/2302.02080),
  [Margin Preserving Training, arXiv 2511.08322](https://arxiv.org/pdf/2511.08322). 그중
  하나는 **새 모델 앙상블 다수결이 negative flip 을 효과적으로 줄여 이기기 어려운 기준선**이
  된다고 보고한다.
- 판정: **채택 — negative flip 을 세는 것.** 이것이 이 조사에서 가장 값 높은 발견이고
  §9.2 에서 우리 현재 구현이 **문헌보다 약하다**고 적는 근거다. 채택 비용이 0 에 가깝다:
  `ParameterEvaluator.evaluate` 는 이미 **같은 `retained_samples` 집합에서 후보와 기준을 각각
  채점**하므로 표본별 비교가 제자리에 있다. 새 데이터도, GPU 도, 다운로드도 필요 없다.
  PC-training 의 **학습 쪽 기여**(focal distillation)는 **미채택**이고 사유는 §8 이다.

### 7.3 drift 감지 — 라벨 없이 할 수 있는가

- 분류는 명확하다. 조망형 자료들이 **ADWIN·DDM·Page-Hinkley 를 오류율 기반**으로 묶고 참
  라벨을 요구한다고 적는다. 반면 Page-Hinkley·CUSUM·ADWIN 을 **입력 스트림**에 적용하면 라벨을
  소비하지 않고 쓸 수 있다
  ([Label-Free Concept Drift Assessment, arXiv 2508.00042](https://arxiv.org/pdf/2508.00042)).
  즉 라벨 필요 여부는 알고리즘이 아니라 **무엇을 먹이는가**가 정한다.
- 진짜 라벨 없는 계열: 참조 창과 검출 창의 분포를 비교하는 방법(증분 Kolmogorov–Smirnov 등),
  [STUDD(student–teacher), arXiv 2103.00903](https://arxiv.org/pdf/2103.00903), 보조 판별기를
  쓰는 D3.
- **진단의 한계가 명시돼 있다**: 오류 스트림 검출기(ADWIN·DDM·EDDM·Page-Hinkley)는 경보를
  항상 실제 개념 변화로 귀속하므로 **순수 공변량 변화에서도 경보**하고, 입력공간 검출기(D3
  계열)는 **가상 drift 만 보고하고 순수 개념 변화를 전부 놓친다**
  ([arXiv 2609.27865](https://arxiv.org/pdf/2609.27865), 2026 preprint — 예비 결과라고 적혀 있고
  식별자 형식이 통상적이지 않아 수치는 조심해서 다룬다).
- 수치를 하나 옮기되 조건을 크게 적는다: **라벨이 희소한 무선 통신 벤치마크**에서 F1 이
  Page-Hinkley·CUSUM 0.80, DDM 0.72, ADWIN 0.44, 제안 기법 1.00 이었다(arXiv 2508.00042).
  **우리 도메인이 아니고** 과제·창 길이·drift 주입 방식이 전부 다르므로 **임계값이나 방법 선택의
  근거로 쓸 수 없다.** 순서만 참고한다.
- 판정: **채택(이미 있는 것의 자동화로 한정).** 우리는 `continual/h2st.py` 로 **특징 수준 2표본
  검정**을 이미 들고 있고 그것은 라벨을 요구하지 않는다 — 문헌 기준으로 분포 비교 계열이고,
  "참조 창 대 검출 창" 구조와 같다. 비어 있는 것은 **참조 특징을 언제 등록하고 언제 검정을
  돌리는가**이고, 그 답은 새 알고리즘이 아니라 기존 요구사항에 이미 있다 — `runtime/refresh.py`
  의 **요청 기반 반영**(운영자가 구역을 열거나, 임무가 부여되거나, 서브태스크가 요구하거나,
  새 장치가 조인할 때)이 그대로 검정 시점이 된다. 상시 돌리면 아무도 보지 않는 구역의 추론이
  계속 도는 그 문제가 그대로 재현된다(AI-C-13, AI-O-01). STUDD·D3 는 **미채택** — 보조 모델을
  하나 더 학습하고 돌려야 하므로 엣지 CPU 예산에 들어가지 않고, 우리는 같은 질문에 답하는
  도구를 이미 갖고 있다.

### 7.4 엣지에서 추론과 재학습이 같은 자원을 다툰다 — Ekya

- [Bhardwaj et al., "Ekya: Continuous Learning of Video Analytics Models on Edge Compute
  Servers" (NSDI 2022, pp. 119–135)](https://www.usenix.org/conference/nsdi22/presentation/bhardwaj):
  엣지 모델은 라이브 영상이 학습 자료에서 멀어지면 성능이 떨어지고, 주기적 재학습은 도움이
  되지만 **추론과 같은 하드웨어를 다툰다.** Ekya 는 여러 스트림에 걸쳐 자원을 배분하고
  **micro-profiler** 로 재학습이 가장 필요한 모델을 고른다. 저자들은 기준선 스케줄러 대비
  **정확도 29% 높고 기준선이 같은 정확도를 내려면 GPU 4배가 필요**하다고 보고한다(조건: **엣지
  GPU 서버**, 다중 영상 스트림, 저자들의 자체 주장. [code](https://github.com/edge-video-services/ekya)).
- 판정: **부분 채택 — 자원 배분 계약만, 재학습은 미채택.** 이미 그렇게 되어 있다:
  `continual/ekya.py` 가 micro-profile 선택과 한계효용 기반 고정 chunk 배분만 결정론적으로
  옮기고 **학습을 띄우지도 GPU 를 제어하지도 않는다**고 docstring 이 적는다. 재학습 쪽을
  거절하는 이유는 **GPU**다 — Ekya 의 전제가 엣지 GPU 서버이고 우리 엣지는 CPU +
  onnxruntime 이다(AI-B-10). 다만 Ekya 가 확인해 준 것이 하나 있고 그것이 설계로 남아 있다:
  **학습과 추론을 같은 생명주기에 두면 학습 장애가 추론을 멈춘다** — `stream_learning` 이
  추론 경로를 호출하지 않고 실패를 예외가 아니라 `TrainingOutcome.reason` 으로 돌려주는 것이
  그 경계다.

### 7.5 자기 출력으로 다시 배우면 무너진다

- 조망: [Reviewing Model Collapse and Countermeasures, arXiv 2608.21366](https://arxiv.org/pdf/2608.21366)
  (2026 preprint). 자기 소비 루프에서 학습 자료가 사람이 만든 자료에서 멀어지고, 흔한 패턴이
  과대 대표되며 드문 패턴이 사라지고 다양성이 줄어든다. 가우시안 장난감 모형에서는 분산이
  0 으로 수축한다.
- 수치 하나와 그 조건: **Stable Diffusion v2.1 을 자기 출력으로 5회 재학습**하면 사람 얼굴
  생성이 심하게 왜곡·균질화됐고 **재학습 집합의 합성 비율이 3% 에 불과해도** 그랬다고 보고한다.
  조건을 분명히 적는다 — **생성 영상 모형**이고 우리 탐지·프로토타입 갱신이 아니다. 옮길 수
  있는 것은 **방향**이지 수치가 아니다.
- 완화로 수렴하는 것: **외부 검증자(사람 또는 더 나은 모델)로 정보를 주입**하면 합성 재학습이
  붕괴하지 않지만 **강하게 편향된 검증자는 여전히 열화**를 낳는다
  ([arXiv 2510.16657](https://arxiv.org/html/2510.16657v1)). 실제 데이터를 섞되 라운드별 혼합
  비율을 과제 의존 상한 아래로 두라는 권고도 있다. 단순 모형에서 **일관된 교정(calibration)이
  데이터 피드백 루프 안정의 충분조건**이라는 결과(Taori & Hashimoto 계열)도 인용된다.
- 판정: **채택(이미 하고 있는 것의 근거로).** AI-L-02 의 금지("검증되지 않은 자동 추론 결과를
  확정 정답으로 자동 승격하지 않는다")가 이 문헌에서 말하는 **외부 검증자 주입**과 같은 조치다.
  우리 쪽 구현이 그 금지를 구조로 들고 있다 — `StreamSample.confirmed` 가
  `HUMAN_CONFIRMED`/`EXTERNAL_LABEL` 일 때만 참이고 `operational_stream.py` 에는 상태를 바꾸는
  함수가 아예 없다. **그런데 "강하게 편향된 검증자" 경고가 우리에게 그대로 적용된다** — §4.1 의
  anchoring 과 §9.1 의 후보 선별 편향이 바로 그 편향의 두 경로다. 즉 이 문헌은 우리 설계를
  지지하는 동시에 **우리의 사람 확인이 편향되지 않았다는 보증이 어디에도 없다**는 것을 가리킨다.

---

## 8. 프로토타입·임계 계열 — 우리 기본 학습기의 선행 연구

`PrototypeLearningProvider` 는 기울기를 쓰지 않는다. 클래스별 특징 평균(프로토타입)과 확인된
표본·프로토타입 유사도의 **하위 분위**를 임계로 쓴다. 이 계열의 선행 연구가 무엇이고 한계가
무엇인지가 §12 의 순서를 정한다.

### 8.1 Nearest-class-mean(NCM) / 프로토타입 분류기

- NCM 은 class-incremental learning 에서 **완전연결 분류층보다 망각에 강하다**는 이유로 널리
  선호된다 ([Dual Prototypes, arXiv 2411.17766](https://arxiv.org/pdf/2411.17766) 의 서술).
  iCaRL 도 학습된 특징 위에 NMC 분류기를 올린다 — 즉 두 계열은 배타가 아니라 조합으로 쓰인다
  ([A Comprehensive Study of Class Incremental Learning Algorithms for Visual Tasks](https://www.sciencedirect.com/science/article/am/pii/S0893608020304202)).
- 고정된 foundation model 특징 위에서 **미세조정 없이** 라벨 표본으로 프로토타입만 세우는 설정이
  정칙화·replay·구조 기법들을 앞섰다는 보고가 있다
  ([Foundation Models as Class-Incremental Learners, OpenReview](https://openreview.net/pdf?id=FyvpNwaMHk)).
  저자들의 주장이고 독립 검증은 아니다.
- **한계도 같은 문헌이 적는다**: (1) NCM 은 **표현 유연성에 묶여** 도메인 사전학습에 크게
  의존한다. (2) 클래스 특징이 조밀한 군집이 아니라 복잡한 manifold 를 이루면 **클래스당
  프로토타입 하나는 너무 단순**하다
  ([Beyond Point-wise Neural Collapse, arXiv 2605.11904](https://arxiv.org/html/2605.11904v1),
  2026 preprint; 다중 프로토타입 변형들도 같은 이유로 제안됐다). (3) 클래스가 쌓이면 상관된
  프로토타입이 서로 **몰려(crowding)** 망각이 억제돼도 정확도가 떨어진다(arXiv 2411.17766).
- 판정: **채택(기존 유지) + 한계를 선언한다.** 우리 선택은 문헌에 근거가 있고 — 말단에서
  돌고, 결정적이고, 사람이 읽을 수 있고, 망각에 강하다 — **기울기 미세조정으로 바꿔야 한다는
  결론은 조사에서 나오지 않았다.** 대신 조건이 붙는다: NCM 의 품질은 **특징 공간의 품질이
  상한**이고, 그 상한은 우리 쪽에서 **측정되지 않았다.** 그리고 우리 특징 공간은 생산자가
  **둘**이다 — CLIP 임베딩(`perception/appearance_classifier.py`)과 **상자 좌표**
  (`twin.file_label_candidate` 의 `feature=tuple(box)`). 후자의 한계는
  `TrainingDesk` docstring 이 이미 정직하게 적고 있다("상자 좌표끼리의 코사인 유사도는 거의
  1 에 몰려서 … 보류 집합 정확도가 낮게 나오는 것이 정상이다 — 배관의 고장이 아니라 그 특징
  공간의 성질이다"). **문헌의 (1)번 한계가 그 문장의 일반형**이다. 다중 프로토타입은
  **미채택(보류)** — 클래스당 표본이 한 자릿수인 지금 프로토타입을 여러 개로 쪼개면 각각이
  표본 1~2개의 평균이 되어 추정이 더 나빠진다. crowding 은 클래스 수가 늘면 올 문제이므로
  §11 에 추적 항목으로 남긴다.

### 8.2 임계 설정 — open-set 인식의 교훈

이 절이 우리 구현의 가장 약한 곳을 가리킨다.

- [Bendale & Boult, "Towards Open Set Deep Networks" (OpenMax, CVPR
  2016)](https://www.cv-foundation.org/openaccess/content_cvpr_2016/papers/Bendale_Towards_Open_Set_CVPR_2016_paper.pdf)
  는 클래스별 활성값 꼬리에 **Weibull(극값) 모형**을 적합해 open space 위험을 제한한다.
  거절은 "미지 클래스가 최대 확률일 때" 또는 "최대 확률이 임계 아래일 때" 적용한다.
  **논문 자신이 절대 임계를 교정하기 어렵다고 적고** — 데이터에 달려 있기 때문 — 임계를
  **학습 영상 + 표집한 open-set 영상**에 대한 grid search 로 F-measure 를 최적화해 정한다.
- 조망과 후속의 일관된 지적: 미지 클래스 정보가 불완전하므로 **알려진 클래스 지식만으로 임계를
  고르게 되고**, 교정이 나쁘면 모델이 낯선 입력에 과신한다
  ([A Survey on Open Set Recognition, arXiv 2109.00893](https://arxiv.org/html/2109.00893)).
  과제마다 의미 정보가 달라 **모든 open-set 과제에 맞는 최적 임계를 얻기 어렵다**
  ([Learning Placeholders, CVPR 2021](https://openaccess.thecvf.com/content/CVPR2021/papers/Zhou_Learning_Placeholders_for_Open-Set_Recognition_CVPR_2021_paper.pdf)).
- 교정은 별개 문제다: [Evaluating Uncertainty Calibration for Open-Set Recognition,
  arXiv 2205.07160](https://arxiv.org/pdf/2205.07160) 은 open-set 조건에서 교정 오차가 크고
  **OpenMax 가 그것을 고쳐 주지 않는다**고 보고하며, temperature scaling 을 쓰려면 **학습
  자료의 10% 를 검증 집합으로 떼야** 한다고 적는다.
- 판정: **채택(원리) — 임계는 음성 없이 교정되지 않는다.** 이것이 §9.3 의 근거다. 우리 임계는
  **확인된 양성만의 유사도 하위 분위**이고, 음성을 한 번도 보지 않는다. OpenMax 가 **표집한
  open-set 영상을 임계 교정에 넣었다**는 사실이 결정적이다 — 가장 널리 인용되는 이 계열의
  시작점조차 한쪽 자료로는 임계를 못 정했다고 적는다. Weibull 적합 자체는 **미채택**이고
  사유는 표본 수다(극값 분포의 꼬리 적합에 클래스당 한 자릿수 표본은 모자라고, 그 추정의
  정확도를 우리는 선언할 수 없다 — §1 의 마지막 줄).

---

## 9. 우리가 가진 것 중 문헌이 더 나은 방법을 말하는 것

이 절이 이 문서의 요점이다. 거절 사유보다 이것이 더 쓸모 있다.

### 9.1 사람에게 보여 줄 프레임을 **파일명 정렬**로 고른다 — 무작위보다 나쁘다

`FrameLabelSource._listing()` 은 프레임을 `sorted(...)` 로 내고 앞 300개만 목록에 올린다.
우리 파일명은 시각 기반이므로 **정렬 = 시간순**이고, 300개 자름은 **가장 이른 300 프레임**이다.

문헌 기준으로 이것은 두 겹으로 나쁘다. 첫째, 능동 학습 평가가 **무작위를 이기지 못하는 방법이
많다**고 보고하는 그 무작위가 여기 **기준선조차 아니다** — 우리 순서는 무작위가 아니라 가장
상관이 높은 순서다. 연속 프레임은 서로 거의 같고, batch redundancy(탐욕적 top-k 가 거의 중복인
표본을 고르는 문제, §3.2 가 k-means++ 로 푸는 그 문제)를 **의도적으로 최대화한 배치**가 시간순
정렬이다. 둘째, **표집 편향이 복리로 커진다**(arXiv 2301.10625) — 이른 구간만 라벨되면 프로토타입은
그 구간의 조명·자세·배경에 맞춰지고, 그 프로토타입으로 다음 후보가 뽑힌다.

**다만 정확히 적는다**: 지금 이 목록은 운영자가 **고르는 화면**이고 자동 획득이 아니다. 사람이
목록을 훑어 다른 프레임을 고를 수 있다. 그러므로 결함은 "틀린 표본을 강제한다" 가 아니라
**기본값이 가장 나쁜 순서이고, 사람이 그 기본값을 따르면 아무 신호도 쓰이지 않는다**는 것이다.
§3.4 의 `BoxCnt` 가 이 자리의 가장 값싼 대체다 — 검출 수는 `results.jsonl` 에 이미 있다.

### 9.2 회귀를 **집계**로 잰다 — negative flip 이 보이지 않는다

`EvaluationReport.regression` 은 `baseline.ratio - retained.ratio` 다. 따라서 **기준이 맞혔던
것 5개를 깨고 틀렸던 것 5개를 고친 후보는 회귀 0 으로 통과한다.** AI-L-05 는 "기존에 검증된
객체·환경·업무에서의 성능 저하 여부" 를 요구하고, 그 문장의 주체는 **집계 비율이 아니라
객체**로 읽는 것이 더 맞다.

§7.2 의 수치가 이 간극의 크기를 말한다 — ImageNet 전체로 재학습한 ResNet-50 이 **정확도를
12% 올리면서도 표본의 3.56% 를 negative flip** 으로 깼다(Yan et al. CVPR 2021 보충자료).
집계만 보면 그 모델은 "크게 개선" 이고, 깨진 3.56% 는 **보이지 않는다.** 물리 시스템에서
그 3.56% 가 사람이 손으로 확인해 준 소화기일 수 있다는 것이 AI-L-03·AI-B-01 이 구성 독립
지식을 보존하라고 한 이유와 같다.

채택 비용이 거의 없다는 것이 이 항목을 1순위로 만든다. `ParameterEvaluator._accuracy` 는 이미
**같은 `retained_samples` 에서 후보와 기준을 각각 채점**한다. 표본별 `(기준 정답 여부, 후보
정답 여부)` 를 세면 negative flip 수와 positive flip 수가 바로 나오고, 게이트에 축이 하나
더 생긴다. 새 데이터도 GPU 도 다운로드도 필요 없다. 그리고 `continual/dgs.py` 의
`forgetting_max` 가 **대리지표이고 기본 꺼짐**이라고 스스로 적은 그 자리를 실제 지표가 메운다.

### 9.3 확인된 **음성**을 버린다 — 그러면서 임계를 음성 없이 정한다

두 사실이 같은 공백의 양면이다.

사람이 `REJECTED` 를 누르면 그것은 **"여기엔 아무것도 없다" 는 정답**이다. `labeling.py` 가
그것을 정확히 그렇게 적는다(`final_box` 가 None, docstring 에 "없음이 곧 정답이다"). 그런데
학습 경로로 넘어갈 때 `serve.py::_file_label_candidates` 가 `label = box.final_class or "absent"`
로 **`"absent"` 라는 문자열 라벨의 양성 후보**로 바꾼다. 그 뒤 `PrototypeLearningProvider` 는
라벨별로 묶어 프로토타입을 만들므로, 같은 조건 묶음에 `"absent"` 가 `min_samples`(기본 3)개
쌓이면 **`parameters["absent"]` 가 생긴다** — 프로토타입과 임계를 가진 하나의 클래스로서.
`PrototypeScorer` 는 그것을 후보 클래스로 취급하고, `EvaluationGate.forbid_label_loss` 는
이후 그 "클래스" 가 사라지는 것을 **FAIL 사유**로 금지한다. 더해서 `REJECTED` 의
`final_box` 가 None 이므로 `file_label_candidate` 의 `feature` 가
`(0.0, 0.0, 0.0, 0.0)` 이 되고, `_cosine` 은 norm 0 에서 0.0 을 돌려주므로 그 프로토타입의
임계가 0.0 으로 내려간다 — **모든 것을 받아들이는 클래스**다.

그래서 거짓 양성이라는 가장 값진 사람 확인이 (a) 음성으로 쓰이지 못하고 (b) 가짜 양성 클래스를
만든다. 문헌이 말하는 올바른 자리는 §8.2 다 — **음성은 임계 교정에 들어가야 한다.** OpenMax 가
표집한 open-set 영상으로 임계를 grid search 했고, 그 논문 자신이 알려진 클래스만으로는 절대
임계를 못 정한다고 적었다. 그리고 우리 코드가 이 결론에 이미 도달해 있다 —
`ConfirmedAcceptanceScorer` docstring 이 "진짜 판별 수치가 필요하면 확인된 음성 표본이 먼저
있어야 하고, 그것은 사용자 확인(AI-L-03)에서 온다" 고 적는다. **그 음성은 이미 와 있고 다른
문으로 들어와 양성이 되어 있다.**

### 9.4 AI-L-06 의 판단 정보 묶음이 없다 — 그리고 추적표가 그것을 "완료" 로 적고 있었다

AI-L-06 은 열 가지 항목을 열거한다. 그것을 한 자료형으로 내는 자리가 없고, 추적표의
AI-L-06 행은 구현 위치로 `continual/ekya.py`(**결정론적 자원 배분**)를 적고 있었다. 자원
배분은 관리자 판단 정보가 아니다. §10-2 에 정정 내역을 적었고 **추적표도 고쳤다.**

문헌이 주는 것은 **항목 목록**이고 그것은 §5.3 의 model card 다. 우리가 더 요구하는 것은
**미검증 범위를 1급 칸으로** 두는 것이고(AI-B-01·AI-O-05), 그 재료는 이미 흩어져 있다 —
`EvaluationReport`(성능 변화), `VerifiedExecutionProfile.not_validated()`(돌리지 않은 검증),
`MeasurementSet.unmeasured()`(재지 않은 항목), `known_failure_conditions`(알려진 실패),
`LearningLineage.events`(사유·주체·근거), `ModelVersion`(검증 범위),
`GroundTruthRecord.summary()`(데이터 출처와 검수 수). **조립만 없다.**

### 9.5 모델 산출물의 무결성 정보가 없다

AI-B-02 는 "실행 이미지와 외부 구성은 버전과 식별 가능한 무결성 정보를 유지" 하라고 요구한다.
`ExecutionConfiguration.implementation_ref` 가 **파일 내용 sha256** 으로 쓰이고 있어(AI-B-01
행의 실측 서술) 절반은 닫혀 있다. 비어 있는 것은 **학습으로 만들어진 산출물** 쪽이다 —
`ParameterSet.version` 은 파라미터 내용 해시이지만 **그 해시가 배포되는 파일의 해시와 같다는
확인**이 없고, 서명도 없다. §5.4 의 결론대로 **해시 + 분리 서명 + 조달 경로 검증**은 폐쇄망에서
성립하고, 공개 투명성 로그만 외부 연결을 요구한다.

### 9.6 후보 보관이 **순수 FIFO** 다 — 작은 버퍼에서 문헌이 피하라고 한 모양

`CandidateStore.add` 는 `per_group_limit`(기본 500)을 넘으면 `del bucket[:초과분]` 으로
**가장 오래된 것부터** 버린다. 조건 묶음별 클래스당 확인 표본이 한 자릿수인 우리 상황은
Chaudhry et al. 이 **"클래스당 3 표본 미만에서는 클래스 균형 표집이 reservoir 를 이긴다"** 고
보고한 구간이고(§7.1), FIFO 는 reservoir 보다도 약하다 — 한 클래스가 몰려 들어오는 구간이
있으면 다른 클래스의 확인 표본이 먼저 사라지고, 그러면 `min_samples` 미달로 그 클래스는
학습에서 조용히 빠진다(`REASON_TOO_FEW_SAMPLES` 는 묶음 전체가 비었을 때만 뜨고, 일부 라벨이
미달로 빠지는 것은 `continue` 로 넘어간다). 500 이라는 한도가 넉넉해 지금은 거의 닿지 않지만,
닿는 날의 실패가 **조용하다**는 것이 문제다.

### 9.7 사람이 고친 것만 후보가 된다 — 무엇을 향해 편향되는가

task 가 물은 질문에 정확히 답한다. `serve.py::_file_label_candidates` 는 **`record.corrections`
만** 올린다 — 즉 `CORRECTING_VERDICTS`(`ADJUSTED`/`RELABELED`/`REJECTED`/`ADDED`)이고
`CONFIRMED`(모델이 맞았다)는 **학습 후보가 되지 않는다.** docstring 이 그 이유를 적는다 —
"모델이 맞힌 것을 후보로 넣으면 후보가 전체 스트림으로 불어난다."

그 이유는 타당하다(AI-L-01 이 전체 스트림 저장을 피하라고 한다). 결과는 그렇지 않다. 학습
후보 집합이 **구성상 현재 모델의 오류 집합과 정확히 같다.** 그리고 우리 기본 학습기는
**프로토타입 = 그 표본들의 평균**이다. 여기서 두 계열이 갈린다.

- 기울기 학습에서 어려운 표본만 쓰는 것은 hard example mining 이고, 손실이 배치 전체에 걸쳐
  섞이며 기존 가중치가 사전정보로 남으므로 편향이 **부분적으로 흡수**된다.
- **프로토타입에서는 흡수가 없다.** 프로토타입은 표본 평균의 추정량이고, 표본이 "모델이 틀린
  것" 으로 조건부 추출된 집합이면 그 평균은 **클래스 평균이 아니라 클래스의 어려운 꼬리의
  평균**이다. 추정량의 편향이 파라미터의 편향과 **같은 양**이다. 임계도 같은 표본의 분위이므로
  같은 방향으로 끌린다.

문헌 근거는 §3.1 의 표집 편향(라벨된 집합이 원 분포에서 뽑힌 것이 아니게 되어 불편 평가·모델
선택이 어려워진다, arXiv 2301.10625)과 §7.5 의 "강하게 편향된 검증자는 여전히 열화를 낳는다"
(arXiv 2510.16657)다. 둘 다 조건이 우리와 정확히 같지는 않으므로 **방향의 근거로만** 쓴다.

**문헌이 하는 대응**은 두 가지이고 둘 다 우리에게 가능하다. (1) **다양성을 섞는다** — 불확실성
단독이 아니라 불확실성 × 다양성(§3.2 BADGE 의 구조). (2) **클래스 균형을 보장한다**(§7.1).
그리고 우리에게 특히 값싼 세 번째가 있다: `CONFIRMED` 를 **후보로 올리지 않되 평가 집합으로
쓴다.** 모델이 맞혔고 사람이 맞다고 한 표본은 **회귀를 재기에 가장 적합한 자료**이고 (§9.2 의
negative flip 이 정확히 그 집합에서 측정된다), 그것은 학습 비용을 전혀 늘리지 않는다 —
`GroundTruthRecord.reviewed` 가 이미 `CONFIRMED` 를 포함하고 있어 자료는 **만들어져 있지만
어디로도 가지 않는다.**

---

## 10. 채택 결론

### 10-1. 요약표

| 기법 | 가정 | 우리 현장에 필요한 것 | 채택 | 한 줄 사유 |
|---|---|---|---|---|
| `BoxCnt` 계열(검출 밀도 기반 프레임 순위) | 검출 결과가 있다 | `results.jsonl` (이미 있다) | **예** | 파일명 정렬보다 나은 가장 값싼 것. 문헌이 정교한 AL 을 일관되게 앞섰다고 보고 |
| negative flip 계수(PC-training 의 **지표** 쪽) | 두 모델을 같은 집합에서 채점 | 이미 그렇게 한다 | **예** | 집계 회귀가 통과시키는 "5개 깨고 5개 고친" 후보를 잡는다. 추가 데이터 0 |
| 확인된 음성의 임계 교정 투입(OpenMax 의 **원리**) | 음성 표본이 있다 | `REJECTED` (이미 있다) | **예** | 양성만으로는 임계가 교정되지 않는다 — OpenMax 논문 자신이 그렇게 적는다 |
| model card 항목 목록(AI-L-06 의 자료형) | 없음 | 조립만 | **예** | 재료가 전부 흩어져 있고 묶는 자료형만 없다. 미검증 칸을 더해 쓴다 |
| 클래스 균형 후보 보존 | 라벨별 계수 | 이미 있다 | **예** | FIFO 는 작은 버퍼에서 reservoir 보다도 약하다(Chaudhry) |
| `CONFIRMED` 를 평가 집합으로 | 사람 검수 | 이미 있다 | **예** | 회귀 측정에 가장 맞는 자료가 만들어져 있고 어디로도 가지 않는다 |
| PROV-O 관계 어휘 대조 | 없음 | 대조표 1장 | **예** | `LearningLineage` 가 이미 하는 것의 표준 이름. 의존성 0 |
| 해시 + 분리 서명(산출물 무결성) | 내부 서명 키 | 키 운영 결정 | **예(사용자 결정 필요)** | 폐쇄망에서 성립한다. 공개 투명성 로그만 외부 연결을 요구한다 |
| h2st 2표본 검정의 **자동 호출** | 참조 특징 등록 | 호출 시점 규약 | **예** | 라벨 없는 drift 감지를 이미 들고 있고 호출 시점만 없다. `refresh.py` 가 그 시점 |
| NCM/프로토타입 학습기 | 특징 공간이 좋다 | 특징 품질 측정 | **예(기존 유지)** | 문헌에 근거가 있다. 다만 특징 공간이 상한이고 그것을 우리는 재지 않았다 |
| 불확실성 단독 AL(엔트로피·margin) | 라운드를 여러 번 돈다 | 라벨 예산 | 아니오 | 우리가 정확히 cold-start 구간이고 문헌이 "무작위보다 나쁘다" 고 보고한 그 구간 |
| BADGE | 마지막 층 기울기 | 기울기 학습기 | 아니오(구조는 채택) | 기울기가 **없다**. 불확실성×다양성 구조는 프로토타입 공간으로 옮긴다 |
| Core-set / k-center-greedy | 풀 전체 쌍 거리 | CPU 예산 | 아니오 | 라벨 화면을 열 때마다 돌 비용이 아니다. 다양성은 더 싸게 얻는다 |
| localization stability(AL) | 프레임당 여러 번 추론 | GPU 또는 지연 예산 | 아니오 | 엣지 CPU 예산 밖(zipdepth 단독 384 입력 219.7 ms) |
| Choi et al. 확률적 탐지 AL | 탐지기를 확률 모형으로 학습 | 그 탐지기 | 아니오 | **없는 것**. 탐지기를 다시 학습해야 한다 |
| 다중 작업자 / soft label / 관점주의 | 사람이 둘 이상 | 작업자 | 아니오 | **없는 것**. 우리 불일치는 모델-사람 축이고 그쪽은 이미 들고 있다 |
| confident learning / cleanlab | out-of-sample 확률 + 클래스별 충분한 표본 | 큰 후보 집합 | 아니오(보류) | **없는 것**. 그리고 표시 후보의 51% 만 실제 오류 — 사람 시간을 지금은 못 낸다 |
| Snorkel / 약지도 | 규칙으로 라벨을 만들 수 있다 | 그런 과제 | 아니오 | 적용 지점이 없고, 라벨링 함수 출력은 미검증 라벨이라 AI-L-02 와 충돌 |
| conformal / learning to defer | 교환가능한 교정 집합 | 교정 집합 규모 | 아니오(보류) | **없는 것**. 보류 집합이 수 건이면 보증의 형식만 빌리는 것이 된다 |
| EWC 등 정칙화, replay 학습, focal distillation | 기울기·Fisher·배치 | 기울기 학습기 | 아니오 | 기본 학습기가 기울기를 쓰지 않는다. `LearningProvider` 경계에 나중에 붙인다 |
| 다중 프로토타입 | 클래스당 표본이 많다 | 표본 수 | 아니오(보류) | 한 자릿수 표본을 쪼개면 각 프로토타입이 표본 1~2개의 평균이 된다 |
| OpenMax Weibull 적합 | 꼬리 적합할 표본 | 표본 수 | 아니오 | 클래스당 한 자릿수로는 극값 적합의 정확도를 선언할 수 없다 |
| DVC / git-annex / DataLad | 데이터를 Git 인접 저장소에 둔다 | 픽셀 평면 변경 | 아니오(원리는 채택) | 픽셀을 업무 평면으로 끌어오는 평면 위반(AI-C-08). 내용 해시 원리만 받는다 |
| Croissant 1.1 포맷 | 공개·공유 데이터셋 | JSON-LD 의존성 | 아니오(읽는 쪽만) | 우리 후보는 공개 대상이 아니다. 외부 데이터셋을 **들여올 때** 읽는다 |
| MLflow Model Registry | 추적 서버 + alias 가 배포를 정한다 | 서버 + 권한 이동 | 아니오(두 교훈은 채택) | 폐쇄망 조달 + 승격 권한이 우리 것이 아니다(AI-C-19). signature 와 stage 폐기 교훈만 |
| Sigstore 공개 투명성 로그 | 공개 인터넷 | 외부 연결 | 아니오 | AI-C-16. 선택 기능으로만 선언할 수 있다 |
| Ekya 재학습 스케줄링 | **엣지 GPU 서버** | GPU | 아니오(배분 계약은 기존) | 우리 엣지는 CPU + onnxruntime(AI-B-10) |
| STUDD / D3 drift 감지 | 보조 모델을 학습·운영 | CPU 예산 | 아니오 | 같은 질문에 답하는 h2st 를 이미 들고 있다 |

### 10-2. 추적표 정정 — **과장을 고쳤다**

task 가 허용한 범위에서 `internal/docs-dev/ai/requirement-traceability.md` 의 AI-L 행을
고쳤다. 조사 중 **과장 셋**을 찾았고, 전부 2026-09 시점에 쓰인 초기 행이 뒤에 들어온 실제
구현(같은 문서의 2026-10/11 행)과 어긋난 채 남은 것이다.

1. **AI-L-06 (가장 분명한 과장)**: "완료 (결정론적 resource allocation) | `continual/ekya.py`".
   AI-L-06 은 관리자 판단 정보(학습 사유·데이터 출처·대표 사례·성능 변화·자원 변화·알려진
   실패·검증/미검증 범위·복구 가능한 이전 버전)를 요구하고 **자원 배분은 그 항목이 아니다.**
   → **부분**으로 내리고 공백을 적었다(§9.4).
2. **AI-L-07**: "완료 (승격 전 검증 Gate) | `continual/lineage.py`". 상태기계 하나로는
   AI-L-07 의 "제한된 대상에서 기존 정상 버전과 비교" 가 성립하지 않는다. 실제 구현은
   `runtime/mlops_pipeline.py` 이고 같은 문서의 뒤쪽 행이 그것을 적는다. → 구현 위치를 합쳤다.
3. **AI-L-03**: "완료 (격리 상태 Gate) | `continual/lineage.py`". "격리" 는 AI-L-02 의 내용이고
   AI-L-03 은 사용자 확인·의미 정보 반영이다. 실제 구현은 `tools/fms_console/labeling.py` +
   `twin.py` 다. → 구현 위치를 합쳤다.

AI-L-05 행은 과장이 아니다 — `dgs.forgetting_max` 가 **대리지표이고 기본 꺼짐**이라고 그 행과
모듈 docstring 이 모두 적고, 뒤쪽 "AI-L-05 (확장)" 행이 실제 held-out 평가를 적는다. 다만
§9.2 의 공백(표본 단위 회귀)을 그 확장 행에 덧붙였다.

---

## 11. 확인하지 못한 것

정직하게 남긴다. 아래는 이 조사가 **확정하지 못한** 항목이고, 뒤에 오는 사람이 여기서 시작하면
된다.

- **우리 특징 공간의 품질을 재지 못했다.** §8.1 이 NCM 의 상한을 특징 품질로 적지만, 우리
  CLIP 임베딩이 우리 클래스를 얼마나 가르는지(클래스 내/간 거리, 프로토타입 분리도)를 **측정한
  수치가 없다.** 이것이 없으면 "프로토타입 학습기가 충분한가" 라는 질문에 답할 수 없다.
  그리고 §9.1 과 §9.7 의 편향이 실제로 얼마나 큰지도 이 측정 없이는 수치로 말할 수 없다.
- **우리 작업자의 상자 변이를 재지 못했다.** §4.4 의 결론대로 `disagreement()` 의 IoU 는 사람
  변이의 바닥 위에서만 뜻이 있는데, 같은 프레임을 두 번 라벨한 자료가 없어서 그 바닥이 얼마인지
  모른다. 문헌 수치(COCO 모서리 잡음 등)를 그대로 가져오면 안 된다 — 과제·해상도·지침이 다르다.
- **cold-start 구간을 벗어나는 표본 수를 모른다.** §3.1 의 문헌은 "작은 예산" 과 "충분한 예산"
  을 데이터셋별로 다르게 적고, 우리 조건 묶음·클래스 수에 대응하는 값이 없다. 그래서 §12 의
  (b) 항목들이 "표본이 몇 개 모이면" 으로 시작하는데 그 숫자를 채우지 못했다.
- **`"absent"` 가 실제로 프로토타입을 만든 사례를 관측하지 못했다.** §9.3 은 코드 경로를 읽어
  유도한 것이고, `min_samples`(3) 미달이어서 아직 발생하지 않았을 가능성이 크다. 재현 시험이
  없으므로 "일어날 수 있다" 까지만 주장한다.
- **confident learning 의 51% 정밀도를 탐지 과제에서 확인하지 못했다.** 그 수치는 **분류 시험
  집합**의 것이고 탐지 상자에 대한 대응 수치를 찾지 못했다.
- **라벨 책상의 GT 가 학습 후보 외의 경로로 쓰이는지 끝까지 확인하지 못했다.**
  `runtime/model_trial.py` 가 `scored` 비교에 GT 를 쓴다고 docstring 에 적지만, GT 저장소
  (`StatusService._ground_truth`)와 그 소비 경로를 전수로 따라가지 못했다.
- **negative flip 의 허용치를 정할 근거가 없다.** §9.2 의 지표는 값싸지만 "몇 개까지 허용하나"
  는 운영 정책이고, Yan et al. 의 3.56% 는 ImageNet 분류의 수치라 우리 임계가 될 수 없다.
- **PROV-O 대조의 완전성을 확인하지 못했다.** `LineageEvent` 의 다섯 칸이 PROV 의 어느 속성에
  대응하는지는 유추했고 PROV-O 명세를 직접 열어 대조하지 않았다.
- 2026 년 preprint 를 여럿 인용했다(arXiv 2605.11904, 2608.21366, 2609.27865, 2601.09065,
  2605.12303, 2606.21069, 2604.19943, 2608.14617 등). **동료평가를 통과한 것이 아니고** 본문을
  전부 열지 못했다. 그중 arXiv 2609.27865 는 자기 결과를 예비적이라 적는다.
- Gebru et al. "Datasheets for Datasets", Basile et al. 의 관점주의 구분, Aroyo & Welty,
  Taori & Hashimoto, Sener & Savarese 는 **인용 문헌을 통해서만** 확인했고 원문을 직접 열지
  못했다.
- Sambasivan et al. (CHI 2021) 의 "data cascade 유병률 92%" 는 **인도·동/서아프리카·미국의
  실무자 53명 면담 연구**의 수치다. 측정이 아니라 면담 보고이므로 우리 쪽 비율의 예측으로
  읽어서는 안 된다
  ([ACM](https://dl.acm.org/doi/fullHtml/10.1145/3411764.3445518)). 이 논문을 인용하는 이유는
  수치가 아니라 결론이다 — 데이터 문제는 **불투명하고 지연되어 나타나며 지표가 빈약하다.**
  그것이 §9 의 항목 전부가 "조용한 실패" 인 이유와 같다.

---

## 12. 다음 단계 — AI-L-* 에 묶고 값 순으로

각 항목에 **(a) 지금 구현 가능 / (b) 없는 데이터가 필요 / (c) 사용자 결정이 필요** 를 붙인다.

1. **negative flip 을 게이트 축으로 더한다** — AI-L-05. **(a) 지금 구현 가능.**
   `ParameterEvaluator` 가 이미 같은 `retained_samples` 에서 두 모델을 채점하므로 표본별
   `(기준 정답, 후보 정답)` 쌍을 세어 `negative_flips` / `positive_flips` 를 낸다. 집계
   `regression` 은 그대로 두고 **축을 하나 더** 둔다(합치면 §9.2 의 실패가 그대로 돌아온다).
   허용치는 `EvaluationGate` 의 새 칸이고 기본값은 보수적으로 둔다 — 그 값의 근거는 §11 에
   없다고 적었으므로 **운영 정책으로 선언**하고 계보에 적는다. 값이 가장 높은 이유: 비용이
   거의 0 이고, 지금 통과하는 후보 중 무엇이 통과해서는 안 됐는지를 **소급해서** 말할 수 있다.
2. **확인된 음성을 음성으로 다룬다** — AI-L-02, AI-L-03, AI-L-05. **(a) 지금 구현 가능.**
   두 일이다. (i) `REJECTED` 가 `"absent"` 양성 라벨이 되지 않게 한다 — 음성을 담는 칸
   (예: `StreamSample` 의 `negative_for: str`)이나 별도 후보 종류로 두고, `"absent"` 문자열이
   `parameters` 의 키가 되는 경로를 막는다. (ii) 그 음성을 **임계 교정과 평가에 투입**한다 —
   `ConfirmedAcceptanceScorer` 가 스스로 적은 공백이 그것으로 닫히고, 그때 비로소 그 점수가
   "수락률" 이 아니라 판별 수치가 된다. 근거는 §8.2(OpenMax 조차 open-set 표본으로 임계를
   교정했다)이고, 재료는 이미 와 있다.
3. **`CONFIRMED` 를 평가 집합으로 보낸다** — AI-L-05, AI-L-01. **(a) 지금 구현 가능.**
   학습 후보로 올리지 않는 기존 판단은 유지한다(AI-L-01: 전체 스트림을 저장하지 않는다).
   대신 `GroundTruthRecord.reviewed` 의 `CONFIRMED` 상자를 **보류·회귀 집합**으로 쌓는다.
   1번과 짝이다 — negative flip 을 세려면 "기준이 맞혔던 것" 집합이 필요하고 그것이 바로
   이 집합이다. 지금은 만들어져서 아무 데도 가지 않는다(§9.7).
4. **라벨 화면의 기본 순서를 검출 밀도 순으로 바꾼다** — AI-L-01. **(a) 지금 구현 가능.**
   `FrameLabelSource._listing()` 의 파일명 정렬을 `results.jsonl` 의 검출 수 기반 순위로
   바꾸고(§3.4 의 `BoxCnt`), **정렬 근거를 응답에 함께 낸다**(사람이 왜 그 순서인지 알아야
   한다 — AI-C-13 과 같은 규약). 검출 결과가 없는 출처(외부 데이터셋)에서는 파일명 정렬을
   유지하되 그 사실을 사유로 낸다. 300 자름도 "가장 이른 300" 에서 "순위 상위 300" 이 된다.
   값이 1~3번보다 낮은 이유는 효과가 **사람의 선택에 달려 있기** 때문이다(§9.1).
5. **후보 보존을 라벨 균형으로 바꾼다** — AI-L-02, AI-L-09. **(a) 지금 구현 가능.**
   `CandidateStore.add` 의 FIFO 를 "라벨별 최소 보장 후 초과분에서 버리기" 로 바꾼다
   (Chaudhry 의 혼합 권고와 같은 모양, §7.1). 지금 한도가 넉넉해 즉시 효과는 작지만 닿는 날의
   실패가 조용하므로 미리 닫는다.
6. **AI-L-06 판단 정보를 한 자료형으로 조립한다** — AI-L-06, AI-L-08. **(a) 지금 구현 가능.**
   model card 의 절 목록(§5.3)에 **미검증·미측정 칸을 더한** 것으로 두고, 재료는 §9.4 가
   열거한 기존 객체에서 **읽어 모으기만** 한다 — 새 판정을 만들지 않는다(FMS 콘솔이 판정을
   하지 않는 것과 같은 규약). 분해 축은 `InputConditions.group_key` 다. 추적표의 AI-L-06 을
   "부분" 에서 되돌릴 수 있는 유일한 작업이다.
7. **h2st 검정을 요청 기반으로 호출한다** — AI-L-01, AI-L-09. **(a) 지금 구현 가능.**
   `runtime/refresh.py` 의 네 계기(구역 열람 · 임무 부여 · 서브태스크 요구 · 새 장치 조인)에
   맞춰 참조 특징 대 최근 특징의 2표본 검정을 돌리고, 기각되면 **학습 후보 사유**로 적는다
   (AI-L-01 이 요구하는 "학습 후보 발생 사유"). 상시 돌리지 않는 것이 요구사항이다(AI-C-13).
8. **PROV-O 어휘 대조표를 남긴다** — AI-L-08. **(a) 지금 구현 가능.**
   `docs/` 에 `LineageEvent` ↔ PROV `Entity`/`Activity`/`Agent` 대조 1장. 코드 변경 0,
   의존성 0, AI-L-08 의 "저장소나 전송 기술을 필수 구현으로 고정하지 않는다" 에 대한 증거.
9. **학습 데이터의 내용 신원을 더한다** — AI-L-08, AI-B-01. **(a) 지금 구현 가능하나 범위가 넓다.**
   `sample_ids` 옆에 **라벨 내용 해시**(정렬된 `(sample_id, label, box, verdict)` 의 sha256)를
   둔다. 같은 id 가 재라벨로 다른 정답을 가리키는 것을 §5.1 의 원리대로 내용으로 가른다.
   `ExecutionConfiguration.fingerprint` 와 같은 모양이고 같은 이유다.
10. **프로토타입 후보 선별에 다양성을 섞는다** — AI-L-01, AI-L-09. **(b) 없는 데이터가 필요.**
    BADGE 의 구조를 프로토타입 공간으로 옮긴다 — `1 - cos(x, prototype)` 로 가중한 k-means++
    로 후보를 뽑아 §9.7 의 편향을 줄인다. **왜 (b) 인가**: 효과를 확인하려면 "편향된 선별로
    만든 프로토타입" 과 "다양성을 섞은 선별로 만든 프로토타입" 을 **같은 보류 집합**에서
    비교해야 하고, 그 보류 집합이 현재 조건 묶음별 수 건이다. 1~3번이 먼저 돌아 평가 집합이
    쌓인 뒤에 할 일이다.
11. **특징 공간의 품질을 측정한다** — AI-B-01, AI-L-05. **(b) 없는 데이터가 필요.**
    §11 의 첫 항목을 닫는 일이다. 클래스 내/간 거리와 프로토타입 분리도를 우리 CLIP 임베딩과
    우리 클래스에서 재고 `MeasurementSet` 으로 적는다(미측정은 비워 둔다). 사람이 라벨한 표본이
    클래스당 두 자릿수가 되어야 수치에 뜻이 생긴다.
12. **같은 프레임을 두 번 라벨해 사람 변이의 바닥을 잰다** — AI-L-03, AI-L-05.
    **(b) 없는 데이터가 필요 + (c) 사용자 결정이 필요.** §4.4 의 결론대로 `disagreement()` 의
    IoU 에 임계를 두려면 이 수치가 먼저 있어야 한다. 사람의 시간을 쓰는 일이므로 **얼마나 쓸
    것인가가 사용자 결정**이다(프레임 20장 재라벨이면 바닥의 1차 추정은 나온다).
13. **산출물 서명과 그 키 운영** — AI-L-08, AI-B-02, AI-C-16. **(c) 사용자 결정이 필요.**
    §5.4·§9.5 대로 해시 + 분리 서명은 폐쇄망에서 성립하지만, **키를 누가 들고 누가 서명하며
    검증 실패 시 배포를 막을 것인가**가 운영 정책이고 AI-C-19 의 경계에 걸린다(승인 주체는
    백엔드의 authoritative 기록이다). 결정이 나오면 `runtime/deployment_bundle.py` 가 자리다.
14. **기울기 학습 provider 를 들일 것인가** — AI-L-04, AI-L-09. **(c) 사용자 결정이 필요.**
    이 조사는 **프로토타입 학습기를 기울기로 바꿔야 한다는 결론을 내지 않았다**(§8.1). 그러나
    §8.1 의 (1)·(2) 한계가 실제로 걸리는 날(특징 공간이 상한이거나 클래스가 manifold 를 이루는
    것이 11번에서 확인되는 날)에는 선택지가 필요하다. 그때 들일 것은 PC-training 의 focal
    distillation(§7.2) 이 1순위다 — **회귀를 줄이는 것이 학습 목표에 들어가는** 유일한 계열이고
    우리 AI-L-05 가 요구하는 것과 같은 방향이다. 결정에 필요한 것은 학습 실행 위치(엣지 CPU
    에서는 안 된다 — AI-L-04 가 허용하는 "실행 위치 선택" 이 그 자리)와 폐쇄망 조달이다.
15. **conformal 교정 집합을 모을 것인가** — AI-S-03, AI-L-06. **(b) + (c).**
    §4.6 의 계열은 AI-S-03(근거 충분도)과 AI-L-06(판단 정보)이 묻는 것과 같은 질문에 답하고,
    "사람에게 넘길지 혼자 처리할지" 를 **분포 무관 보증**으로 말한다. 지금은 교정 집합이 없어
    보증의 형식만 빌리게 되므로 미채택이다. 교정 집합을 만드는 것은 라벨 예산을 쓰는 일이고,
    그 예산을 1~3번(지금 당장 값이 나오는 것)보다 여기에 먼저 쓸 것인지가 사용자 결정이다.
