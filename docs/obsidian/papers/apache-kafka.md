# Apache Kafka

## 메타데이터
- categories: Distributed Event Streaming, Partition과 Offset, Consumer Group, SASL SSL 보안
- domain: [[전송·프로토콜]]
- source: Apache Software Foundation. "Apache Kafka Documentation." kafka.apache.org, 확인 필요.
- url: https://kafka.apache.org/documentation/
- year: 확인 필요
- authors: Apache Kafka project (Apache Software Foundation)
- venue: Apache Software Foundation (공식 문서 사이트)

## 1. 핵심 요약
- Apache Kafka는 이벤트를 발행/구독, 내구성 있게 저장, 실시간 또는 사후에 처리할 수 있는 3가지 핵심 기능을 하나로 결합한 event streaming platform이다.
- 이벤트는 topic 단위로 저장되며, topic은 여러 broker에 분산된 partition으로 나뉜다.
- Producer는 이벤트를 발행하고 Consumer는 이를 구독해 읽고 처리하며, topic은 지역/데이터센터를 넘어 여러 broker에 복제(replication)될 수 있다.
- 인증은 클라이언트-브로커, 브로커 간 연결 모두에 SSL 또는 SASL(GSSAPI/PLAIN/SCRAM-SHA-256/512/OAUTHBEARER)을 지원하며, 인가(authorization)는 pluggable 구조로 외부 인가 서비스와 통합 가능하다.

## 2. 문서 목적
- 해결하려는 문제: 대규모 이벤트(로그, 메시지, 명령 등)를 여러 producer/consumer가 동시에 안정적으로 주고받고, 일정 기간 재생(replay) 가능한 형태로 다루면서도 수평 확장이 가능해야 하는 문제.
- 기술적 목표: topic-partition 기반 분산 저장 구조와 replication을 통해 내구성과 확장성을 확보하고, consumer group을 통해 여러 consumer가 부하를 나눠 처리할 수 있게 하며, SASL/SSL 기반 인증과 pluggable 인가로 접근을 통제하는 것.
- 다루는 범위: producer/consumer API, topic/partition/offset/replication 등 저장 모델, broker 클러스터 구성, 보안(인증·암호화·인가) 개요.

## 3. 핵심 개념 상세

### Distributed Event Streaming Platform
- 원문 표현: "Kafka combines three key capabilities so you can implement your use cases for event streaming end-to-end with a single battle-tested solution: To publish (write) and subscribe to (read) streams of events, including continuous import/export of your data from other systems. To store streams of events durably and reliably for as long as you want. To process streams of events as they occur or retrospectively."
- 정의: 이벤트의 발행/구독, 내구성 있는 저장, 실시간·사후 처리를 하나의 시스템으로 제공하는 분산 이벤트 스트리밍 플랫폼.
- 역할: 여러 구간·서비스 사이의 업무 데이터와 명령·이벤트 전달을 담당하는 백본으로 널리 쓰이는 기술이며, 다만 일반적으로 장기 저장소로 사용하기보다는 단기 버퍼·다중 소비자 분배·단기 replay 용도로 한정해서 쓰는 운영 관행이 권장된다.

### Topic / Partition
- 원문 표현: "Events are organized and durably stored in topics. Very simplified, a topic is similar to a folder in a filesystem, and the events are the files in that folder." / "Topics are partitioned, meaning a topic is spread over a number of 'buckets' located on different Kafka brokers."
- 정의: topic은 이벤트가 저장되는 논리적 스트림 단위이며, 하나의 topic은 여러 broker에 분산된 partition들로 나뉘어 저장된다.
- 역할: 발신 출처나 기능별로 업무 데이터를 topic-partition으로 분리해 다중 소비자(예: 여러 다운스트림 서비스)가 동시에 소비할 수 있게 하는 구조적 근거다.

### Producer / Consumer
- 원문 표현: "Producers are those client applications that publish (write) events to Kafka." / "Consumers are those that subscribe to (read and process) these events."
- 정의: 이벤트를 Kafka topic에 쓰는 클라이언트(producer)와, topic을 구독해 이벤트를 읽고 처리하는 클라이언트(consumer).
- 역할: 서로 다른 프로토콜을 쓰는 두 시스템을 연결하는 브릿지 컴포넌트가 producer로서 업스트림 데이터를 Kafka에 쓰고, 다운스트림 서비스가 consumer로서 이를 읽는 구조는 이기종 메시징 계층을 통합하는 전형적인 패턴이다.

### Replication
- 원문 표현: "Every topic can be replicated, even across geo-regions or datacenters, so that there are always multiple brokers that have a copy of the data."
- 정의: 동일 partition의 데이터 복사본을 여러 broker에 유지해 특정 broker 장애 시에도 데이터 가용성을 유지하는 메커니즘.
- 역할: 클러스터가 단일 broker 장애에도 업무 데이터·명령 전달을 지속할 수 있게 하는 근거이지만, replication은 가용성을 위한 메커니즘일 뿐이므로 이를 "영구 보존"과 동일시해 Kafka를 장기 저장소로 취급해서는 안 된다.

### SASL/SSL 보안과 인가
- 원문 표현: "Authentication of connections to brokers from clients (producers and consumers), other brokers and tools, using either SSL or SASL." / "Authorization of read / write operations by clients" / "Authorization is pluggable and integration with external authorization services is supported."
- 정의: broker-client, broker-broker 연결에 대한 인증을 SSL 또는 SASL(GSSAPI/PLAIN/SCRAM-SHA-256/512/OAUTHBEARER)로 수행하고, 읽기/쓰기 권한에 대한 인가는 pluggable하게 외부 서비스와 통합할 수 있는 구조.
- 역할: 분산 시스템의 여러 구간(클라이언트-broker, broker-broker)에서 누가 어떤 topic을 publish/consume할 수 있는지를 통제해야 하는 메시징 계층 접근 통제 요구를, 표준 인증·인가 메커니즘으로 구현하는 근거가 된다.

## 4. 구조 및 흐름
1. Producer(예: 서로 다른 메시징 프로토콜을 연결하는 브릿지 서비스)가 특정 topic에 이벤트를 발행(write)한다.
2. Kafka broker 클러스터가 topic을 여러 partition으로 나눠 분산 저장하고, 설정된 replication factor만큼 다른 broker에 복제한다.
3. Consumer(또는 consumer group)가 topic을 구독해 partition별로 이벤트를 순서대로 읽고 처리한다.
4. broker 연결 시 SSL/SASL로 인증하고, 이후 read/write 요청은 pluggable authorization 계층에서 허용 여부를 판정한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Kafka는 발행/구독, 저장, 처리를 하나로 통합한 플랫폼이다 | "Kafka combines three key capabilities ... To publish ... To store ... To process ..." |
| topic은 여러 broker에 분산된 partition으로 확장된다 | "Topics are partitioned, meaning a topic is spread over a number of 'buckets' located on different Kafka brokers." |
| topic은 지역·데이터센터를 넘어 복제될 수 있다 | "Every topic can be replicated, even across geo-regions or datacenters, so that there are always multiple brokers that have a copy of the data." |
| 인증은 SSL 또는 SASL 여러 메커니즘을 지원한다 | SASL/GSSAPI(0.9.0.0+), SASL/PLAIN(0.10.0.0+), SASL/SCRAM-SHA-256·512(0.10.2.0+), SASL/OAUTHBEARER(2.0+) 명시 |
| 인가는 pluggable하며 외부 서비스와 통합 가능하다 | "Authorization is pluggable and integration with external authorization services is supported." |

## 6. 한계 및 부족한 점
- 이번 조사에서는 kafka.apache.org의 introduction 페이지와 4.3 버전 security overview 페이지만 확인했으며, consumer group의 정확한 rebalance 동작이나 offset commit 세부 규칙, exactly-once semantics(EOS) 관련 문서는 확인하지 못했다(확인 안 됨).
- documentation 메인 인덱스 페이지는 네비게이션 메뉴 위주로 렌더링되어 partition 내부의 offset 개념에 대한 공식 정의 문장은 이번 조사에서 직접 인용하지 못했다.
- 이 문서가 참조한 버전 번호(security overview 페이지 경로상 4.3)는 조사 시점의 공식 문서 버전을 가리킬 뿐이며, 실제 운영에 사용하는 Kafka 버전은 배포 환경에 따라 별도로 고정(pin)·관리해야 한다.

## 7. 원문 기반 핵심 문장
> "Kafka combines three key capabilities so you can implement your use cases for event streaming end-to-end with a single battle-tested solution: To publish (write) and subscribe to (read) streams of events, including continuous import/export of your data from other systems. To store streams of events durably and reliably for as long as you want. To process streams of events as they occur or retrospectively."
