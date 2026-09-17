# RFC 6455: The WebSocket Protocol

## 메타데이터
- categories: HTTP Upgrade Handshake, Full-duplex 통신, Frame Opcode, Closing Handshake
- domain: [[전송·프로토콜]]
- source: Fette, I., Melnikov, A. "The WebSocket Protocol." RFC 6455, IETF, 2011.
- url: https://www.rfc-editor.org/rfc/rfc6455
- year: 2011
- authors: I. Fette, A. Melnikov
- venue: IETF RFC (Proposed Standard)

## 1. 핵심 요약
- WebSocket 프로토콜은 통제된 환경에서 실행되는(브라우저 등의) 코드와, 그 코드로부터의 통신을 허용(opt-in)한 원격 호스트 사이의 양방향 통신을 가능하게 한다.
- 연결은 기존 HTTP 인프라와 호환되도록 HTTP Upgrade 요청으로 시작하는 opening handshake로 수립되며, 같은 포트를 HTTP와 WebSocket 클라이언트가 함께 사용할 수 있다.
- handshake가 성공하면 각 측이 독립적으로 원하는 시점에 데이터를 보낼 수 있는 양방향(full-duplex) 데이터 전송 채널이 된다.
- 데이터는 텍스트(UTF-8), 바이너리, control frame 등 타입이 구분된 frame 단위로 전송된다.
- 연결 종료는 한쪽이 특정 제어 시퀀스를 담은 control frame(Close frame)을 보내고 상대가 이에 대해 Close frame으로 응답하는 closing handshake로 이루어진다.

## 2. 문서 목적
- 해결하려는 문제: 브라우저 기반 애플리케이션이 서버와 지속적인 양방향 통신을 하려면 기존 HTTP의 요청-응답 모델로는 polling 등 비효율적인 방법에 의존해야 했던 문제.
- 기술적 목표: 기존 HTTP 인프라(포트, 프록시, 서버)와 호환되는 handshake로 연결을 수립한 뒤, 별도의 요청-응답 구조 없이 지속적으로 메시지를 주고받을 수 있는 경량 프레이밍 프로토콜을 정의하는 것.
- 다루는 범위: opening handshake(HTTP Upgrade 기반 클라이언트/서버 요구사항), 데이터 프레이밍 포맷(opcode, mask, payload length), 텍스트/바이너리/제어 프레임의 의미, closing handshake, 확장(extension)과 서브프로토콜 협상 메커니즘.

## 3. 핵심 개념 상세
### Opening Handshake(HTTP Upgrade)
- 원문 표현: "The opening handshake is intended to be compatible with HTTP-based server-side software and intermediaries, so that a single port can be used by both HTTP clients talking to that server and WebSocket clients talking to that server. To this end, the WebSocket client's handshake is an HTTP Upgrade request"
- 정의: WebSocket 연결이 일반 HTTP 요청으로 시작해 `Upgrade` 헤더를 통해 WebSocket 프로토콜로 전환되는 초기 협상 절차.
- 역할: 서버 push, 실시간 대시보드, 채팅, 라이브 알림처럼 지속적인 양방향 통신이 필요한 서비스가 기존 HTTP 인프라(리버스 프록시, 로드밸런서, 방화벽 포트 정책) 위에서 별도 포트 개방 없이 동작할 수 있게 하는 근거다.

### Full-duplex 통신
- 원문 표현: "Once the client and server have both sent their handshakes, and if the handshake was successful, then the data transfer part starts. This is a two-way communication channel where each side can, independently from the other, send data at will."
- 정의: handshake 이후 클라이언트와 서버가 서로 독립적으로 임의 시점에 데이터를 보낼 수 있는 양방향 채널.
- 역할: 서버가 클라이언트의 요청 없이도 이벤트·상태 갱신을 push 방식으로 지속 전달하면서, 클라이언트 측 명령·제어 메시지도 같은 연결 위에서 함께 주고받을 수 있는 전송 모델의 근거가 된다. HTTP 폴링처럼 매번 새 요청을 여는 오버헤드 없이 저지연 양방향 교환이 필요한 경우에 적합하다.

### Frame과 Opcode
- 원문 표현: "A frame has an associated type. Each frame belonging to the same message contains the same type of data... there are types for textual data (which is interpreted as UTF-8 text), binary data (whose interpretation is left up to the application), and control frames..."
- 정의: WebSocket 메시지는 하나 이상의 frame으로 구성되며, 각 frame은 opcode로 텍스트/바이너리/제어 프레임 등 타입이 구분된다.
- 역할: JSON 등 구조화된 메타데이터는 텍스트 frame으로, 이미지·오디오 청크 같은 원시 데이터는 바이너리 frame으로 구분해 실어 보낼 수 있는 최소 프레이밍 단위를 제공하며, 수신 측이 opcode만으로 페이로드 해석 방식을 정할 수 있게 한다.

### Closing Handshake
- 원문 표현: "Either peer can send a control frame with data containing a specified control sequence to begin the closing handshake... Upon receiving such a frame, the other peer sends a Close frame in response, if it hasn't already sent one."
- 정의: 한쪽이 Close frame을 보내 연결 종료를 시작하고, 상대가 Close frame으로 응답하는 절차.
- 역할: 클라이언트가 연결을 끊거나 서버 쪽 세션이 종료될 때, TCP 연결을 강제로 끊는 대신 양측이 종료 사실을 명시적으로 확인하는 절차를 제공해 미전송 데이터 유실이나 어중간한 연결 종료를 줄인다.

## 4. 구조 및 흐름
1. 클라이언트(뷰어 등)가 대상 서버에 일반 HTTP 요청 형태로 `Upgrade: websocket` 헤더를 포함한 handshake 요청을 보낸다.
2. 서버가 이를 수락하면 HTTP 101 Switching Protocols 응답으로 handshake를 완료한다.
3. handshake 성공 후 연결은 양방향(full-duplex) 데이터 전송 채널이 되며, 양측이 독립적으로 frame을 주고받는다.
4. 데이터는 텍스트/바이너리/제어 frame으로 구분되어 전송되며, 하나의 논리적 메시지가 여러 frame으로 나뉘어 전송될 수 있다(fragmentation).
5. 연결을 종료할 때는 한쪽이 Close control frame을 보내 closing handshake를 시작하고, 상대가 Close frame으로 응답한 뒤 underlying TCP 연결을 닫는다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| WebSocket은 기존 HTTP 인프라와 호환되도록 설계되었다 | "The opening handshake is intended to be compatible with HTTP-based server-side software and intermediaries, so that a single port can be used by both HTTP clients... and WebSocket clients" |
| handshake 이후에는 완전한 양방향 채널이 된다 | "This is a two-way communication channel where each side can, independently from the other, send data at will." |
| 연결 종료는 일방적 차단이 아니라 상호 확인 절차를 거친다 | "Upon receiving such a frame, the other peer sends a Close frame in response, if it hasn't already sent one." |

## 6. 한계 및 부족한 점
- RFC 6455는 애플리케이션 계층 프레이밍과 handshake만 정의하며, 메시지 전달 순서 보장이나 재전송·QoS는 하위의 TCP에 의존한다 — 이번 조사에서 이 지점을 RFC가 명시적으로 한계로 서술하는 문장까지는 확인하지 못했다(원문 확인 안 됨).
- RFC 6455 자체는 텍스트/바이너리 frame에 실리는 페이로드의 의미(메시지 스키마, 필드 구조)에 대해 아무것도 규정하지 않는다. WebSocket은 전송·프레이밍 계층만 표준화하며, 페이로드 포맷과 의미 체계를 정의하는 것은 이를 사용하는 애플리케이션의 책임이다.
- 확장(permessage-deflate 등)이나 서브프로토콜 협상의 세부 규칙은 이번 조사에서 원문 인용을 확보하지 못했다.

## 7. 원문 기반 핵심 문장
> "The WebSocket Protocol enables two-way communication between a client running untrusted code in a controlled environment to a remote host that has opted-in to communications from that code."
