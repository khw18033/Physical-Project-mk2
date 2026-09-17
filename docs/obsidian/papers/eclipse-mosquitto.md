# Eclipse Mosquitto

## 메타데이터
- categories: MQTT Broker, Authentication Methods, Dynamic Security Plugin, Topic ACL
- domain: [[전송·프로토콜]]
- source: Eclipse Foundation. "Eclipse Mosquitto Documentation." mosquitto.org, 확인 필요.
- url: https://mosquitto.org/documentation/
- year: 확인 필요
- authors: Eclipse Mosquitto project
- venue: Eclipse Foundation (공식 문서 사이트)

## 1. 핵심 요약
- Eclipse Mosquitto는 공식 문서 헤더에서 스스로를 "An Open Source MQTT Server"로 소개하는 오픈소스 MQTT broker다.
- 인증 방식으로 password file, 인증 plugin(legacy `auth_plugin`, 2.0 이상 `plugin`), 익명 접속 허용(`allow_anonymous`) 등을 제공한다.
- Dynamic Security plugin은 broker를 재시작하지 않고도 topic 기반 API로 갱신 가능한 role 기반 인증·접근 제어 기능을 제공한다.
- Dynamic Security의 핵심 개념은 clients(인증 대상), groups(클라이언트 묶음), roles(ACL 집합)이며, role은 client 또는 group에 할당된다.

## 2. 문서 목적
- 해결하려는 문제: 엣지에 배치되는 MQTT broker가 단순 발행/구독 중계를 넘어, 누가 어떤 topic에 publish/subscribe할 수 있는지를 안전하게 통제해야 하는 문제.
- 기술적 목표: password file부터 커스텀 인증 plugin, 그리고 런타임에 갱신 가능한 Dynamic Security plugin까지 여러 수준의 인증·인가 메커니즘을 제공하는 것.
- 다루는 범위: broker 설정(man page), listener 설정, persistence(SQLite), plugin(ACL file, password file, Dynamic Security, Sparkplug Aware), 인증 방식, libmosquitto 클라이언트 API.

## 3. 핵심 개념 상세

### MQTT Broker
- 원문 표현: "An Open Source MQTT Server"
- 정의: MQTT 프로토콜에 따라 publisher와 subscriber 사이의 메시지 발행/구독을 중계하는 서버 소프트웨어.
- 역할: 엣지·게이트웨이 계층에 배치되는 대표적인 오픈소스 MQTT broker 구현이며, 자원이 제한된 다수의 말단 장치가 하나의 broker에 연결해 발행/구독 메시지를 중계받는 IoT 아키텍처에서 널리 쓰인다.

### Authentication Methods
- 원문 표현: "Password files are a simple mechanism of storing usernames and passwords in a single file." / "If you want more control over authentication of your users than is offered by a password file, then an authentication plugin may be suitable for you." / "To configure unauthenticated access, use the `allow_anonymous` option"
- 정의: 단순 사용자명/비밀번호 파일 기반 인증부터, 커스텀 로직을 붙일 수 있는 인증 plugin(legacy `auth_plugin` 또는 2.0+ `plugin`), 그리고 인증을 요구하지 않는 익명 접속까지 선택 가능한 인증 방식 스펙트럼.
- 역할: 네트워크 계층이 이미 신뢰할 수 있는 사설망(VPN, 오버레이 네트워크 등)으로 보호되고 있더라도, 모든 클라이언트가 모든 topic에 publish하도록 허용해서는 안 된다는 것이 일반적인 보안 원칙이며, broker의 인증 방식이 이러한 메시징 계층 보안 경계를 실제로 구현하는 지점이 된다.

### Dynamic Security Plugin
- 원문 표현: "The Dynamic Security plugin is a Mosquitto plugin which provides role based authentication and access control features that can be updated whilst the broker is running, using a special topic based API."
- 정의: broker 재시작 없이 topic 기반 API로 client/group/role 구성을 실시간 갱신할 수 있는 role 기반 인증·접근 제어 plugin.
- 역할: 여러 클라이언트(장치, 서비스 등)가 각자 자신에게 할당된 topic에만 publish/subscribe하고 다른 클라이언트의 topic에는 접근을 거부(DENY)하는 멀티테넌트형 접근 제어를 구현할 수 있는 대표적 메커니즘이다.

### Clients / Groups / Roles (ACL 관계)
- 원문 표현: "Multiple clients can be placed in a group. Groups can have roles assigned to them, so using groups is appropriate where you have a number of clients that need to have the same access." / "Roles contain multiple access control lists (ACLs), and can be assigned to clients and/or groups."
- 정의: Client(인증 주체)를 Group으로 묶고, 권한의 실체인 ACL 목록을 담은 Role을 Client 또는 Group에 할당해 topic별 publish/subscribe/unsubscribe 권한을 제어하는 3계층 모델.
- 역할: 여러 클라이언트(장치, 서비스 프로세스 등)가 동일한 broker를 공유할 때, 개별 client 단위가 아니라 group·role 단위로 topic 접근 정책을 관리할 수 있게 해 대규모 배포 환경의 접근 통제 운영 부담을 줄인다.

## 4. 구조 및 흐름
1. broker(Mosquitto)를 설정 파일과 listener 설정으로 기동한다.
2. 인증 방식을 선택한다 — password file, 인증 plugin, 또는 (권장되지 않는) 익명 접속.
3. Dynamic Security plugin을 사용하는 경우, 특수 topic API를 통해 client를 생성하고 group에 배치한다.
4. role을 정의해 ACL(topic filter + publishClientSend/publishClientReceive/subscribe/unsubscribe + allow/deny + priority)을 구성한다.
5. role을 client 또는 group에 할당하면, 이후 해당 client의 접근 요청 시 할당된 role들이 우선순위 순으로 평가되어 허용/거부가 결정된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Mosquitto는 오픈소스 MQTT 서버(broker)다 | 공식 문서 헤더가 "An Open Source MQTT Server"로 소개 |
| 인증은 password file보다 더 세밀한 제어가 필요하면 plugin으로 확장할 수 있다 | "If you want more control over authentication of your users than is offered by a password file, then an authentication plugin may be suitable for you." |
| Dynamic Security는 broker 재시작 없이 인증·접근 제어를 갱신할 수 있다 | "role based authentication and access control features that can be updated whilst the broker is running, using a special topic based API" |
| 권한은 role의 ACL을 client/group에 할당하는 방식으로 구성된다 | "Roles contain multiple access control lists (ACLs), and can be assigned to clients and/or groups." |

## 6. 한계 및 부족한 점
- 공식 authentication-methods 문서는 "As well as authentication you should also consider some form of access control to determine what clients can access which topics"라고만 언급할 뿐, 정적 ACL 파일 문법 자체의 세부 규칙은 이 페이지에서 상세히 다루지 않는다 — 별도의 ACL file plugin 문서 확인이 추가로 필요하다(확인 안 됨).
- 메인 documentation 인덱스 페이지에서는 Mosquitto가 지원하는 정확한 MQTT 프로토콜 버전(3.1/3.1.1/5.0 여부)이 명시적으로 확인되지 않았다 — man page(`mqtt(7)`)를 별도로 확인해야 한다.
- Dynamic Security의 ACL 평가 우선순위 규칙("roles assigned to a client are checked first, in priority order. Each client group is checked in priority order")은 확인했지만, role/ACL이 충돌할 때의 전체 tie-break 규칙까지는 이번 조사에서 완전히 확인하지 못했다.

## 7. 원문 기반 핵심 문장
> "The Dynamic Security plugin is a Mosquitto plugin which provides role based authentication and access control features that can be updated whilst the broker is running, using a special topic based API."
