# OASIS TOSCA 2.0

## 메타데이터
- categories: Requirement, [[Capability]], Orchestration
- domain: [[배포·오케스트레이션]]
- source: OASIS. "TOSCA Version 2.0."
- url: https://docs.oasis-open.org/tosca/TOSCA/v2.0/TOSCA-v2.0.html
- year: 2025
- authors: Chris Lauwers, Calin Curescu (editors)
- venue: OASIS Standard

## 1. 핵심 요약
- application component와 관계를 service topology로 기술하고 lifecycle orchestration 절차를 표현하는 언어다.
- node가 제공하는 capability와 다른 node가 요구하는 requirement를 명시적으로 구분한다.
- resolver가 requirement assignment의 후보 node/capability를 결정하고 node filter로 조건을 제한할 수 있다.

## 2. 문서 목적
topology와 orchestration을 결합해 deployment뿐 아니라 service lifecycle management를 model-driven 방식으로 자동화한다.

## 3. 핵심 개념 상세
- **Node:** application topology의 component 표현이다.
- **Capability:** node가 다른 node와의 관계에서 제공할 수 있는 기능 또는 특성이다.
- **Requirement:** node가 필요로 하는 capability와 관계 조건을 기술한다.
- **Node filter:** property와 capability 조건으로 selectable node를 제한한다.

## 4. 구조 및 흐름
service template이 node와 관계를 선언하면 processor의 resolver가 requirement를 만족하는 capability를 할당하고 orchestrator가 lifecycle 작업을 수행한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| topology 정보가 자동화를 구동한다 | 표준 초록이 dependencies, connections, compositions의 model-driven 자동화를 명시 |
| requirement와 capability allocation이 규범 구조다 | 표준 §8이 capability/requirement 정의·할당·node filter를 규정 |

## 6. 한계 및 부족한 점
- cloud application topology가 주 범위이며 물리 장치 안전, perception evidence, 실시간 deadline 의미는 정의하지 않는다.
- TOSCA DSL을 사용하려면 parser, resolver, orchestrator 동작과 conformance 요구를 함께 고려해야 한다.

## 7. 원문 기반 핵심 문장
> “TOSCA provides a language for describing application components and their relationships.”
