# RFC 3550: RTP — A Transport Protocol for Real-Time Applications

## 메타데이터
- categories: Sequence Number 기반 손실 탐지, RTP Timestamp, SSRC 식별자, RTCP 제어 프로토콜
- domain: [[전송·프로토콜]]
- source: Schulzrinne, H., Casner, S., Frederick, R., Jacobson, V. "RTP: A Transport Protocol for Real-Time Applications." RFC 3550, IETF, 2003.
- url: https://www.rfc-editor.org/rfc/rfc3550
- year: 2003
- authors: H. Schulzrinne, S. Casner, R. Frederick, V. Jacobson
- venue: IETF RFC (Standards Track, Obsoletes RFC 1889)

## 1. 핵심 요약
- RTP(Real-time Transport Protocol)는 오디오·비디오·시뮬레이션 데이터처럼 실시간 특성을 가진 데이터를 유니캐스트 또는 멀티캐스트로 전달하기 위한 end-to-end network transport 기능을 제공한다.
- RTP 자체는 적시 전달(timely delivery)이나 QoS를 보장하지 않으며, 순서 보장이나 신뢰성 있는 전달도 보장하지 않는다 — 이런 보장은 하위 계층 서비스에 위임한다.
- 패킷마다 sequence number, timestamp, SSRC(synchronization source), payload type 필드를 실어 손실 탐지, 재생 동기화, 발신원 식별, 페이로드 포맷 해석을 지원한다.
- RTCP(RTP Control Protocol)는 세션 참여자 전체에 제어 패킷을 주기적으로 전송해 데이터 전달 품질을 모니터링하고 참가자 정보를 전달한다.
- 일반적으로 UDP 위에서 동작하며 UDP의 멀티플렉싱과 체크섬 기능을 활용하지만, RTP가 UDP를 필수로 요구하는 것은 아니다.

## 2. 문서 목적
- 해결하려는 문제: 오디오·비디오처럼 시간에 민감한 데이터를 네트워크로 전달할 때 필요한 손실 탐지, 재생 순서 복원, 발신원 식별, 페이로드 포맷 협상 같은 공통 기능이 표준화되어 있지 않은 문제.
- 기술적 목표: 특정 애플리케이션이나 특정 하위 전송 프로토콜에 묶이지 않는 범용 실시간 전송 기능(시퀀싱, 타임스탬핑, 발신원 식별, 페이로드 타입 식별)을 정의하는 것.
- 다루는 범위: RTP 데이터 패킷 헤더 포맷, RTCP 제어 패킷 포맷과 전송 규칙, SSRC 충돌 처리, 다양한 profile/payload format을 통한 확장 방식을 다룬다. 특정 코덱이나 특정 하위 네트워크(UDP/TCP 등)의 세부 구현은 profile 및 payload format 문서로 위임한다.

## 3. 핵심 개념 상세
### Sequence Number
- 원문 표현: "The sequence number increments by one for each RTP data packet sent, and may be used by the receiver to detect packet loss and to restore packet sequence."
- 정의: RTP 데이터 패킷마다 1씩 증가하는 필드로, 송신 순서를 나타낸다.
- 역할: 수신 측이 패킷 손실 여부를 탐지하고, UDP처럼 순서를 보장하지 않는 하위 전송 위에서도 원래 송신 순서를 복원하는 데 사용한다.

### Timestamp
- 원문 표현: "The timestamp reflects the sampling instant of the first octet in the RTP data packet. The sampling instant MUST be derived from a clock that increments monotonically and linearly in time to allow synchronization and jitter calculations."
- 정의: 패킷에 담긴 미디어 데이터의 첫 옥텟이 샘플링된 시점을 나타내는 값으로, 단조 증가하는 클록에서 유도된다.
- 역할: 수신 측 재생 시점 동기화와 jitter(수신 간격 변동) 계산의 기준이 된다.

### SSRC (Synchronization Source)
- 원문 표현: "The SSRC field identifies the synchronization source. This identifier SHOULD be chosen randomly, with the intent that no two synchronization sources within the same RTP session will have the same SSRC identifier."
- 정의: 동일 RTP 세션 내에서 각 스트림 발신원을 구분하는 무작위 선택 식별자.
- 역할: 여러 발신원이 섞여 전달될 수 있는 세션에서 어느 패킷이 어느 스트림에 속하는지 식별하는 기준을 제공한다.

### Payload Type
- 원문 표현: "This field identifies the format of the RTP payload and determines its interpretation by the application. A profile MAY specify a default static mapping of payload type codes to payload formats."
- 정의: RTP payload에 실린 데이터의 형식(코덱 등)을 나타내는 필드.
- 역할: 수신 측 애플리케이션이 페이로드를 어떤 포맷으로 해석해야 하는지 결정하게 한다. JPEG payload처럼 특정 payload format(RFC 2435 등)이 이 필드 값에 대응한다.

### RTCP (RTP Control Protocol)
- 원문 표현: "The RTP control protocol (RTCP) is based on the periodic transmission of control packets to all participants in the session, using the same distribution mechanism as the data packets."
- 정의: 데이터 패킷과 동일한 분배 메커니즘으로 세션 참가자 전체에 주기적으로 전송되는 제어 패킷 프로토콜.
- 역할: 전달 품질 모니터링, 참가자 식별, 세션 규모 추정 등 RTP 데이터 패킷 자체가 담지 않는 세션 수준 정보를 제공한다.

### Delivery 미보장
- 원문 표현: "Note that RTP itself does not provide any mechanism to ensure timely delivery or provide other quality-of-service guarantees, but relies on lower-layer services to do so. It does not guarantee delivery or prevent out-of-order delivery, nor does it assume that the underlying network is reliable and delivers packets in sequence."
- 정의: RTP는 전달 보장, 순서 보장, QoS 보장 메커니즘을 자체적으로 갖지 않는다는 명시적 선언.
- 역할: RTP 위에 얹히는 애플리케이션이 손실·역전된 패킷을 스스로 처리(재전송, FEC, jitter buffer, 애플리케이션 수준 순서 복원 등)해야 한다는 설계 전제를 제공하며, 이 책임을 하위 프로토콜이 아니라 애플리케이션 쪽에 남겨둔다.

## 4. 구조 및 흐름
1. 송신 측이 미디어 데이터를 RTP 패킷으로 나누고, 각 패킷에 sequence number(1씩 증가), timestamp(샘플링 시각), SSRC(발신원 식별자), payload type을 채운 RTP 헤더를 붙인다.
2. RTP 패킷은 일반적으로 UDP 위에서 전송되며("Applications typically run RTP on top of UDP to make use of its multiplexing and checksum services"), UDP의 멀티플렉싱·체크섬 기능을 활용한다.
3. 수신 측은 sequence number로 손실된 패킷과 도착 순서가 뒤바뀐 패킷을 탐지하고, timestamp를 기준으로 재생 순서와 타이밍을 복원한다.
4. RTCP 패킷이 데이터 패킷과 같은 배포 경로로 주기적으로 함께 전송되어 수신 품질 통계와 참가자 정보를 세션 구성원에게 알린다.
5. 실제 페이로드(예: JPEG 프레임)의 세부 포맷은 RTP 자체가 아니라 별도의 payload format 명세(RFC 2435 등)가 정의하며, RTP 헤더의 payload type 필드가 이를 가리킨다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| RTP는 실시간 데이터를 위한 범용 전송 기능을 제공하지만 전달을 보장하지 않는다 | "RTP itself does not provide any mechanism to ensure timely delivery... It does not guarantee delivery or prevent out-of-order delivery" |
| sequence number만으로 손실 탐지와 순서 복원이 가능하다 | "may be used by the receiver to detect packet loss and to restore packet sequence" |
| RTP는 특정 하위 전송 프로토콜에 묶이지 않지만 UDP와 함께 쓰이는 것이 일반적이다 | "Applications typically run RTP on top of UDP to make use of its multiplexing and checksum services" |

## 6. 한계 및 부족한 점
- RFC 3550 자체가 delivery 미보장, QoS 미보장을 명시하므로, RTP/UDP 기반 전송에서 패킷 손실·순서 역전·지연에 대한 실제 처리(재전송, FEC, jitter buffer 등)는 RTP 표준이 아니라 이를 사용하는 애플리케이션·미디어 스택 구현이 책임져야 한다.
- RTCP의 세부 패킷 포맷(SR/RR/SDES/BYE 등)과 대역폭 제한 알고리즘은 이번 조사에서 세부 인용을 확보하지 못했다. RTP를 사용한다고 해서 RTCP까지 반드시 함께 사용하는 것은 아니며, 실제 채택 여부는 구현·배포마다 다르다.
- 이 문서는 RFC 3550 landing 페이지 및 본문 일부 확인 결과이며, 전체 본문(특히 세션 참가자 timing rule, SSRC 충돌 해소 알고리즘 등)을 전수 확인하지는 않았다.

## 7. 원문 기반 핵심 문장
> "This memorandum describes RTP, the real-time transport protocol. RTP provides end-to-end network transport functions suitable for applications transmitting real-time data, such as audio, video or simulation data, over multicast or unicast network services."
