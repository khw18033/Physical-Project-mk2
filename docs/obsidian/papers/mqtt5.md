# MQTT Version 5.0

## 메타데이터
- categories: QoS 전달 보장 레벨, Last Will and Testament, Session Message Expiry Interval, Request Response 패턴
- domain: [[전송·프로토콜]]
- source: OASIS. "MQTT Version 5.0." OASIS Standard, 2019.
- url: https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html
- year: 2019
- authors: OASIS MQTT Technical Committee
- venue: OASIS Standard

## 1. 핵심 요약
- MQTT 5.0은 2019년 3월 7일 OASIS Standard로 공표된 발행/구독(pub/sub) 기반 경량 메시징 프로토콜 규격이다.
- QoS 0/1/2 세 가지 전달 보장 수준을 정의하며, QoS 0은 best-effort(손실 가능), QoS 1은 최소 한 번(중복 가능), QoS 2는 정확히 한 번 전달을 보장한다.
- Will Message(LWT), Session Expiry Interval, Message Expiry Interval 등 연결 단절·세션 수명·메시지 유효기간을 다루는 속성(Properties)을 정의한다.
- Response Topic과 Correlation Data 속성으로 MQTT 위에서 request/response 패턴을 구현할 수 있는 구조를 표준화한다.

## 2. 문서 목적
- 해결하려는 문제: 저전력·저대역폭·불안정한 네트워크 환경에서도 신뢰성 있게 동작해야 하는 발행/구독 메시징을, 전달 보장 수준·세션 지속성·연결 단절 통지까지 포함해 표준화하는 것.
- 기술적 목표: broker를 중심으로 한 pub/sub 모델 위에 QoS, Will Message, 세션/메시지 만료, request/response 등 v5.0에서 새로 도입된 속성(Properties) 기반 확장 메커니즘을 정의하는 것.
- 다루는 범위: CONNECT/PUBLISH/SUBSCRIBE 등 제어 패킷 구조, QoS 흐름, 세션 상태 관리, Will Message 동작, 다양한 v5.0 Properties(Session/Message Expiry, Response Topic, Correlation Data 등), retained message 규칙.

## 3. 핵심 개념 상세

### QoS (Quality of Service)
- 원문 표현: QoS 0 — "messages are delivered according to the best efforts of the operating environment. Message loss can occur." / QoS 1 — "messages are assured to arrive but duplicates can occur." / QoS 2 — "messages are assured to arrive exactly once."
- 정의: publisher와 broker, broker와 subscriber 사이에서 메시지가 몇 번, 얼마나 확실하게 전달되는지를 정하는 세 단계(0/1/2) 합의 수준.
- 역할: 메시지 종류별로 요구되는 전달 보장 수준(유실돼도 괜찮은 상태값인지, 반드시 도달해야 하는 명령인지)을 선택하는 근거가 되지만, QoS는 전송 계층의 보장일 뿐 애플리케이션 수준의 정확히 한 번 처리(idempotency)까지는 보장하지 않으므로, 재전송에 안전해야 하는 동작에는 별도의 요청 식별자·중복 처리 로직을 상위 계층에 두는 경우가 많다.

### Will Message (Last Will and Testament)
- 원문 표현: "An Application Message which is published by the Server after the Network Connection is closed in cases where the Network Connection is not closed normally."
- 정의: 클라이언트가 CONNECT 시 미리 등록해 두고, 비정상 연결 종료 시 broker가 대신 발행하는 메시지.
- 역할: 네트워크가 불안정한 IoT·엣지 환경에서 장치의 비정상 연결 종료(급사)를 감지하는 표준 메커니즘으로 널리 쓰이며, 애플리케이션이 별도의 폴링 없이도 클라이언트 단절을 통지받아 장치 가용성 판정의 입력으로 활용할 수 있게 한다.

### Session Expiry Interval / Message Expiry Interval
- 원문 표현: Session Expiry Interval — "If the Session Expiry Interval is absent the value 0 is used. If it is set to 0, or is absent, the Session ends when the Network Connection is closed." / Message Expiry Interval — "the Four Byte value is the lifetime of the Will Message in seconds and is sent as the Publication Expiry Interval when the Server publishes the Will Message."
- 정의: 각각 연결이 끊긴 뒤 세션 상태(구독, 미전달 메시지 등)를 broker가 얼마나 유지할지, 그리고 개별 메시지(또는 Will Message)가 유효한 기간을 나타내는 속성.
- 역할: MQTT의 message expiry는 전송 계층에서 메시지가 유효한 기간을 다루는 개념일 뿐이며, 애플리케이션이 요청의 마감 시한(deadline)이나 오래된 요청(stale request) 여부를 판단해야 하는 경우에는 이를 전송 계층의 expiry와 혼동하지 않고 별도의 업무 규칙으로 정의해야 한다.

### Request/Response 패턴 (Response Topic, Correlation Data)
- 원문 표현: Response Topic — "a UTF-8 Encoded String which is used as the Topic Name for a response message... The presence of a Response Topic identifies the Will Message as a Request." / Correlation Data — "used by the sender of the Request Message to identify which request the Response Message is for when it is received."
- 정의: 요청 메시지에 응답을 받을 토픽(Response Topic)과 요청-응답을 매칭할 식별 데이터(Correlation Data)를 실어 MQTT 위에서 request/response 상호작용을 구현하는 v5.0 표준 속성.
- 역할: 명령이나 요청에 대한 수신 확인·처리 결과 회신 경로를 pub/sub 모델 위에 구성할 때 참고되는 표준 패턴이지만, 실무에서는 보통 애플리케이션 자체의 요청 식별자를 응답 매칭의 주 근거로 쓰고 전송 프로토콜의 상관 필드 자체에 업무 의미 계약을 전적으로 종속시키지 않는 편이 안전하다.

## 4. 구조 및 흐름
1. 클라이언트가 broker에 CONNECT하며 필요 시 Will Message, Session Expiry Interval 등 속성을 함께 전달한다.
2. 클라이언트가 topic을 구독(SUBSCRIBE)하거나 publisher가 topic에 메시지를 발행(PUBLISH)하며, 이때 QoS 레벨을 지정한다.
3. QoS 1/2인 경우 broker와 클라이언트 사이에 PUBACK/PUBREC/PUBREL/PUBCOMP 등 확인 패킷을 교환해 전달을 보장한다.
4. 네트워크 연결이 비정상 종료되면 broker가 등록된 Will Message를 발행하고, Session Expiry Interval에 따라 세션 상태를 유지하거나 폐기한다.
5. request/response가 필요한 경우 요청 메시지에 Response Topic과 Correlation Data를 실어 응답을 매칭한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| QoS 0은 손실 가능성이 있다 | "messages are delivered according to the best efforts of the operating environment. Message loss can occur." |
| QoS 2는 정확히 한 번 전달을 보장한다 | "messages are assured to arrive exactly once." |
| Will Message는 비정상 연결 종료를 감지하는 표준 메커니즘이다 | Will Message는 "Network Connection is not closed normally" 상황에서 서버가 대신 발행하도록 정의됨 |
| MQTT 5.0은 request/response 상호작용을 표준 속성으로 지원한다 | Response Topic/Correlation Data 속성이 CONNECT/PUBLISH Properties에 정의됨 |

## 6. 한계 및 부족한 점
- 이번 조사에서 확인한 범위 내에서 QoS 2("exactly once")는 프로토콜 수준의 메시지 전달 보장이며, 이것이 애플리케이션 수준(물리 동작 재실행 방지 등)의 idempotency까지 보장한다는 의미는 아니다. 따라서 정확히 한 번만 처리돼야 하는 물리적 부작용이 있는 동작에는 흔히 요청 ID 기반의 idempotency 계약을 애플리케이션 계층에 별도로 얹는다.
- 스펙 문서가 명시하는 QoS 정의가 네트워크 파티션, broker 재시작 등 모든 실패 모드에서까지 유지되는지에 대한 세부 조건은 이번 조사에서 확인하지 못했다(확인 안 됨).
- Session Expiry Interval, Message Expiry Interval 각각의 정확한 바이트 인코딩 규칙 이상의 세부 제약(예: 최대값, 브로커 구현별 차이)은 이번 조사 범위에서 전부 확인하지 못했다.

## 7. 원문 기반 핵심 문장
> "An Application Message which is published by the Server after the Network Connection is closed in cases where the Network Connection is not closed normally."
