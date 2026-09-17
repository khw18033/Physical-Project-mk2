# IDTA Capability Description 1.0

## 메타데이터
- categories: [[Asset Administration Shell]], [[Capability]], [[Skill]]
- domain: [[디지털트윈·상호운용]]
- source: IDTA. "Capability Description Version 1.0." IDTA 02020.
- url: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Capability%20Description/1/0
- year: 2025
- authors: Industrial Digital Twin Association
- venue: IDTA Submodel Template Specification

## 1. 핵심 요약
- 공정·제품의 required capability와 resource의 provided capability를 같은 방식으로 모델링한다.
- capability를 물리·가상 세계에 효과를 만들기 위한 구현 독립적 기능 명세로 다룬다.
- property가 능력을 구체화하고 constraint가 이를 제한하며 skill이 capability를 실현한다.

## 2. 문서 목적
required/provided capability를 신뢰성 있게 비교하여 생산 계획과 orchestration을 지원하는 AAS submodel 구조를 정의한다.

## 3. 핵심 개념 상세
- **Property:** 최대 속도, 허용 오차, 온도 범위처럼 capability를 상세화한다.
- **Property constraint:** property를 precondition, invariant, postcondition으로 제한할 수 있다.
- **Transition constraint:** 여러 capability 사이의 순차 또는 병렬 관계를 나타낸다.
- **Skill:** capability를 기술적 또는 software solution module로 구현한다.

## 4. 구조 및 흐름
공정 요구를 required capability로 표현하고 resource의 provided capability와 비교한다. 조건이 맞는 capability는 이를 실현하는 skill과 연결된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| capability와 구현은 구별된다 | 공식 scope가 capability를 implementation-independent specification으로 정의하고 skill이 실현한다고 명시 |
| matching은 주요 용도다 | required/provided capability 비교가 planning과 orchestration을 지원한다고 명시 |

## 6. 한계 및 부족한 점
- 산업 생산을 주 적용 영역으로 삼으며 AI inference 호출이나 범용 로봇 명령 lifecycle은 정의하지 않는다.
- 이 문서는 AAS submodel template이므로 이를 그대로 교환하려면 AAS metamodel과 식별 체계가 필요하다.

## 7. 원문 기반 핵심 문장
> “The Capability Description Submodel is used to model process or product requirements ... and resource capabilities.”
