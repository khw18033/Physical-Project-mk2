# W3C Web of Things (WoT) Thing Description 1.1

## 메타데이터
- categories: ActionAffordance, safe/idempotent 액션 속성, invokeaction/queryaction/cancelaction
- domain: [[디지털트윈·상호운용]]
- source: W3C Web of Things Working Group. "Web of Things (WoT) Thing Description 1.1." W3C Recommendation, 2023.
- url: https://www.w3.org/TR/wot-thing-description11/
- year: 2023
- authors: W3C Web of Things Working Group
- venue: W3C Recommendation

## 1. 핵심 요약
- 2023년 12월 5일 W3C Recommendation으로 정식 발행된 문서로, 정식 표준 지위를 가진다.
- Thing Description은 IoT/Web of Things 장치(Thing)의 상호작용 인터페이스와 메타데이터를 기술하는 공통 정보 모델을 정의한다.
- 상호작용 인터페이스는 Property/Action/Event 세 종류의 Interaction Affordance로 분류되며, 이 중 ActionAffordance가 실행 가능한 동작을 기술한다.
- ActionAffordance는 input/output 데이터 스키마 외에 safe, idempotent, synchronous라는 세 가지 boolean 속성으로 실행 성격을 부가 기술한다.
- TD 1.1은 2020년 4월 9일 발행된 TD 1.0과 하위 호환을 명시적으로 유지한다.

## 2. 문서 목적
- 해결하려는 문제: 서로 다른 IoT 플랫폼·프로토콜의 장치가 각자 다른 방식으로 자신의 상호작용 인터페이스를 노출하면 시스템 간 상호운용이 어려운 문제.
- 기술적 목표: Property/Action/Event 세 종류의 Interaction Affordance와 그 실행 의미(상태 변경 여부, 반복 호출 안전성, 동기/비동기 여부)를 JSON 기반의 공통 vocabulary로 표준화하는 것.
- 다루는 범위: Thing Description 정보 모델 전체(이 문서에서는 ActionAffordance 관련 조항 위주로 확인). 구체 프로토콜(HTTP/CoAP/MQTT 등) 바인딩 세부사항은 별도의 WoT Binding Templates 문서로 위임한다.

## 3. 핵심 개념 상세
### ActionAffordance
- 원문 표현: "An Interaction Affordance that allows to invoke a function of the Thing, which manipulates state (e.g., toggling a lamp on or off) or triggers a process on the Thing (e.g., dim a lamp over time)."
- 정의: Thing이 노출하는, 상태를 변경하거나 프로세스를 트리거하는 실행 가능한 기능을 기술하는 Interaction Affordance.
- 역할: 장치나 서비스가 자신이 제공하는 실행 가능한 기능을 이름, 입출력 스키마, 실행 성격(상태 변경 여부·반복 호출 안전성·동기 여부)과 함께 스스로 기술하도록 하는 capability 서술 구조의 설계 근거로 널리 참고된다. 이런 필드 구성은 이종 장치를 다루는 시스템에서 "이 장치가 무엇을 할 수 있는가"를 표준화된 방식으로 질의할 수 있게 한다.

### safe
- 원문 표현: "Signals if the Action is safe (=true) or not. Used to signal if there is no internal state (cf. resource state) is changed when invoking an Action."
- 정의: 액션을 호출해도 Thing의 내부 resource state가 변하지 않는지를 나타내는 boolean 속성.
- 역할: 이름과 달리 기능 안전(functional safety)과는 무관한 개념이며, HTTP의 GET처럼 부작용 없는(side-effect-free) 조회성 호출을 구분하는 데 쓰이는 표현이다. 이름만 보고 산업 안전(safety-critical) 의미로 오해하지 않도록 주의가 필요한 대표적인 용어다.

### idempotent
- 원문 표현: "Indicates whether the Action is idempotent (=true) or not. Informs whether the Action can be called repeatedly with the same result, if present, based on the same input."
- 정의: 동일한 입력으로 액션을 반복 호출했을 때 동일한 결과가 나오는지를 나타내는 boolean 속성.
- 역할: AIP-155의 idempotency 개념과 함께, 동일 요청의 반복 호출이 안전한지 여부를 API 설계 단계에서부터 명시적으로 선언해 재시도 정책이나 중복 실행 방지 규칙을 세우는 근거로 쓰인다.

### synchronous
- 원문 표현: "Indicates whether the action is synchronous (=true) or not."
- 정의: 액션이 호출 즉시 완료되는 동기 방식인지, 별도의 진행 상황 추적이 필요한 비동기 방식인지를 구분하는 속성.
- 역할: 즉시 완료되는 호출과 진행 상황 추적이 필요한 장시간 작업을 API 설계 단계에서부터 구분해야 한다는 설계 원칙을 보여준다. 이 구분에 따라 후자는 별도의 상태 머신(예: 수락됨/실행 중/취소 중/완료 등)으로 진행 상황을 노출하는 설계로 이어지는 경우가 많다.

### invokeaction / queryaction / cancelaction
- 원문 표현: "the value assigned to op MUST either be `invokeaction`, `queryaction`, `cancelaction` or an [Array] containing a combination of these terms."
- 정의: Form 객체의 `op` 필드에 들어가는, 액션 호출·상태 조회·취소를 각각 나타내는 프로토콜 독립적 operation 어휘.
- 역할: 액션의 호출, 상태 조회, 취소라는 세 가지 동작을 프로토콜에 무관하게 별도의 operation으로 분리해 정의하는 설계의 선례로 참고된다. 이런 분리는 호출·조회·취소가 서로 다른 전달 보장이나 응답 시간 요구를 가질 때 유용하다.

## 4. 구조 및 흐름
1. Thing Description은 Thing의 Interaction Affordance를 Property/Action/Event 세 유형으로 분류한다.
2. ActionAffordance는 `input`/`output` DataSchema로 액션의 파라미터·결과 형식을 기술한다.
3. `safe`/`idempotent`/`synchronous` 세 boolean 속성으로 액션의 실행 성격(상태 변경 여부, 반복 호출 안전성, 동기 여부)을 부가로 기술한다.
4. Form 객체의 `op` 값(`invokeaction`/`queryaction`/`cancelaction` 또는 이들의 조합)이 실제 호출·조회·취소 동작을 구체 프로토콜 바인딩에 연결한다.
5. HTTP/CoAP/MQTT 등 프로토콜별 세부 바인딩은 TD 1.1 본문이 아니라 별도의 WoT Binding Templates 문서로 위임되어, TD 정보 모델 자체는 프로토콜 독립적으로 유지된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| ActionAffordance는 상태 변경 여부와 반복 호출 안전성을 별도 속성으로 명시적으로 구분해 기술해야 한다 | ActionAffordance 정의 표(§5.3.1.4, Table 6)에 `safe`와 `idempotent`가 서로 다른 boolean 필드로 정의됨 |
| TD 1.1은 이전 버전과의 상호운용을 깨지 않는다 | "documents created with version 1.0 of this specification remain compatible with Thing Description 1.1" |
| 프로토콜 바인딩은 TD 정보 모델과 분리되어야 한다 | `invokeaction`/`queryaction`/`cancelaction` 등 `op` 값은 프로토콜 독립적 vocabulary이며, 실제 전송 세부는 별도 WoT Binding Templates로 위임됨 |

## 6. 한계 및 부족한 점
- 이번에 확인한 ActionAffordance 관련 조항 범위 안에서는 TD 스펙 자체가 스스로 명시하는 결함·미해결 논의는 뚜렷하게 확인되지 않았고, 대신 필드 수준의 불안정성 경고만 확인되었다 — 예를 들어 `format` 관련 항목은 "may be replaced by another mechanism or removed in a future JSON Schema version"이라고 명시되어 있어 완전히 안정된 필드는 아니다.
- 이름 오용의 위험은 스펙 자체의 결함이라기보다 이 스펙을 참고하는 쪽이 주의해야 할 함정이다: `safe`라는 이름만 보고 산업 안전(functional safety) 개념으로 오해하면 위험하며, 실제로는 "리소스 상태 불변"이라는 훨씬 좁은 의미일 뿐이다.
- WoT 전체 런타임(Thing Description JSON-LD 문서, Forms 기반 프로토콜 바인딩, discovery 메커니즘)을 통째로 도입하는 대신, ActionAffordance의 필드 설계 아이디어(입출력 스키마 + safe/idempotent/synchronous 같은 실행 성격 플래그)만 다른 시스템의 capability 서술 구조에 반영하는 것도 흔한 실무 패턴이다. 전체 런타임을 채택하면 WoT 생태계 특유의 문서 포맷·discovery 프로토콜 종속성이 함께 따라오기 때문이다.

## 7. 원문 기반 핵심 문장
> "An Interaction Affordance that allows to invoke a function of the Thing, which manipulates state (e.g., toggling a lamp on or off) or triggers a process on the Thing (e.g., dim a lamp over time)."
