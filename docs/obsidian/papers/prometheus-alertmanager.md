# Prometheus Alertmanager

## 메타데이터
- categories: Grouping, Deduplication, Routing, Inhibition, Silences
- domain: [[관측·보안]]
- source: Prometheus Authors. "Alertmanager." Prometheus Alerting Documentation, 2026(access).
- url: https://prometheus.io/docs/alerting/latest/alertmanager/
- year: 확인 필요(latest 문서, 페이지 자체에 개정 연도 명시 없음)
- authors: Prometheus Authors
- venue: Prometheus 공식 문서 (prometheus.io/docs/alerting)

## 1. 핵심 요약
- Alertmanager는 Prometheus 서버 같은 client application이 보낸 alert를 처리해 deduplicating(중복 제거), grouping(묶기), routing(올바른 receiver로 전달)을 담당하는 컴포넌트다.
- grouping은 대규모 장애 시 발생하는 다수의 유사 alert를 하나의 알림으로 묶어 noise를 줄이는 기능이며, 설정 파일의 routing tree로 제어한다.
- inhibition은 특정 alert가 이미 발생 중일 때 그와 관련된 다른 alert의 알림을 억제하는 기능이고, silence는 특정 기간 동안 alert를 단순히 mute하는 기능이다.
- Alertmanager는 고가용성을 위한 클러스터 구성을 지원하며, 이때 Prometheus는 여러 Alertmanager 앞에 로드밸런서를 두지 않고 전체 Alertmanager 목록을 직접 가리켜야 한다.

## 2. 문서 목적
- 해결하려는 문제: Prometheus 등 여러 client가 개별적으로 발생시키는 alert를 그대로 통지하면 중복·과다 알림(alert storm)이 발생해 실제 중요한 신호가 묻히는 문제.
- 기술적 목표: alert를 수신해 중복을 제거하고, 유사한 alert를 그룹으로 묶고, 알림 억제·음소거 규칙을 적용한 뒤 적절한 receiver(email, PagerDuty, OpsGenie 등)로 라우팅하는 것.
- 다루는 범위: Alertmanager의 개요, grouping/inhibition/silence 개념, 설정 파일(routing tree, inhibition rule) 구조, 웹 UI를 통한 silence 관리, 고가용성 클러스터 구성 시 Prometheus와의 연동 방식.

## 3. 핵심 개념 상세
### Alertmanager 개요 (Deduplicating / Grouping / Routing)
- 원문 표현: "The Alertmanager handles alerts sent by client applications such as the Prometheus server. It takes care of deduplicating, grouping, and routing them to the correct receiver integration such as email, PagerDuty, or OpsGenie."
- 정의: alert 수신 후 중복 제거·그룹화·라우팅을 순차적으로 수행해 최종 receiver로 전달하는 alert 처리 파이프라인.
- 역할: 여러 구성요소가 개별적으로 발생시키는 alert를 애플리케이션 코드가 아니라 별도 계층에서 한 지점으로 모아 처리하게 함으로써, 알림 로직(중복 제거·그룹화·라우팅)을 모니터링 대상 시스템으로부터 분리하는 역할을 한다.

### Grouping
- 원문 표현: "Grouping categorizes alerts of similar nature into a single notification."
- 정의: 유사한 특성(예: 동일 label 조합)을 가진 다수의 alert를 하나의 notification으로 묶는 기능. 언제 초기 notification을 보낼지, 그룹 내 후속 alert를 얼마 만에 보낼지는 설정 파일의 routing tree로 관리한다.
- 역할: 대규모 장애처럼 다수 컴포넌트가 동시에 alert를 발생시키는 상황에서 알림 폭주를 막는 데 특히 유용하다고 명시되어 있다. 다수의 노드·서비스가 한꺼번에 문제를 일으키는 환경에서 알림 수신자가 개별 alert에 압도되지 않도록 하는 근거가 된다.

### Inhibition
- 원문 표현: "Inhibition is a concept of suppressing notifications for certain alerts if certain other alerts are already firing."
- 정의: 특정 상위 alert가 이미 발생 중일 때, 그로부터 파생되거나 관련성이 높은 하위 alert의 notification을 억제하는 규칙. Alertmanager 설정 파일을 통해 구성한다("Inhibitions are configured through the Alertmanager's configuration file.").
- 역할: 예를 들어 클러스터 전체가 도달 불가능해졌을 때 관련된 개별 alert들을 억제해 알림 노이즈를 줄이는 데 사용된다고 예시로 설명한다.

### Silences
- 원문 표현: "Silences are a straightforward way to simply mute alerts for a given time."
- 정의: 지정된 기간 동안 matcher 조건에 맞는 alert의 알림을 단순히 음소거하는 기능. routing과 유사한 matcher 방식을 사용하며, 웹 UI를 통해 설정한다("Silences are configured in the web interface of the Alertmanager.").
- 역할: 계획된 유지보수나 알려진 이슈 기간 동안 불필요한 알림을 임시로 끄는 운영 절차에 해당한다.

### 고가용성 클러스터
- 원문 표현: "Alertmanager supports configuration to create a cluster for high availability." / "It's important not to load balance traffic between Prometheus and its Alertmanagers, but instead, point Prometheus to a list of all Alertmanagers."
- 정의: 여러 Alertmanager 인스턴스가 클러스터를 구성해 고가용성을 제공하며, Prometheus는 로드밸런서를 거치지 않고 전체 Alertmanager 목록에 직접 alert를 전송해야 하는 구성 방식.
- 역할: 관측 인프라 자체의 단일 장애점을 피하려면 Alertmanager도 클러스터로 구성해야 하며, 이를 참조하는 Prometheus 설정은 로드밸런서 뒤에 숨긴 단일 주소가 아니라 전체 인스턴스 목록을 직접 알아야 한다는 제약을 시사한다.

## 4. 구조 및 흐름
1. Prometheus 서버 등 client application이 조건을 만족하는 alert를 Alertmanager로 전송한다.
2. Alertmanager가 수신한 alert 중 중복(deduplicate)을 제거한다.
3. 설정 파일의 routing tree를 기준으로 유사한 alert를 grouping해 하나의 notification 단위로 묶는다.
4. inhibition 규칙을 평가해, 이미 발생 중인 상위 alert와 관련된 하위 alert의 notification을 억제할지 판단한다.
5. 웹 UI 등에서 등록된 silence 규칙에 해당하는 alert는 mute 처리한다.
6. 남은 alert 그룹을 routing tree가 지정한 receiver(email, PagerDuty, OpsGenie 등)로 전달한다.
7. 고가용성이 필요하면 Alertmanager를 클러스터로 구성하고, Prometheus는 로드밸런서 없이 전체 Alertmanager 목록으로 직접 전송한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Alertmanager는 dedup·grouping·routing을 통합 처리하는 컴포넌트다 | "It takes care of deduplicating, grouping, and routing them to the correct receiver integration such as email, PagerDuty, or OpsGenie." |
| grouping은 대규모 장애 시 알림 폭주를 줄이는 데 특히 유용하다 | grouping 설명에서 다수 시스템이 동시에 실패하는 상황을 명시적 예시로 듦 |
| Alertmanager 고가용성 구성 시 Prometheus는 로드밸런서가 아니라 전체 인스턴스 목록을 사용해야 한다 | "It's important not to load balance traffic between Prometheus and its Alertmanagers, but instead, point Prometheus to a list of all Alertmanagers." |

## 6. 한계 및 부족한 점
- 이번 WebFetch 결과에서는 deduplication과 routing 각각에 대한 별도의 상세 정의 문단은 확인되지 않았고, 개요 문장에서만 언급된다. 즉 "dedup 알고리즘의 구체적 기준(어떤 label 조합을 동일 alert로 간주하는지)"은 이 페치 범위에서 확인하지 못했다 — "원문 확인 안 됨."
- 클러스터 구성 시 필요한 최소 노드 수, gossip 프로토콜 세부, 네트워크 요건 등 고가용성 관련 세부 스펙은 이번 페치 범위에서 확인되지 않았다.

## 7. 원문 기반 핵심 문장
> "The Alertmanager handles alerts sent by client applications such as the Prometheus server. It takes care of deduplicating, grouping, and routing them to the correct receiver integration such as email, PagerDuty, or OpsGenie."
