# KServe Open Inference Protocol V2

## 메타데이터
- categories: Inference API, Model Serving, Metadata
- domain: [[전송·프로토콜]], [[배포·오케스트레이션]]
- source: KServe. "Open Inference Protocol V2."
- url: https://kserve.github.io/website/docs/concepts/architecture/data-plane/v2-protocol
- year: 2026
- authors: KServe Contributors
- venue: KServe Documentation

## 1. 핵심 요약
- 여러 model serving backend가 공통 data-plane API를 제공하도록 하는 protocol이다.
- server live/ready, model ready/metadata, inference endpoint를 정의한다.
- HTTP/REST와 gRPC mapping 및 tensor의 datatype·shape·content 표현을 규정한다.

## 2. 문서 목적
TensorFlow Serving, TorchServe, Triton 같은 서로 다른 serving system의 inference API 차이를 줄여 client와 server 사이의 상호운용성을 높인다.

## 3. 핵심 개념 상세
- **Server Live/Ready:** process 생존과 요청 처리 준비 여부를 구분한다.
- **Model Ready:** 특정 name/version model의 준비 상태를 확인한다.
- **Model Metadata:** name, versions, platform, input/output tensor metadata를 반환한다.
- **Infer:** model name과 선택 version에 tensor input을 전달하고 output tensor를 받는다.

## 4. 구조 및 흐름
client가 server와 model readiness를 확인하고 metadata로 tensor interface를 파악한 뒤 inference request를 전송한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| health와 inference는 별도 endpoint다 | protocol endpoint 목록이 live, ready, model ready, infer를 분리 |
| tensor interface는 metadata로 질의할 수 있다 | model metadata response가 datatype과 shape를 포함 |

## 6. 한계 및 부족한 점
- 좌표계, 물리 단위, 의미적 task capability, domain validity, safety role을 정의하지 않는다.
- benchmark 방법이나 provider 선택 정책은 범위 밖이다.

## 7. 원문 기반 핵심 문장
> “The Open Inference Protocol ... provides a standardized interface for model inference.”
