# Grafana Tempo

## 메타데이터
- categories: Distributed Tracing Backend, Object Storage 기반 저장, OpenTelemetry 연동, Grafana 데이터소스 연동
- domain: [[관측·보안]]
- source: Grafana Labs. "Grafana Tempo documentation." Grafana Labs Documentation, 2026(access).
- url: https://grafana.com/docs/tempo/latest/
- year: 확인 필요(latest 문서, 페이지 자체에 개정 연도 명시 없음)
- authors: Grafana Labs
- venue: Grafana Labs 공식 문서 (grafana.com/docs/tempo)

## 1. 핵심 요약
- Grafana Tempo는 오픈소스이며 사용이 쉽고 대규모(high-scale)로 확장 가능한 distributed tracing backend라고 소개된다.
- Jaeger, Zipkin, OpenTelemetry 등 여러 오픈소스 tracing 프로토콜을 지원한다.
- 별도의 대규모 인덱스 없이 object storage만으로 운영 가능해 비용 효율적(cost-efficient)이라고 설명한다.
- Grafana에 기본 내장된 Tempo data source를 통해 네이티브로 연동되며, Mimir·Prometheus·Loki 등 Grafana 생태계 다른 signal과 깊이 통합된다.

## 2. 문서 목적
- 해결하려는 문제: 여러 애플리케이션 컴포넌트를 거치는 요청(request)의 전체 경로를 추적하고, 요청 단위 지연·오류 발생 지점을 파악하기 위한 trace 데이터를 저장·조회할 backend가 필요한 문제.
- 기술적 목표: trace를 수집·저장하고 trace ID 기반 조회, span에서 metric 생성, 로그·metric과 trace 데이터를 연결하는 기능을 제공하는 것.
- 다루는 범위: distributed tracing backend로서의 개요, 지원 프로토콜(Jaeger/Zipkin/OpenTelemetry), object storage 기반 저장 모델, Grafana와의 데이터소스 연동, Mimir/Prometheus/Loki와의 연계(exemplar를 통한 metric↔trace 이동 등).

## 3. 핵심 개념 상세
### Distributed Tracing Backend
- 원문 표현: "Grafana Tempo is an open-source, easy-to-use, and high-scale distributed tracing backend."
- 정의: 여러 서비스·컴포넌트를 거치는 요청의 실행 경로(trace)를 저장하고 조회할 수 있게 하는 오픈소스 백엔드 시스템.
- 역할: OpenTelemetry 등으로 수집된 trace 데이터가 최종적으로 저장·조회되는 backend로 쓰이며, 업무 식별자와는 별개로 관리되는 기술 실행 경로(trace) 정보를 담는 저장소 역할을 한다.

### 요청 생명주기 시각화
- 원문 표현: "visualizes the lifecycle of a request as it passes through a set of applications"
- 정의: 하나의 요청이 여러 애플리케이션·컴포넌트를 거치는 전체 흐름을 시각적으로 보여주는 기능.
- 역할: 하나의 요청이나 명령이 여러 메시징·처리 구간을 거칠 때, 어느 구간에서 지연이나 실패가 발생했는지 기술적으로 추적하는 데 대응한다.

### 지원 tracing 프로토콜(OpenTelemetry 포함)
- 원문 표현: "open source tracing protocols, including Jaeger, Zipkin, or OpenTelemetry"
- 정의: Tempo가 수집(ingest) 가능한 trace 데이터의 프로토콜/포맷 목록으로, OpenTelemetry가 그중 하나로 명시되어 있다.
- 역할: OTLP(OpenTelemetry) 기반으로 계측된 trace가 별도 변환 없이 Tempo로 직접 수집될 수 있는 경로임을 뒷받침한다.

### Object Storage 기반 저장 모델
- 원문 표현: "cost-efficient and only requires an object storage to operate"
- 정의: 별도의 고비용 인덱스 시스템 없이 object storage만으로 동작 가능한 저장 구조.
- 역할: 대량의 trace 데이터를 장기간 저장할 때 비용 부담을 줄이는 근거가 되지만, trace를 장기 감사·재현 기록의 유일한 원천으로 삼을지 아니면 단기 기술 추적용으로 한정하고 장기 재현은 별도 업무 저장소·아카이브에 맡길지는 운영 정책으로 별도 결정해야 한다.

### Grafana 데이터소스 연동
- 원문 표현: "Grafana ships with native support using the built-in Tempo data source."
- 정의: Grafana가 별도 플러그인 설치 없이 기본적으로 Tempo를 데이터소스로 지원하는 통합 방식.
- 역할: 관측 데이터(trace)를 조회·시각화하는 운영 UI 계층에서 Tempo가 Grafana와 즉시 연동 가능함을 의미하며, metric·alert·trace 등 여러 관측 신호를 Grafana라는 공통 조회 계층으로 수렴시키는 구성에서 유리하다.

## 4. 구조 및 흐름
1. 각 서비스·실행 컴포넌트가 OpenTelemetry SDK로 span을 생성해 trace를 계측한다.
2. 생성된 trace 데이터가 Jaeger/Zipkin/OpenTelemetry 등 지원 프로토콜 중 하나로 Tempo에 전송(ingest)된다.
3. Tempo는 수신한 trace를 object storage에 저장한다.
4. 사용자는 trace ID 등을 이용해 특정 요청의 전체 실행 경로를 조회하거나, span으로부터 생성된 metric을 조회한다.
5. Grafana의 내장 Tempo data source를 통해 trace를 시각화하고, Mimir/Prometheus/Loki 등 다른 signal(metric, log)과 연계해 조사한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Tempo는 대규모로 확장 가능한 오픈소스 tracing backend다 | "Grafana Tempo is an open-source, easy-to-use, and high-scale distributed tracing backend." |
| Tempo는 OpenTelemetry를 포함한 여러 표준 프로토콜을 지원한다 | "open source tracing protocols, including Jaeger, Zipkin, or OpenTelemetry" |
| Tempo는 object storage만으로 비용 효율적으로 운영 가능하다 | "cost-efficient and only requires an object storage to operate" |
| Tempo는 Grafana와 네이티브로 통합된다 | "Grafana ships with native support using the built-in Tempo data source." |

## 6. 한계 및 부족한 점
- 이번 WebFetch 범위에서는 구체적인 처리량(ingest 처리량, 최대 trace 크기), 데이터 보존 기간 설정, 쿼리 성능 한계와 같은 정량적 스펙은 확인되지 않았다. "원문 확인 안 됨."
- trace ID 기반 조회의 정확한 API·쿼리 방식(예: TraceQL)에 대한 세부 사항은 이번 페치 범위에 포함되지 않았으므로 별도 확인이 필요하다.

## 7. 원문 기반 핵심 문장
> "Grafana Tempo is an open-source, easy-to-use, and high-scale distributed tracing backend."
