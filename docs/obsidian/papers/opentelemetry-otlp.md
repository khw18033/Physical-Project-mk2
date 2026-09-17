# OpenTelemetry Protocol (OTLP)

## 메타데이터
- categories: OTLP 전송 프로토콜, Trace와 Span, Trace Context Propagation, 3 Signal 구조
- domain: [[관측·보안]]
- source: OpenTelemetry Authors. "OpenTelemetry Protocol (OTLP) Specification." opentelemetry.io, 확인 필요.
- url: https://opentelemetry.io/docs/specs/otlp/
- year: 확인 필요
- authors: OpenTelemetry Authors (CNCF)
- venue: OpenTelemetry 공식 문서 (CNCF 프로젝트)

## 1. 핵심 요약
- OTLP(OpenTelemetry Protocol) v1.11.0 명세는 telemetry 소스, collector 등 중간 노드, backend 사이에서 telemetry 데이터를 인코딩·전송·전달하는 방식을 정의하는 범용 프로토콜이다.
- traces, metrics, logs 세 signal 모두에 대해 "Stable" 상태이며, profiles signal은 아직 개발 중이다.
- gRPC(기본 포트 4317)와 HTTP(기본 포트 4318, HTTP/1.1·HTTP/2) 두 전송 방식을 정의하고, payload는 Protobuf 스키마 기반으로 binary 또는 JSON 인코딩을 지원한다.
- Trace는 하나의 요청이 애플리케이션을 통과하는 경로 전체를 나타내며, Span은 그 경로를 구성하는 개별 작업 단위, Span Context는 Trace ID/Span ID/Trace Flags/Trace State를 담아 여러 프로세스·서비스에 걸친 span들을 연관짓는다.

## 2. 문서 목적
- 해결하려는 문제: 서로 다른 프로세스·서비스·데이터센터에서 발생하는 telemetry(trace/metric/log)를 특정 벤더 포맷에 묶이지 않고 표준화된 방식으로 수집·전달·상관(correlate)해야 하는 문제.
- 기술적 목표: Protobuf 스키마 기반의 payload 인코딩과 gRPC/HTTP 전송을 표준화하고, Context Propagation을 통해 여러 컴포넌트를 거치는 요청의 span들을 하나의 trace로 재구성할 수 있게 하는 것.
- 다루는 범위: OTLP의 전송 계층(gRPC/HTTP) 규격, payload 인코딩(binary/JSON Protobuf), signal별(traces/metrics/logs/profiles) 성숙도 상태, trace/span/span context 개념과 propagation.

## 3. 핵심 개념 상세

### OTLP (OpenTelemetry Protocol)
- 원문 표현: "The OpenTelemetry Protocol (OTLP) specification describes the encoding, transport, and delivery mechanism of telemetry data between telemetry sources, intermediate nodes such as collectors and telemetry backends." / "a general-purpose telemetry data delivery protocol designed in the scope of the OpenTelemetry project."
- 정의: telemetry 소스, collector 같은 중간 노드, backend 사이에서 telemetry 데이터를 어떻게 인코딩하고 전송·전달할지 정의하는 범용 프로토콜 명세.
- 역할: 여러 서비스·노드에 걸친 metric·log·trace를 특정 벤더 포맷에 묶이지 않고 표준화된 관측 경로로 수집·전달하려는 시스템에서 실제 전송 프로토콜로 채택되는 대표적인 선택지다.

### 3 Signal (Traces/Metrics/Logs)과 Stable 상태
- 원문 표현: "Status: Stable for the trace, metric and log signals. Development for the profiles signal."
- 정의: OTLP가 다루는 telemetry 데이터 종류를 traces/metrics/logs(그리고 개발 중인 profiles)로 구분하고, 각 signal의 명세 성숙도를 별도로 표기하는 상태 관리 방식.
- 역할: traces/metrics/logs 세 signal이 모두 OTLP로 안정적으로 다뤄질 수 있는 근거가 이 Stable 상태 표기에 있으며, signal마다 독립적인 성숙도와 취급 방식을 갖기 때문에 metric은 집계·요약하고 log/trace는 원본을 보존하는 등 signal별로 서로 다른 처리 정책을 설계하는 것이 일반적이다.

### gRPC/HTTP + Protobuf Payload
- 원문 표현: "OTLP defines the encoding of telemetry data and the protocol used to exchange data between the client and the server" through "Protocol Buffers schema."
- 정의: OTLP payload는 Protobuf 스키마로 정의되며, gRPC(unary request, 기본 포트 4317) 또는 HTTP(POST, 기본 포트 4318, binary Protobuf 또는 JSON Protobuf 인코딩)로 전송된다.
- 역할: 관측 시스템을 구축할 때 별도의 자체 관측 스키마를 새로 만들지 않고, 이미 널리 쓰이는 typed 직렬화 형식(Protobuf)을 그대로 재사용할 수 있게 하는 근거가 된다.

### Span과 Trace
- 원문 표현: Trace — "The path of a request through your application." / Span — "A span represents a unit of work or operation. Spans are the building blocks of Traces."
- 정의: Trace는 하나의 요청이 애플리케이션(들)을 통과하는 전체 경로이고, Span은 그 경로를 구성하는 개별 작업 단위다.
- 역할: 명령이나 요청의 실행 경로 지연·오류를 기술적으로 추적하는 단위이며, trace_id 같은 기술 추적 식별자는 업무적 요청 식별자(request id 등)와 분리해 관리하는 것이 일반적인 설계 관행이다.

### Span Context와 Trace Context Propagation
- 원문 표현: "Span context is an immutable object on every span that contains ... The Trace ID ... the span's Span ID, Trace Flags ..., Trace State ..." / "Context Propagation is the core concept that enables Distributed Tracing. With Context Propagation, Spans can be correlated with one another and assembled into a trace, regardless of where Spans are generated."
- 정의: 각 span이 갖는 불변 식별 정보(Trace ID, Span ID, Trace Flags, Trace State)와, 이 정보를 프로세스·서비스 경계를 넘어 전달해 서로 다른 곳에서 생성된 span들을 하나의 trace로 재조립하는 메커니즘.
- 역할: 요청이 여러 이기종 메시징 구간(예: 서로 다른 브로커나 프로토콜 브릿지)을 거칠 때 각 구간의 span을 하나의 trace로 연결해, 전체 경로 중 어디서 지연이나 단절이 발생했는지 진단할 수 있게 하는 핵심 메커니즘이다.

## 4. 구조 및 흐름
1. telemetry 소스(애플리케이션, 라이브러리)가 trace(span), metric, log 데이터를 OpenTelemetry SDK로 생성한다.
2. SDK가 이 데이터를 OTLP payload(Protobuf 스키마 기반)로 인코딩한다.
3. gRPC(4317) 또는 HTTP(4318, binary/JSON Protobuf)를 통해 collector 등 중간 노드로 전송한다.
4. collector가 필요 시 데이터를 가공(요약, 필터링 등)한 뒤 backend로 다시 OTLP로 전달하거나 다른 형식으로 export한다.
5. 여러 컴포넌트를 거치는 요청은 Trace Context Propagation을 통해 각 span의 Span Context(Trace ID 등)가 전달되어, backend에서 전체 trace로 재조립된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| OTLP는 telemetry 소스-중간노드-backend 사이의 범용 전달 프로토콜이다 | "a general-purpose telemetry data delivery protocol designed in the scope of the OpenTelemetry project" |
| traces/metrics/logs 세 signal은 이미 안정화됐다 | "Status: Stable for the trace, metric and log signals. Development for the profiles signal." |
| OTLP payload는 Protobuf 스키마로 정의된다 | "OTLP defines the encoding of telemetry data ... through Protocol Buffers schema" |
| trace는 서로 다른 프로세스에서 생성된 span들을 Context Propagation으로 상관시켜 만들어진다 | "With Context Propagation, Spans can be correlated with one another and assembled into a trace, regardless of where Spans are generated." |

## 6. 한계 및 부족한 점
- 이번 조사에서 확인한 "Stable" 상태는 v1.11.0 시점 명세 기준이며, profiles signal은 아직 development 단계라고 문서가 스스로 명시한다 — profiling telemetry까지 다뤄야 하는 경우에는 별도 확인이 필요하다.
- OTLP 명세 자체는 전송·인코딩 계층을 다루며, collector가 metric을 어떻게 "요약"할지에 대한 정책은 OTLP 명세의 범위가 아니라 별도 collector 설정·운영 정책의 문제다 — 이번 조사에서 OTLP 문서 자체가 이를 규정하지 않는다는 점만 확인했다.
- span 간 인과관계(causal relationship)의 세부 데이터 모델(parent span, links 등)은 이번 조사에서 traces 개념 페이지 수준까지만 확인했고, 전체 데이터 모델 명세(Span 필드 전체)는 별도 페이지 확인이 필요하다(확인 안 됨).

## 7. 원문 기반 핵심 문장
> "The OpenTelemetry Protocol (OTLP) specification describes the encoding, transport, and delivery mechanism of telemetry data between telemetry sources, intermediate nodes such as collectors and telemetry backends."
