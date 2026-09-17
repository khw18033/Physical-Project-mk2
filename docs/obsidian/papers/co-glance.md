# Co-GLANCE: Uncertainty-Aware Active Perception for Heterogeneous Robot Teaming

## 메타데이터
- categories: VLM 지식 증류 기반 온보드 인지, 두 단계 불확실성 정량화(선택적 기권 + Conformal Prediction), 이종 로봇 배차를 위한 Vehicle Routing, Active Perception 요청 트리거
- domain: [[협력 인지]], [[로보틱스·다중로봇]]
- source: Podolinsky, Michal P., Bhatt, Neel P., Samineni, Pranay, Siva, Rohan, Ellis, Christian, Topcu, Ufuk. "Co-GLANCE: Uncertainty-Aware Active Perception for Heterogeneous Robot Teaming." arXiv preprint arXiv:2606.09919, 2026.
- url: https://arxiv.org/abs/2606.09919 (프로젝트 페이지: https://co-glance.github.io)
- year: 2026
- authors: Michal P. Podolinsky, Neel P. Bhatt (공동 1저자), Pranay Samineni, Rohan Siva, Christian Ellis, Ufuk Topcu — The University of Texas at Austin
- venue: **arXiv 프리프린트만 확인됨 (게재 학회/저널 없음)** — 아래 "게재 상태" 참고

## 게재 상태 (반드시 확인)
- arXiv 식별자 `arXiv:2606.09919v1 [cs.LG]`, 제출일 2026-06-07 (UTC), 라이선스 CC BY 4.0. Subject class는 cs.LG/cs.AI/cs.MA/cs.RO.
- 논문 본문·arXiv 메타데이터 어디에도 accepted venue(학회/저널명, journal reference)가 기재되어 있지 않다. 프로젝트 페이지(co-glance.github.io)의 BibTeX 항목도 `booktitle={}`으로 비어 있다.
- 즉 현재(2026-09) 시점에서 이 논문은 **동료 심사를 통과했다는 근거가 없는 arXiv 프리프린트**이며, 워크숍/학회 accept 여부는 확인되지 않는다. 동료가 "2026"으로만 표기하고 venue를 명시하지 않은 것은 실제로 venue 정보가 없기 때문으로 보인다.

## 1. 핵심 요약
- 이종 air-ground 로봇 팀은 단일 시점(viewpoint)만으로는 폐색(occlusion) 등으로 인한 지각 불확실성을 해소할 수 없는데, 기존 VLM 기반 접근은 클라우드 추론에 의존하고 보정된(calibrated) 불확실성 추정치를 제공하지 못한다.
- Co-GLANCE는 대형 VLM(ChatGPT-5.4 + Grounding DINO + SAM 2)의 폐색 분할·로봇 배차 추론 능력을 경량 YOLO-seg-nano 모델로 증류(distill)해 온보드에서 실시간 추론하고, "risk-controlled(선택적 기권)"와 "coverage-controlled(conformal prediction)"의 2단계 불확실성 정량화로 통계적으로 유효한 커버리지 보장을 산출한다.
- 저신뢰(threshold 미만) 예측은 active perception 요청으로 이어져, 로봇 배차 불확실성은 보수적인 "양쪽 로봇 동시 파견"으로, 객체 탐지 불확실성은 지상 로봇의 근접 재관측 파견으로 해소된다. 이 배차 정책은 논문이 스스로 명시하듯 정보이득 등을 정식으로 최적화한 것이 아니라 휴리스틱이다.
- DJI Matrice 600 Pro 드론과 Boston Dynamics Spot 사족보행 로봇을 이용한 실제(real-world) 실험에서, 클라우드 VLM 베이스라인 대비 폐색 탐지 정확도 25%p, 로봇 배차 정확도 36%p 향상과 약 350배의 프레임당 추론 지연 감소(37ms vs. 13,000ms 이상)를 보였고, 4,000장 이상의 동기화된 공중-지상 프레임 데이터셋을 함께 공개했다.

## 2. 문서 목적
- 해결하려는 문제: 이종 air-ground 로봇 팀에서 폐색 등으로 인한 지각 불확실성이 시점(로봇 플랫폼)마다 다르게 나타나는데, 이를 해소하려면 (1) 어떤 영역이 불확실한지 판단하는 장면 이해와 (2) 어느 로봇을 보내야 하는지 판단하는 capability-aware 배차가 모두 필요하다는 문제. VLM은 이 두 판단에 유용한 semantic prior를 제공하지만 온보드 추론에는 계산 비용이 과도하고 보정된 불확실성 추정치를 제공하지 않는다.
- 기술적 목표: VLM의 의미 추론을 경량 온보드 모델로 증류하면서, 그 결과에 대해 conformal prediction과 선택적 기권을 결합한 2단계 스킴으로 통계적으로 유효한 불확실성 보장을 부여하고, 이 보정된 불확실성이 직접 active perception(어느 로봇을 어디로 보낼지)을 트리거하도록 만드는 것.
- 다루는 범위: VLM 기반 폐색 분할·배차 라벨 생성과 contextual self-review에 의한 pseudo-label 정제(§3.1), 2단계 불확실성 정량화 이론(§3.2), Heterogeneous Vehicle Routing Problem(HVRP) 기반 로봇 배차·경로 계획과 active perception 트리거 규칙(§3.3), DJI Matrice 600 Pro + Boston Dynamics Spot을 이용한 실제 야외 실험과 4,000+ 프레임 데이터셋 공개(§4).

## 3. 핵심 개념 상세

### VLM 지식 증류 기반 온보드 폐색 분할·배차 (Self-Review 포함)
- 원문 표현: "Co-GLANCE distills occlusion segmentation and platform allocation from a large VLM into a lightweight YOLO-seg-nano model for onboard inference (Figure 3)... a contextual self-review stage presents the candidate masks back to the VLM in a multi-turn conversation, allowing it to remove incorrect masks, refine misaligned regions, propose new keywords, and assign platform labels."
- 정의: 공중 RGB 프레임에서 VLM이 폐색 유발 물체의 키워드를 생성하고, 이를 open-vocabulary segmentation(Grounding DINO + SAM 2)으로 후보 마스크화한 뒤, 같은 VLM에게 캐시된 멀티턴 대화 컨텍스트에서 그 마스크를 다시 검토·정제시켜(self-review) 최종 pseudo-label(마스크 + 배차 라벨)을 만들고, 이 pseudo-label로 경량 YOLO-seg-nano 모델을 학습해 온보드에서 단일 forward pass로 폐색 분할과 배차를 동시에 수행하는 파이프라인.
- 역할: VLM이 생성한 키워드가 실제로 어떻게 grounding될지 예측할 수 없어 마스크가 의도한 영역과 어긋나는 문제를 self-review로 보정하고, 최종적으로는 클라우드 VLM 없이 온보드에서 실시간으로 동일한 판단(어디가 폐색인지, 어느 플랫폼이 필요한지)을 재현하도록 한다.

### 플랫폼 배차 라벨 공간 {ground, either, both}
- 원문 표현: "Platform allocation label: Encodes which platform is necessary to resolve an occlusion, not which is currently closest or most convenient. The label space is {ground, both, either}, where ground requires the ground robot, both requires both robots, and either permits flexible assignment."
- 정의: 각 폐색 영역에 대해 그것을 실제로 해소하는 데 "필요한" 플랫폼을 3개 클래스 중 하나로 라벨링하는 체계. 단순히 가장 가까운 로봇이 아니라 물리적으로 그 폐색을 볼 수 있는 로봇이 무엇인지를 인코딩한다.
- 역할: 후속 HVRP 기반 경로 계획이 이 라벨을 입력으로 받아 각 폐색을 어느 로봇의 방문 목록에 넣을지 결정하는 근거가 된다. 실측 클래스 분포는 either 54.7%, ground 32.2%, both 13.1%였다(Table 7, 8,190개 마스크 인스턴스 기준).

### 2단계 불확실성 정량화 (Risk-Controlled Selective Abstention + Coverage-Controlled Conformal Prediction)
- 원문 표현: "The risk-controlled stage produces guaranteed singletons, where confidence is sufficient, through selective abstention; the coverage-controlled stage provides calibrated set predictions through conformal prediction on the remainder, informing active perception while it is underway."
- 정의: (Stage 1) 모델의 softmax 신뢰도 $\hat P(X_i)$가 보정된 임계값 $\hat\lambda$ 이상이면 그 예측(singleton)을 확정적으로 사용하고, 이때 오류율이 최소 $1-\delta$의 확률로 $\alpha$ 이하임이 보장된다(Learn-Then-Test 방식의 selective abstention, 식 (1)). $\hat\lambda$ 미만인 예측은 "기권(abstention)"되어 Stage 2로 넘어간다. (Stage 2) 기권된 샘플에 대해 conformal prediction으로 nonconformity score 기반 예측 집합 $\hat C(X_{test})=\{y:\hat f_y(X_{test})\ge 1-\hat q\}$를 만들고, marginal coverage guarantee $P[Y_{test}\in \hat C(X_{test})]\ge 1-\epsilon$를 부여한다(식 (2)). 이 스킴은 폐색 분할·배차, 사람 탐지 모두에 동일하게 적용된다.
- 역할: 모델 confidence 값 자체가 아니라 통계적으로 보정된(calibrated) 오류율/커버리지 보장을 기준으로 "이 예측을 그대로 의사결정에 써도 되는가"를 판정하며, 기권된 경우에만 active perception을 트리거함으로써 불필요한 재관측을 줄이고 남은 불확실한 경우에는 최소한 통계적으로 유효한 후보 집합을 제공한다.

### HVRP 기반 로봇 배차·경로 계획과 Active Perception 트리거 (휴리스틱, 정식 정보이득 최적화 아님)
- 원문 표현: "We feed certified allocation labels and agent positions into a Heterogeneous Vehicle Routing Problem (HVRP), minimizing total heuristic travel cost where ground robot traversal is weighted 10× higher than aerial traversal... Stage 1 singleton labels are passed directly to the planner; abstentions trigger a conservative both-agent dispatch, ensuring all high-uncertainty regions are visited... stage 1 abstentions trigger an active perception request dispatching the ground agent to acquire a closer viewpoint."
- 정의: (1) Stage 1에서 확정된(singleton) 배차 라벨(ground/either/both)과 로봇 위치를 입력으로 HVRP(지상 로봇 이동비용을 항공 로봇의 10배로 가중한 휴리스틱 이동비용 최소화, Google OR-Tools 사용)를 풀어 각 로봇의 방문 순서를 정하고, 지상 로봇에는 폐색당 1개 관측 지점을, 항공 로봇에는 폐색 주변 원형 스윕(8개 시점)을 배정한다. (2) 배차가 기권된(불확실한) 경우 정보이득을 계산하지 않고 곧바로 "양쪽 로봇 모두 파견"하는 보수적 규칙을 적용한다. (3) 객체 탐지가 기권된 경우에는 (선택이 아니라) 지상 로봇을 근접 재관측용으로 파견하도록 고정되어 있고, 이때 Stage 2 conformal prediction 집합은 어떤 클래스일 가능성이 높은지를 알려주는 보조 정보로만 쓰인다.
- 역할: "인지 실패 → 어느 로봇을 보낼지" 결정을 담당하지만, 저자들이 한계 절(§6)에서 명시하듯("the active perception policy is heuristic rather than jointly optimized with downstream planning objectives") 이 배차 결정 자체는 정식 utility/information-gain 최적화가 아니라 임계값 기반 confirm/abstain 규칙 + 보수적 both-dispatch 폴백 + 여행비용 휴리스틱 VRP의 조합이다. 통계적으로 엄밀한 부분은 "불확실성 정량화(2단계 guarantee)"이지, "어느 로봇을 보낼지 정하는 정책" 자체는 아니다.

## 4. 구조 및 흐름
1. 공중 RGB 프레임에서 VLM이 폐색 후보 키워드를 생성하고(Figure 3-1a), open-vocabulary segmentation(Grounding DINO + SAM 2)으로 후보 마스크를 만든다(1b).
2. Contextual self-review: 같은 VLM에게 후보 마스크를 멀티턴 대화로 다시 보여주어 잘못된 마스크 제거, 정렬 보정, 새 키워드 제안, 배차 라벨({ground, either, both}) 부여를 수행한다(1c–d).
3. 이 pseudo-label로 경량 YOLO-seg-nano 모델을 학습해, 온보드에서 단일 forward pass로 폐색 분할 + 배차 라벨 + confidence를 동시에 산출한다(Figure 3-2, 3).
4. 각 예측에 대해 Stage 1(risk-controlled selective abstention)을 적용: confidence가 보정된 임계값 $\hat\lambda$ 이상이면 singleton으로 확정해 바로 배차 계획에 사용하고, 미만이면 기권 처리해 active perception 요청을 발생시킨다.
5. 기권된 경우 Stage 2(conformal prediction)로 커버리지 보장 예측 집합을 만들어 병행 제공한다(주로 객체 클래스 후보를 좁히는 보조 정보).
6. 확정된 배차 라벨과 로봇 위치를 HVRP에 입력해 각 로봇의 방문 경로를 산출하고(지상 이동비용 10배 가중), 기권된 배차는 양쪽 로봇 동시 파견, 기권된 탐지는 지상 로봇 근접 재관측 파견으로 처리한다.
7. 실험: DJI Matrice 600 Pro(Jetson Xavier NX, Arducam HQ IMX477, 삼중화 GPS) + Boston Dynamics Spot(Jetson AGX Thor, 전면 RGB 카메라, RTK-GPS)로 야외 2개 시나리오(건설 현장, 위장 인원 은폐)에서 총 4,000장 이상(2,071 프레임 쌍)을 수집해 학습·평가하고, 두 로봇을 서로 다른 초기 시점에서 출발시킨 실제(real-world) 시연 2건으로 종단간 성능을 측정한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|------|------|
| VLM 지식을 증류한 경량 온보드 모델(Co-GLANCE)이 클라우드 VLM 베이스라인보다 실제 배치 환경에서 더 높은 폐색 탐지·배차 정확도를 낸다 | 2개 실제 시나리오 종단간 평가(Table 4)에서 폐색 탐지 정확도 25%p, 로봇 배차 정확도 36%p 향상(Expert 12/12 대비 VLM 5.5–6/12, Co-GLANCE 7.5/12); 마스크 단위 평가(Table 2, n=199)에서도 VLM 대비 precision/recall/F1 각각 22%/15%/19% 향상 |
| 증류된 온보드 모델은 클라우드 VLM 대비 압도적으로 낮은 지연과 통신 의존성을 가진다 | 프레임당 추론 지연 37ms(Co-GLANCE, Jetson Xavier NX) vs 13,000ms 이상(VLM, RTX 4090) — 약 350배 감소; API 토큰 사용량 0 vs 평균 16.7k/frame; "operating entirely onboard and without network connectivity" |
| 2단계 불확실성 정량화(선택적 기권 + conformal prediction)는 이론적 보장대로 실제로도 오류율을 통제한다 | 로봇 배차: Stage 1 보장 오류율 ≤15%(δ=0.1)에서 실측 오류율 12.6%, 기권율 10.4%(Table 3); 사람 탐지: 보장 오류율 ≤20%에서 실측 20%, 기권율 50%; CIFAR-10 예시(Appendix B)에서도 목표 커버리지 0.80에 실측 커버리지 0.8046으로 검증 |
| Self-review는 VLM pseudo-label 품질을 개선하지만 증류 모델은 여전히 일부 지표(특히 both 클래스 배차 정확도)에서 self-review VLM보다 낮다 | self-review는 recall·배차 정확도를 15%p 이상 향상(Table 2); 그러나 Co-GLANCE(distilled)는 배차 정확도에서 VLM(self-review) 대비 5%p 낮고, both 클래스 배차 정확도에서는 두 VLM 베이스라인 모두보다 낮음(Table 12, Appendix F) — "compound scene-level reasoning"을 증류하기 어려운 것으로 저자들이 추정 |

## 6. 한계 및 부족한 점
- 검증 방법: arXiv PDF(2606.09919v1, 25페이지, 부록 A–G 포함)를 `pypdf`로 텍스트 추출해 본문·부록 전체를 직접 확인했다(그림·표는 텍스트만 확인, 이미지 자체는 미확인).
- **게재 상태의 한계**: 논문 어디에도 accepted venue가 명시되어 있지 않아, 동료 심사를 거쳤는지 확인할 수 없는 arXiv 프리프린트 단계다. 결과·주장은 저자 자체 보고이며 외부 심사·재현 검증을 거치지 않았을 가능성을 감안해야 한다.
- **저자 스스로 명시한 한계(§6)**: (1) "제한된 수의 로봇"(실제로는 드론 1대 + 사족보행 로봇 1대, 2대 구성)을 가진 semi-structured 야외 환경에서만 평가했다. (2) active perception 정책이 하류 계획 목표와 공동 최적화된 것이 아니라 휴리스틱이다. (3) 증류 모델이 VLM이 생성한 pseudo-label의 편향을 물려받을 수 있다.
- **동료의 프레이밍과 대조되는 점(사용자가 특히 확인 요청)**: "Drone/Quadruped/PTZ 요청"이라는 3자 선택 구조는 이 논문에는 없다. 실제 물리 플랫폼은 드론(DJI Matrice 600 Pro)과 사족보행 로봇(Boston Dynamics Spot) 2종뿐이며 PTZ 카메라는 등장하지 않는다. 또한 "인지 실패 → 다른 viewpoint 필요 판단 → 특정 플랫폼 요청"이라는 흐름은 대체로 맞지만, 실제 배차 결정은 정식 utility/information-gain 최적화가 아니라 (a) 확정 라벨은 HVRP 비용 최소화로 경로만 정하고, (b) 배차가 불확실하면 무조건 양쪽 로봇을 모두 보내는 보수적 규칙, (c) 탐지가 불확실하면 무조건 지상 로봇을 보내는 고정 규칙이다. 즉 "여러 후보 중 최적 플랫폼을 계산해서 고르는" 형태가 아니라 "확실하면 계획대로, 불확실하면 정해진 폴백(양쪽 다 보내기 / 지상 로봇 보내기)"에 가깝다.
- 평가 규모가 작다(마스크 단위 테스트 n=199, 배차 보정 테스트 n=222, 사람 탐지 보정 테스트 n=30 등) — 통계적 보장 자체는 이론적으로 유효하지만 실측 검증 샘플 수는 크지 않다.
- 데이터셋이 2개 야외 시나리오(건설 현장, 위장 인원)로 한정되어 있어 기상·조도·계절 등 환경 다양성에 대한 일반화는 확인되지 않는다.
- 로봇 간 통신은 "local WiFi"로만 기술되어 있고, 통신 지연·단절 상황에서의 강건성은 논문에서 다루지 않는다.

## 7. 원문 기반 핵심 문장
> "These calibrated uncertainty estimates directly trigger active perception, dispatching the most appropriate robot to acquire informative viewpoints and resolve uncertainty."
