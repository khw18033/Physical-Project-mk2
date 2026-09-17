# Protocol Buffers

## 메타데이터
- categories: .proto Schema 정의, Field Number과 Schema Evolution, Binary Wire Format, 언어 중립 코드 생성
- domain: [[전송·프로토콜]]
- source: Google. "Protocol Buffers Documentation." protobuf.dev, 확인 필요.
- url: https://protobuf.dev/
- year: 확인 필요
- authors: Google
- venue: protobuf.dev (공식 문서 사이트)

## 1. 핵심 요약
- Protocol Buffers는 Google이 만든 언어 중립·플랫폼 중립의 확장 가능한 구조화 데이터 직렬화 메커니즘이다.
- .proto 파일에 스키마를 한 번 정의하면 C++, C#, Dart, Go, Java, Kotlin, Objective-C, Python, Rust, Ruby, PHP(proto3) 등 여러 언어용 코드가 자동 생성된다.
- 각 필드는 고유한 field number를 가지며, 이 번호는 wire format에서 필드를 식별하는 근거이므로 메시지가 사용 중일 때는 변경할 수 없다.
- 필드를 삭제할 때 번호를 `reserved`로 등록하지 않으면 번호 재사용으로 디코딩 모호성, 데이터 손상, PII/SPII 유출 위험이 있다. 반대로 새 필드 추가는 기존 파서와 호환되므로 안전하다.

## 2. 문서 목적
- 해결하려는 문제: 서로 다른 언어·플랫폼 간에 구조화된 데이터를 직렬화·역직렬화할 때 XML보다 가볍고 빠르면서도, 스키마 변경(필드 추가/삭제)에도 하위 호환을 유지할 수 있는 방법이 필요.
- 기술적 목표: .proto 스키마 정의 언어와 field number 기반 binary wire format을 통해, 언어·플랫폼에 종속되지 않는 코드 생성과 명시적인 스키마 진화(schema evolution) 규칙을 제공하는 것.
- 다루는 범위: proto3 언어 문법, 메시지·필드 타입 정의, field number 규칙과 reserved 선언, 스키마 업데이트(필드 추가/삭제/변경) 시 호환성 규칙, 여러 언어용 코드 생성기.

## 3. 핵심 개념 상세

### .proto Schema 정의
- 원문 표현: "The first line of the file specifies that you're using the proto3 revision of the protobuf language spec."
- 정의: 메시지 타입과 각 필드의 이름·타입·번호를 선언하는 protobuf 자체의 인터페이스 정의 언어(IDL) 파일.
- 역할: 여러 서비스·언어·팀이 동시에 소비해야 하는 API나 메시지 스키마(예: 명령·이벤트·상태 계약)를 정의할 때 canonical schema 형식으로 널리 채택된다.

### Field Number
- 원문 표현: "This number cannot be changed once your message type is in use because it identifies the field in the message wire format." / "You must give each field in your message definition a number between 1 and 536,870,911"
- 정의: 각 필드에 부여하는 고유 정수 식별자로, wire format에서 필드를 식별하는 유일한 근거이며 필드 이름이 아니라 번호가 직렬화 형식을 결정한다.
- 역할: 메시지 스키마가 버전업되어도 wire 호환성을 유지하려면 필드 번호를 고정해야 하며, "필드 번호 변경은 사실상 필드 삭제 + 새 필드 생성과 같다"는 규칙이 스키마 변경 절차 전반에 그대로 적용된다.

### Schema Evolution과 Reserved
- 원문 표현: "If you update a message type by entirely deleting a field, or commenting it out, future developers can reuse the field number when making their own updates to the type... To make sure this doesn't happen, add your deleted field number to the reserved list." / "Adding new fields is safe."
- 정의: 필드를 삭제할 때 해당 번호를 `reserved`로 등록해 재사용을 막고, 새 필드 추가는 기존 파서와 호환되도록 허용하는 하위·상위 호환 규칙.
- 역할: 여러 서비스나 노드가 서로 다른 시점에 순차적으로 배포되는 분산 시스템에서는 구버전 파서가 신버전 메시지를 안전하게 처리할 수 있어야 하므로, 이 규칙은 롤링 배포 순서 제약과 직접 연결된다.

### 언어 중립 코드 생성
- 원문 표현: "Protocol Buffers are language-neutral, platform-neutral extensible mechanisms for serializing structured data."
- 정의: 하나의 .proto 정의로부터 여러 프로그래밍 언어용 직렬화·역직렬화 코드를 자동 생성하는 메커니즘.
- 역할: 서로 다른 언어·런타임으로 구현된 여러 서비스나 컴포넌트가 동일한 메시지 계약을 공유할 수 있게 하는 근거이며, 마이크로서비스·이기종 클라이언트 환경에서 스키마 정의와 직렬화 코드를 중복 구현하지 않게 해 준다.

## 4. 구조 및 흐름
1. .proto 파일에 `syntax = "proto3"` 선언과 message 타입, 각 필드의 이름·타입·번호를 정의한다.
2. protoc(또는 언어별 플러그인)이 .proto 파일을 읽어 대상 언어의 클래스/구조체 코드를 생성한다.
3. 생성된 코드로 애플리케이션이 구조화 데이터를 객체로 다루고, 필요 시 binary wire format으로 직렬화해 전송한다.
4. 스키마를 변경할 때는 필드 번호를 유지한 채 새 필드만 추가하거나, 삭제한 필드 번호를 reserved로 등록해 향후 충돌을 막는다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Protocol Buffers는 XML보다 작고 빠르고 단순하다 | "think XML, but smaller, faster, and simpler" |
| field number는 한 번 사용되면 변경하면 안 된다 | field number가 wire format에서 필드를 식별하는 유일한 근거이기 때문에, 변경 시 기존 직렬화 데이터와의 호환성이 깨짐 |
| 필드 번호 재사용은 심각한 위험을 유발할 수 있다 | "Encoding a field using one definition and then decoding that same field with a different definition can lead to: ... Leaked PII/SPII, Data corruption" |
| 새 필드 추가는 안전하다 | "If you add new fields, any messages serialized by code using your 'old' message format can still be parsed by your new generated code." |

## 6. 한계 및 부족한 점
- 공식 문서 자체가 필드 번호 재사용의 위험을 명시적으로 경고하지만, 이를 방지하는 강제 메커니즘은 개발자가 `reserved`를 직접 선언하는 규율에 의존하며 자동 검증이 항상 보장되는지는 이번 조사 범위에서 확인하지 못했다.
- 이번 조사에서는 protobuf.dev의 개요·proto3 가이드 페이지만 확인했고, encoding 세부 규격(정확한 wire type 비트 구조 등)이나 성능 벤치마크 수치는 확인하지 못했다(확인 안 됨).
- 문서 발행 연도가 명시적으로 표기되어 있지 않아(지속 갱신되는 웹 문서) "year"를 특정 연도로 단정할 수 없다.

## 7. 원문 기반 핵심 문장
> "Protocol Buffers are language-neutral, platform-neutral extensible mechanisms for serializing structured data."
