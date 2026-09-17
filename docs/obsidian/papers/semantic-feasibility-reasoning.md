# Semantic Feasibility Reasoning for Heterogeneous Multi-Robot Task Allocation

## 메타데이터
- categories: ReasonerOutput, OWL/SWRL 기반 Feasibility Reasoning, Loaded-state Reachability, Allocator-agnostic 인터페이스
- domain: [[디지털트윈·상호운용]], [[로보틱스·다중로봇]]
- source: In, Gungyo, Kwon, Gihyeon, An, Yechan, Kuc, Taeyong. "Semantic Feasibility Reasoning for Heterogeneous Multi-Robot Task Allocation." Electronics, vol. 15, no. 16, article 3562, 2026. DOI: 10.3390/electronics15163562.
- url: https://www.mdpi.com/2079-9292/15/16/3562
- year: 2026 (published 2026-08-11)
- authors: Gungyo In, Gihyeon Kwon, Yechan An, Taeyong Kuc (Department of Electrical and Computer Engineering / Department of Intelligent Robotics, Sungkyunkwan University, Suwon, Republic of Korea)
- venue: MDPI Electronics 15(16):3562

## 1. 핵심 요약
- 이종 다중 로봇 task allocation에서 "이 로봇이 이 task를 실제로 수행할 수 있는가"라는 feasibility 판단을 특정 optimizer나 symbolic planner 내부 로직에 묻어두지 않고, ontology 기반의 독립된 reasoning 단계로 분리해 명시적으로 산출한다.
- Robot/Task/Place에 대한 semantic model을 OWL ontology로 정의하고(Owlready2로 구축), SWRL 규칙 기반 declarative reasoning(Pellet 2.3.1)과 procedural evaluation을 결합한 hybrid reasoning으로 multi-axis capability 조건과 "적재 상태(loaded-state)"에 따라 달라지는 place reachability를 함께 판정한다.
- reasoning 결과는 allocator-independent한 `ReasonerOutput`으로 형식화되며, Hungarian/MILP/greedy/genetic algorithm이라는 알고리즘적으로 서로 다른 4개 allocator가 동일한 `ReasonerOutput`을 공유 입력으로 사용해 유효한 assignment를 생성함을 실험으로 보인다.
- 적재 상태를 반영한 reachability 보정이 14–15%의 무효 assignment를 사전에 차단했고, fleet 구성과 대상 물체의 적재 상태 모두가 assignment feasibility에 영향을 준다는 것을 확인했다.

## 2. 문서 목적
- 해결하려는 문제: 기존 다중 로봇 task allocation 연구에서는 task feasibility 판단이 특정 optimizer나 symbolic planner 안에 암묵적으로 결합되어 있고, 공간 통행 가능성(traversability)은 로봇이 짐을 실었을 때 치수가 달라지는 것을 반영하지 못하는 정적 기준으로만 평가되어 왔다는 문제.
- 기술적 목표: robot/task/place를 공통 semantic model로 표현하고, declarative reasoning(SWRL)과 procedural evaluation을 결합한 hybrid reasoning으로 multi-axis capability 조건과 loaded-state 기반 reachability를 함께 판정하는 ontology 기반 feasibility reasoner를 설계하는 것. 이 reasoner의 출력을 allocator-independent한 공통 계약(`ReasonerOutput`)으로 만들어 서로 다른 allocation 알고리즘이 동일한 feasibility 정보를 공유하도록 하는 것이 핵심 목표다.
- 다루는 범위: ontology(TBox/ABox) 구성, SWRL 규칙 기반 declarative reasoning, procedural evaluation, `ReasonerOutput` 생성까지의 4단계 reasoning 아키텍처, 4개 fleet/allocator 조합에 대한 실험, loaded-state refinement에 대한 ablation study, 정확도 검증(reference checker)까지. 정적·1회성(static, one-shot) assignment 설정을 평가 범위로 명시하며 동적 재배치는 다루지 않는다.

## 3. 핵심 개념 상세

### Ontology 표현 — OWL + SWRL (custom formalism 아님)
- 표준 Semantic Web 스택을 그대로 사용한다: ontology 자체는 **OWL**로 정의하고 Python 라이브러리 **Owlready2**로 구축했으며, SWRL 규칙 추론에는 Owlready2에 번들된 OWL reasoner **Pellet 2.3.1**(OpenJDK 21.0.8 위에서 구동)을 사용한다. 즉 프레임워크가 독자적으로 고안한 custom 표현 언어가 아니라 OWL(TBox: class·property 정의) + ABox(Robot/Task/Place 인스턴스) + SWRL(declarative rule)이라는 기존 표준 조합이다.
- Robot Model: base footprint 치수, payload capacity(base/storage slot/attachment), storage slot 구조와 호환성, 장착 장비(mounted equipment), task capability와 object handling method를 표현.
- Task Model: place 정보(pickup/drop/working location), 대상 item 사양, 요구되는 payload·handling method·capability, 시간 제약을 표현.
- Place Model: 통과 가능한 폭·높이, 공간 연결 관계, traversability 제약을 표현.
- SWRL 규칙은 7개이며 폭/높이 제약, form-factor 호환성, handling method 매칭, base payload 임계값 등 "declarative하게 표현 가능한" 기본 feasibility 조건을 담당한다. subset 검사나 loaded-state 보정처럼 SWRL의 표현력을 벗어나는 조건은 Python 기반 procedural evaluation으로 별도 처리한다.

### `ReasonerOutput` — 실제 데이터 구조
- 단일 boolean이나 점수가 아니라 두 개의 구성요소를 갖는 구조화된 출력이다.
  - `TaskFeasibility`: task별 eligible robot 집합 + 그 각 eligible robot에 대한 loaded-state 기준 reachable place 집합.
  - `RobotReachability`: robot별 empty-state(비적재) 기준 reachable place 집합.
- 로봇이 feasible로 판정되려면 다음 4개 조건이 모두 성립해야 한다: (1) 로봇의 capability 집합이 task 요구 capability 집합을 포함, (2) form-factor 호환성 성립, (3) 적절한 handling method로 payload capacity 충족, (4) 요구되는 상태(empty/loaded)에서 reachability 유지.
- Loaded-state reachability 계산은 handling method에 따라 다르게 처리한다: `MANIPULATE` 방식은 `max(robot_height, item_height)`, 그 외 방식은 `robot_height + item_height`로 유효 높이를 계산 — 빈 상태에서는 통과 가능하지만 짐을 실으면 막히는 경로를 탐지할 수 있게 한다.

### Hybrid Reasoning 4단계 아키텍처
1. Semantic Knowledge Construction — ontology(TBox) 정의를 로드하고 Robot/Task/Place 인스턴스(ABox)를 구성.
2. Declarative Semantic Reasoning — Pellet을 통해 7개 SWRL 규칙을 적용해 기본 feasibility predicate를 도출.
3. Procedural Semantic Evaluation — SWRL 표현 범위를 벗어나는 조건(부분집합 검사, loaded-state 보정 등)을 Python으로 절차적으로 평가.
4. Output Generation — 두 결과를 결합해 `ReasonerOutput`(TaskFeasibility + RobotReachability)을 생성.

### Feasibility Reasoning과 Allocation 최적화의 분리 — 아키텍처적으로 실제로 분리됨을 확인
- 이 논문은 colleague의 주장대로 feasibility reasoning(capability filtering)과 최종 allocation 최적화를 두 개의 독립 단계로 실제로 분리하고, 그 접점을 `ReasonerOutput`이라는 공통 계약으로 명시한다.
- 실험에서 알고리즘적 성격이 서로 다른 4개 allocator — **Hungarian algorithm**(조합 최적, exact), **MILP**(exact 수리계획), **greedy**(휴리스틱), **genetic algorithm**(메타휴리스틱) — 가 모두 동일한 `ReasonerOutput`을 입력으로 사용해 유효한 assignment를 산출했다는 것이 이 분리 주장의 실증 근거다. 이는 "여러 allocator가 reasoner 출력을 공유할 수 있는 독립 2단계 구조"라는 주장을 뒷받침하는 직접적인 실험 설계다.
- 정량적으로도 declarative reasoning(SWRL/Pellet) 단계가 전체 실행 시간의 약 95%를 차지한다고 보고해, reasoning 비용과 allocation 비용이 실제로 분리 측정되고 있음을 보여준다.

## 4. 구조 및 흐름
1. Robot/Task/Place에 대한 OWL ontology(TBox)를 Owlready2로 구성하고, 구체 시나리오의 로봇·태스크·장소 인스턴스(ABox)를 채운다.
2. Pellet 2.3.1을 통해 7개 SWRL 규칙으로 declarative reasoning을 수행해 폭/높이, form-factor, handling method, payload 임계값 등 기본 feasibility predicate를 도출한다.
3. SWRL로 표현하기 어려운 조건(집합 포함 관계, loaded-state에 따른 reachability 재계산 등)을 Python procedural evaluation으로 보완한다.
4. 두 결과를 결합해 `TaskFeasibility`(task별 eligible robot + loaded-state reachable place)와 `RobotReachability`(robot별 empty-state reachable place)로 구성된 `ReasonerOutput`을 생성한다.
5. 이 `ReasonerOutput`을 Hungarian/MILP/greedy/genetic algorithm 4개 allocator에 공통 입력으로 제공해, 각자의 비용·목적함수 최적화는 독립적으로 수행하면서도 feasibility 제약은 동일하게 적용받도록 한다.
6. 4개 시나리오 × 3개 fleet 구성(이종 fleet, manipulator-only, no-lift 등)과 4개 allocator 조합, 그리고 3개 문제 규모 × 200개(총 600개) randomized instance에 대한 ablation study로 loaded-state refinement의 효과와 확장성(reasoning 시간·메모리)을 평가한다.
7. 별도의 reference checker 구현으로 80,663개 robot-task 쌍 전체에 대해 false positive/negative 0건을 확인해 reasoning 결과의 정확성을 검증한다.

## 5. 핵심 주장과 근거

| 주장 | 근거 |
|---|---|
| Feasibility reasoning을 allocation 최적화와 분리한 `ReasonerOutput`은 알고리즘적으로 이질적인 여러 allocator가 그대로 공유할 수 있는 공통 계약이다 | Hungarian(exact 조합최적)·MILP(exact 수리계획)·greedy(휴리스틱)·genetic algorithm(메타휴리스틱)이라는 서로 다른 4개 allocator가 모두 동일한 `ReasonerOutput`을 입력으로 사용해 유효한 assignment를 생성함을 실험으로 확인 |
| 적재 상태(loaded-state)를 반영한 reachability 보정이 정적 traversability 기준보다 더 정확한 feasibility 판단을 제공한다 | Loaded-state refinement가 14–15%의 무효(invalid) assignment를 사전에 차단; MANIPULATE 방식은 `max(robot_height, item_height)`, 그 외 방식은 `robot_height+item_height`로 유효 높이를 계산해 빈 상태에서는 통과 가능하지만 적재 시 막히는 경로를 탐지 |
| Hybrid reasoning(SWRL + procedural)이 실제로 정확하고 실행 비용을 지배하는 것은 declarative 단계다 | Reference checker로 80,663개 robot-task 쌍 전체에서 false positive/negative 0건 확인; declarative(SWRL/Pellet) reasoning이 전체 실행 시간의 약 95%를 차지 |
| Fleet 구성과 대상 물체의 적재 상태 모두가 assignment feasibility에 영향을 준다 | 4개 시나리오 × 3개 fleet 구성(이종 fleet, manipulator-only, no-lift 등)에 걸친 실험과 3개 문제 규모 × 200개(총 600개) randomized instance ablation에서 두 요인 모두 결과에 유의한 영향을 미침을 확인 |

## 6. 한계 및 부족한 점
- MDPI 페이지는 direct fetch(WebFetch, curl 모두)가 403으로 차단되어 원문을 프록시(r.jina.ai reader)와 Crossref API(정식 abstract·저자·DOI 메타데이터) 조합으로 확인했다. Method 섹션 요약은 프록시로 추출된 본문에 근거하며, 원문 PDF의 수식·표를 직접 대조하지는 못했다.
- 저자 스스로 명시한 범위 제한: 정적 환경 구성, 설계 시점에 선언되는 속성값, 1회성(one-shot) 할당 결정, traversability에 대한 envelope 근사만을 다루며, closed-loop 동적 재배치나 복합 capability를 위한 coalition formation은 향후 과제로 남겨두었다.
- 코드 공개 여부: GitHub 등 소스코드 저장소는 확인되지 않았다. Data Availability Statement는 "논문 본문과 Supplementary Materials에 포함되어 있으며 추가 문의는 교신저자에게"라고만 명시하고, 실제 공개된 Supplementary File은 S1(ontology schema)·S2(place model)·S3(robot class 정의)·S4(task 정의)·S5(generation rules)·S6(configuration files)로 **ontology/설정 자산**에 한정된다. Reasoning·procedural evaluation·4개 allocator를 구현한 Python 소스코드 자체가 공개되었다는 근거는 확인되지 않았다.
- 실험이 시뮬레이션/randomized instance 기반이며, 실제 물리 로봇 fleet에서의 실행 검증(hardware-in-the-loop)은 확인 범위 내에서 언급되지 않았다.

## 7. 원문 기반 핵심 문장
> "In heterogeneous multi-robot systems, allocating tasks efficiently requires determining whether each robot can actually carry out a given task. In existing multi-robot task allocation research, however, such task feasibility has typically been handled inside a particular optimizer or symbolic planner, while spatial traversability has been assessed against static criteria that cannot capture the changes induced by a robot's loaded state. This paper proposes an ontology-based semantic feasibility reasoning method for heterogeneous multi-robot task allocation... The reasoning result is formalized as an allocator-independent ReasonerOutput that serves as a common input for diverse allocation algorithms."
