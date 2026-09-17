# Eclipse Paho MQTT Python Client

## 메타데이터
- categories: MQTT Client Library, LWT 설정, Automatic Reconnect
- domain: [[전송·프로토콜]]
- source: Eclipse Foundation. "Eclipse Paho Python Client." eclipse.dev, 확인 필요.
- url: https://eclipse.dev/paho/clients/python/
- year: 확인 필요
- authors: Eclipse Paho project
- venue: Eclipse Foundation (공식 문서 사이트)

## 1. 핵심 요약
- Eclipse Paho Python Client는 Python 3.7+ 환경에서 MQTT v5.0, v3.1.1, v3.1을 모두 지원하는 클라이언트 클래스를 제공하는 라이브러리다.
- Last Will and Testament(LWT) 설정, 연결 끊김 시 자동 재연결(automatic reconnect), 오프라인 상태에서의 메시지 버퍼링을 지원한다.
- TCP와 WebSocket 전송, SSL/TLS 암호화, blocking/non-blocking(비동기) API, 여러 서버로의 failover를 지원한다.
- `pip install paho-mqtt`로 설치하는 순수 클라이언트 라이브러리이며 broker 기능은 포함하지 않는다.

## 2. 문서 목적
- 해결하려는 문제: 자원이 제한된 말단(경량 디바이스) 환경에서 MQTT broker나 다른 서버형 미들웨어 없이, 클라이언트 라이브러리만으로 MQTT 프로토콜(연결, 발행/구독, LWT, 재연결)을 구현해야 하는 문제.
- 기술적 목표: 여러 MQTT 프로토콜 버전(v3.1/v3.1.1/v5.0)을 단일 Python 클라이언트 API로 지원하고, 연결 단절 시 자동 재연결·오프라인 버퍼링을 통해 애플리케이션이 저수준 재연결 로직을 직접 구현하지 않아도 되게 하는 것.
- 다루는 범위: 클라이언트 연결/해제, publish/subscribe API, QoS·LWT 설정, TLS, WebSocket transport, blocking/non-blocking 인터페이스, 자동 재연결 동작.

## 3. 핵심 개념 상세

### MQTT Client Library
- 원문 표현: "provides a client class with support for MQTT v5.0, MQTT v3.1.1, and v3.1 on Python 3.7+."
- 정의: broker와 직접 통신하는 MQTT 프로토콜 클라이언트 구현으로, 세 가지 프로토콜 버전을 하나의 Python API로 다룰 수 있게 하는 라이브러리.
- 역할: 자원이 제한된 엣지·IoT 디바이스가 무거운 서버형 미들웨어 없이 MQTT broker에 연결하기 위한 경량 클라이언트 구현으로 널리 쓰이며, 말단 장치가 클라이언트 라이브러리만 유지하고 broker·수집기 같은 서버 컴포넌트는 별도 노드에 두는 경량 실행 경계를 구현하는 전형적 구성요소다.

### 지원 프로토콜 버전
- 원문 표현: "provides a client class with support for MQTT v5.0, MQTT v3.1.1, and v3.1"
- 정의: 하나의 클라이언트가 v5.0, v3.1.1, v3.1 세 버전 중 선택해 연결할 수 있는 호환성.
- 역할: MQTT 5.0의 Properties 기반 기능(예: Session Expiry, Response Topic)을 클라이언트 구현에서 실제로 사용할 수 있는 근거가 되지만, 상대 broker도 동일 버전을 지원해야 종단 간에 유효하다.

### LWT 설정
- 정의: 클라이언트 연결 시 Will Message(토픽, payload, QoS, retain 여부)를 미리 등록해 비정상 종료 시 broker가 대신 발행하게 하는 기능.
- 역할: 장치의 급사(비정상 연결 종료)를 감지하는 신호의 발신 지점이며, 클라이언트가 자신의 생사 신호를 broker에 위임해 별도의 heartbeat 폴링 없이도 연결 단절을 알릴 수 있게 하는 수단이다.

### Automatic Reconnect / Offline Buffering
- 원문 표현: "Can automatically reconnect to the server if the connection is lost" / "Will buffer messages whilst offline to send when the connection is re-established"
- 정의: 네트워크 단절 시 클라이언트가 스스로 재연결을 시도하고, 그 사이 발행하려던 메시지를 로컬에 버퍼링해 재연결 후 전송하는 동작.
- 역할: 네트워크가 불안정할 수 있는 엣지·IoT 환경에서 애플리케이션이 저수준 재연결 로직을 직접 구현하지 않아도 되게 해 주지만, 네트워크 단절 중에도 유지되어야 하는 로컬 안전·핵심 기능은 이 재연결·버퍼링 메커니즘 자체에 의존해서는 안 되며 별도로 설계해야 한다.

## 4. 구조 및 흐름
1. 애플리케이션이 Paho Client 객체를 생성하고 프로토콜 버전(v3.1/v3.1.1/v5.0)을 선택한다.
2. CONNECT 시 필요하면 Will Message(LWT), TLS 설정, 인증 정보를 지정한다.
3. 클라이언트가 broker에 연결해 원하는 topic을 구독하거나 메시지를 발행(publish)한다.
4. 연결이 끊기면 클라이언트가 자동 재연결을 시도하며, 그동안 발행 요청은 로컬에 버퍼링된다.
5. 재연결에 성공하면 버퍼링된 메시지를 전송하고 구독 상태를 복원한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| 하나의 클라이언트 API로 여러 MQTT 버전을 지원한다 | "provides a client class with support for MQTT v5.0, MQTT v3.1.1, and v3.1 on Python 3.7+" |
| 연결 단절에도 클라이언트가 스스로 복구를 시도한다 | "Can automatically reconnect to the server if the connection is lost" |
| 오프라인 상태에서도 메시지를 잃지 않고 재전송할 수 있다 | "Will buffer messages whilst offline to send when the connection is re-established" |

## 6. 한계 및 부족한 점
- 공식 문서 페이지에서 확인한 범위 내에서는 자동 재연결의 백오프(backoff) 정책이나 오프라인 버퍼의 최대 크기·정책에 대한 구체적 수치는 확인하지 못했다(확인 안 됨).
- 이 라이브러리는 클라이언트 구현일 뿐이므로 QoS 2의 "exactly once" 보장이나 세션 지속성은 상대 broker(Mosquitto)의 구현과 설정에 의존하며, 클라이언트 문서만으로는 종단 간 보장을 단정할 수 없다.
- 문서에 명시적 발행 연도가 확인되지 않아 "year"는 확인 필요로 남긴다.

## 7. 원문 기반 핵심 문장
> "provides a client class with support for MQTT v5.0, MQTT v3.1.1, and v3.1 on Python 3.7+."
