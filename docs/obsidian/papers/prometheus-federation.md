# Prometheus Federation

## 메타데이터
- categories: Federation, /federate 엔드포인트, Hierarchical Federation, honor_labels
- domain: [[관측·보안]]
- source: Prometheus Authors. "Federation." Prometheus Documentation, 2026(access).
- url: https://prometheus.io/docs/prometheus/latest/federation/
- year: 확인 필요(latest 문서, 페이지 자체에 개정 연도 명시 없음)
- authors: Prometheus Authors
- venue: Prometheus 공식 문서 (prometheus.io/docs)

## 1. 핵심 요약
- Federation은 한 Prometheus 서버가 다른 Prometheus 서버로부터 "선택된" time series만 scrape하는 기능이다.
- `/federate` HTTP 엔드포인트가 이 기능의 실제 구현체이며, `match[]` 쿼리 파라미터로 가져올 time series를 지정한다.
- Hierarchical federation은 다수의 하위(subordinate) Prometheus에서 집계된 데이터를 상위 Prometheus가 다시 모으는 tree 형태의 토폴로지로, 데이터센터 수십 개·노드 수백만 규모까지 확장 가능하다고 설명한다.
- federation은 원본 label을 보존하기 위해 scrape 설정에서 `honor_labels` 옵션을 함께 켜는 것이 일반적인 구성 방식이다.

## 2. 문서 목적
- 해결하려는 문제: 지역(구역)마다 분산된 Prometheus 인스턴스가 수집한 대량의 상세 metric을 중앙에서 전부 다시 수집하면 네트워크·저장 비용이 과도해지는 문제.
- 기술적 목표: 상위 Prometheus가 하위 Prometheus의 전체 metric이 아니라 운영에 필요한 "선택된" 부분집합만 주기적으로 가져오도록 하는 표준 메커니즘(`/federate`)을 제공하는 것.
- 다루는 범위: `/federate` 엔드포인트의 동작과 파라미터, scrape 설정 예시, hierarchical(계층적) federation 토폴로지, native histogram을 federate할 때의 payload 형식 이슈.

## 3. 핵심 개념 상세
### Federation
- 원문 표현: "Federation allows a Prometheus server to scrape selected time series from another Prometheus server."
- 정의: 한 Prometheus 서버가 다른 Prometheus 서버가 보유한 time series 중 지정된 일부만 자신의 scrape 대상으로 가져오는 기능.
- 역할: 여러 하위 모니터링 서버가 각자 상세 지표를 로컬에 유지하면서도, 상위 모니터링 서버가 전체 원본을 다시 수집하지 않고 운영에 필요한 요약·선택된 지표만 주기적으로 가져오는 계층형 모니터링 구조의 핵심 메커니즘이 된다.

### /federate 엔드포인트
- 원문 표현: "The `/federate` endpoint allows retrieving the current value for a selected set of time series in that server."
- 정의: 특정 시점의 time series 현재값을 반환하는 HTTP 엔드포인트. 최소 하나 이상의 `match[]` 파라미터가 필요하며 각 파라미터는 `up`이나 `{job="api-server"}` 같은 instant vector selector 형태를 가져야 한다.
- 역할: 상위 Prometheus의 scrape config가 이 엔드포인트를 대상으로 지정해, 어떤 metric을 가져올지 선언적으로 제한한다. "하위에는 상세, 상위에는 선택된 요약"이라는 계층형 관측 경계를 실제로 구현하는 지점이다.

### honor_labels
- 원문 표현: "configure your destination Prometheus server to scrape from the `/federate` endpoint of a source server, while also enabling the `honor_labels` scrape option (to not overwrite any labels exposed by the source server)"
- 정의: scrape 대상이 이미 붙여놓은 label을 상위 서버가 자신의 label로 덮어쓰지 않도록 하는 scrape 옵션.
- 역할: 구역별로 태깅된 label(예: 구역 ID, 노드 ID)이 서버로 federate되는 과정에서 손실되지 않도록 보장하는 설정으로, 다구역 운영에서 출처 구분에 중요하다.

### Hierarchical Federation
- 원문 표현: "Hierarchical federation allows Prometheus to scale to environments with tens of data centers and millions of nodes."
- 정의: 상위 레벨 Prometheus 서버가 다수의 하위(subordinated) Prometheus 서버로부터 이미 집계된 time series 데이터를 다시 모으는 tree 형태의 구조.
- 역할: 다수의 지역·클러스터 단위 모니터링 서버를 두고 그 위에 소수의 상위 집계 서버를 두는 조직에서, 하위 인스턴스 수가 늘어나도 상위가 전체 원본을 재수집하지 않고 계층적으로 확장할 수 있음을 뒷받침한다.

### Native Histogram Federation 제약
- 원문 표현: "the federation payload will contain multiple metric families with the same name" (mixed sample type의 native histogram을 federate할 때), 이는 "violates the rules of the protobuf exposition format, but Prometheus is nevertheless able to ingest all metrics correctly."
- 정의: classic histogram과 native histogram이 혼재된 상태로 federate되면 federation payload가 protobuf exposition format의 규칙을 형식적으로는 위반하지만 실제 수집(ingest)에는 문제가 없다는 알려진 예외 케이스.
- 역할: native histogram 기반 metric을 federation과 함께 도입하려는 운영자가 payload의 형식적 이상(anomaly) 가능성을 미리 인지해야 하는 지점이다.

## 4. 구조 및 흐름
1. 하위 Prometheus가 로컬 target들을 상시 scrape해 상세 time series를 보유한다.
2. 상위(서버) Prometheus의 scrape config에 하위 Prometheus의 `/federate` 엔드포인트를 target으로 등록하고, 하나 이상의 `match[]` selector로 가져올 time series 범위를 지정한다.
3. 상위 Prometheus가 주기적으로 `/federate`를 scrape하면서 `honor_labels: true`를 설정해 원본 label을 유지한다.
4. 여러 하위 Prometheus를 두는 경우, 상위 Prometheus 자체도 또 다른 상위 계층의 federation 대상이 될 수 있어 tree 형태의 hierarchical federation을 구성할 수 있다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| federation은 선택된 일부 time series만 가져오는 기능이지 전체 replication이 아니다 | "Federation allows a Prometheus server to scrape selected time series from another Prometheus server." |
| federation은 대규모 다중 데이터센터 환경으로 확장 가능하다 | "Hierarchical federation allows Prometheus to scale to environments with tens of data centers and millions of nodes." |
| federate 시 원본 label 보존을 위해 honor_labels가 필요하다 | 공식 설정 예시에서 `/federate` 대상 scrape config에 `honor_labels` 활성화를 명시적으로 권고 |

## 6. 한계 및 부족한 점
- WebFetch로 확인한 범위 내에서는 federation의 일반적인 한계(예: pull 주기에 따른 지연, 실시간성 부족, 대규모 label cardinality에서의 부하)에 대한 별도의 명시적 경고 문구는 확인하지 못했다. "원문 확인 안 됨."
- native histogram과 classic histogram이 혼재된 경우의 protobuf 형식 위반은 문서가 스스로 인정하는 유일하게 명확한 제약이며, 그 외 federation의 일반적 스케일 한계(초당 처리량, 권장 상한 등 구체 수치)는 이번 페치 범위에서 확인되지 않았다.

## 7. 원문 기반 핵심 문장
> "Federation allows a Prometheus server to scrape selected time series from another Prometheus server."
