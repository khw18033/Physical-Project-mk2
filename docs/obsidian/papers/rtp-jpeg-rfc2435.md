# RFC 2435: RTP Payload Format for JPEG-compressed Video

## 메타데이터
- categories: JPEG Frame Fragmentation, RTP JPEG Header, Restart Marker Header
- domain: [[전송·프로토콜]]
- source: Berc, L., Fenner, W., Frederick, R., McCanne, S., Stewart, P. "RTP Payload Format for JPEG-compressed Video." RFC 2435, IETF, 1998.
- url: https://www.rfc-editor.org/rfc/rfc2435
- year: 1998
- authors: L. Berc, W. Fenner, R. Frederick, S. McCanne, P. Stewart
- venue: IETF RFC (Standards Track)

## 1. 핵심 요약
- RFC 2435는 JPEG로 압축된 비디오 스트림을 RTP(RFC 3550) payload로 실어 보내는 구체적인 포맷을 정의한다.
- 이 포맷은 프레임 간 코덱 파라미터(quantization table 등)가 거의 바뀌지 않는 실시간 비디오 스트림에 최적화되어 있다.
- JPEG 프레임은 네트워크의 최대 패킷 크기보다 큰 경우가 많아, 여러 RTP 패킷으로 fragmentation(분할)해 전송하고 수신 측이 재조립(reassembly)한다.
- 같은 프레임에 속한 모든 패킷은 동일한 RTP timestamp를 가지며, 프레임의 마지막 패킷에는 RTP marker bit가 설정된다.
- restart marker(타입 64~127)를 사용하는 경우, 이를 올바르게 디코딩하기 위한 추가 정보를 담는 별도의 Restart Marker header가 main JPEG header 바로 뒤에 위치해야 한다.

## 2. 문서 목적
- 해결하려는 문제: JPEG로 압축된 비디오 프레임을 RTP 위에서 전송할 때 필요한 fragmentation, 헤더 필드, quantization table 전달 방식이 표준화되어 있지 않은 문제.
- 기술적 목표: 프레임마다 JFIF 헤더 전체를 반복 전송하지 않고도(코덱 파라미터가 거의 바뀌지 않는다는 전제 하에) 효율적으로 JPEG 프레임을 RTP 패킷으로 나누고 재조립할 수 있는 최소한의 헤더 포맷을 정의하는 것.
- 다루는 범위: RTP/JPEG 메인 헤더 필드(Type-specific, Fragment Offset, Type, Q, Width, Height) 정의, quantization table 헤더, restart marker 헤더, fragmentation·reassembly 규칙. 특정 인코더·디코더 구현이나 RTP 자체의 전달 보장 문제는 다루지 않는다(RFC 3550 범위).

## 3. 핵심 개념 상세
### JPEG Frame Fragmentation/Reassembly
- 원문 표현: "Because JPEG frames are typically larger than the underlying network's maximum packet size, frames must often be fragmented into several packets." / "Each packet that makes up a single frame MUST have the same timestamp, and the RTP marker bit MUST be set on the last packet in a frame."
- 정의: 하나의 JPEG 프레임을 네트워크 MTU에 맞게 여러 RTP 패킷으로 나누어 보내고, 수신 측이 동일 timestamp를 가진 패킷들을 모아 marker bit가 설정된 패킷을 마지막으로 프레임을 재구성하는 절차.
- 역할: RTP/UDP 위에서 JPEG 영상을 전송할 때, 매 프레임을 하나의 UDP 데이터그램에 담지 않고 여러 패킷으로 분할·재조립할 수 있게 하는 표준 메커니즘이다. UDP는 데이터그램 크기 제한과 경로상 MTU 제약을 받으므로, 이 fragmentation 규칙이 없으면 각 송신단이 임의로 분할·재조립 방식을 정해야 한다. 다만 실제 구현이 이 fragmentation 규칙을 스펙 그대로 따르는지는 구현체마다 별도로 검증이 필요하다.

### RTP/JPEG 헤더(main JPEG header)
- 원문 표현: "The Fragment Offset is the offset in bytes of the current packet in the JPEG frame data." (Type-specific/Fragment Offset/Type/Q/Width/Height 필드 구성 확인)
- 정의: 각 RTP/JPEG 패킷 앞에 붙는 8바이트 헤더로 Type-specific(8bit), Fragment Offset(24bit), Type(8bit), Q(8bit, quantization table 지정), Width(8bit, 8픽셀 단위), Height(8bit, 8픽셀 단위) 필드로 구성된다.
- 역할: 수신 측이 별도의 out-of-band 협상 없이도 각 패킷이 프레임 내 어느 위치의 데이터인지(Fragment Offset), 어떤 quantization table을 쓰는지(Q), 이미지 크기가 얼마인지(Width/Height)를 패킷 자체에서 알 수 있게 한다.

### Restart Marker Header
- 원문 표현: "This header MUST be present immediately after the main JPEG header when using types 64-127. It provides the additional information required to properly decode a data stream containing restart markers."
- 정의: JPEG restart marker(타입 64-127)를 사용하는 스트림에서 main JPEG header 바로 뒤에 필수로 추가되는 헤더.
- 역할: restart marker가 포함된 JPEG 데이터 스트림을 수신 측이 올바르게 디코딩하는 데 필요한 추가 정보를 제공한다. restart marker를 쓰지 않는 스트림에서는 필요하지 않다.

## 4. 구조 및 흐름
1. 인코더가 JPEG 프레임을 생성한다(quantization table 등 코덱 파라미터는 프레임마다 거의 바뀌지 않는다고 전제).
2. 프레임 크기가 네트워크 MTU보다 크면 여러 RTP 패킷으로 나누고, 각 패킷 앞에 main JPEG header(Type-specific/Fragment Offset/Type/Q/Width/Height)를 붙인다.
3. restart marker를 사용하는 경우 main JPEG header 바로 뒤에 Restart Marker header를 추가로 붙인다.
4. 동일 프레임에 속한 모든 패킷에 같은 RTP timestamp(RFC 3550 필드)를 부여하고, 프레임의 마지막 패킷에 RTP marker bit를 설정한다.
5. 수신 측은 timestamp가 같은 패킷들을 Fragment Offset 순으로 모으고, marker bit가 설정된 패킷을 프레임의 끝으로 인식해 재조립한 뒤 JPEG 디코더에 전달한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| 이 포맷은 코덱 파라미터가 프레임마다 거의 바뀌지 않는 실시간 스트림에 최적화되어 있다 | "The packet format is optimized for real-time video streams where codec parameters change rarely from frame to frame." |
| 큰 JPEG 프레임은 여러 RTP 패킷으로 분할 전송해야 한다 | "Because JPEG frames are typically larger than the underlying network's maximum packet size, frames must often be fragmented into several packets." |
| 수신 측은 timestamp와 marker bit만으로 프레임 경계를 알 수 있다 | "Each packet that makes up a single frame MUST have the same timestamp, and the RTP marker bit MUST be set on the last packet in a frame." |

## 6. 한계 및 부족한 점
- 이 표준은 코덱 파라미터가 프레임 간 거의 바뀌지 않는다는 전제 위에 설계되어 있어, 매 프레임 quantization table이나 해상도가 크게 바뀌는 스트림에는 오버헤드나 제약이 있을 수 있다(본문에서 이 트레이드오프 자체를 심층적으로 논의하는지는 이번 조사 범위에서 추가 확인하지 못했다).
- 실제 구현이 RFC 2435의 fragmentation·헤더 규칙을 완전히 준수하는지는 스펙 문서만으로는 확인할 수 없고, 코드 수준의 별도 검증이 필요하다 — "RTP/JPEG를 쓴다"는 사실과 "RFC 2435를 정확히 준수한다"는 사실은 다른 주장이므로 혼동하지 않아야 한다.
- restart marker header의 세부 필드 구성(Restart Interval, F/L count 등)은 이번 조사에서 필드명까지 상세히 인용하지 못했다 — 필요 시 원문 §3.1.7 확인 필요.

## 7. 원문 기반 핵심 문장
> "This memo describes the RTP payload format for JPEG video streams. The packet format is optimized for real-time video streams where codec parameters change rarely from frame to frame."
