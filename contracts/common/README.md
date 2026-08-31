# 공통 계약 (Common Contracts)

이 디렉터리는 파트(하드웨어·AI·가시화) 경계를 통과하는 JSON 메시지의 기준이다.
**파트 경계의 단일 기준은 각 파트의 내부 타입(Python dataclass·TypeScript type)이 아니라
여기 있는 JSON Schema다.** 각 파트는 언어별 타입을 독립적으로 유지하되, 이 스키마와 예제로
호환성을 검증한다. AI·하드웨어·가시화는 백엔드 내부 타입을 직접 import하거나 복사하지 않는다.

## 소유권

**공통 메시지 식별자·상관키·봉투는 백엔드가 정의·유지한다.** 요구사항 근거:

- **BE-C-01** — 공통 메시지 스키마·필드 규약(백엔드 정의 → 전 파트 준수)
- **BE-C-02** — 식별자 계층(Entity/Node/Zone) 규약
- **BE-C-03** — 프레임 참조·시간 동기 규약
- **BE-C-07** — 원천 종류(실물·시뮬·기록재생) 표기 규약

AI 파트도 이 소유권을 전제한다 — AI-C-01: "AI가 생산·소비하는 데이터는 백엔드가 정의한 공통
식별·시간·버전 규약과 의미 체계를 따라야 한다." 따라서 이 계약이 정본이고, 다른 파트의 봉투
표현(예: AI 쪽 `contracts/ai/message.schema.json`, 가시화 Envelope)은 이 계약에 정렬한다.

## 파일

| 파일 | 무엇 | 근거 |
|---|---|---|
| `message.schema.json` | 모든 메시지의 공통 봉투(머리) | BE-C-01·BE-C-02·BE-C-07 |
| `frame-reference.schema.json` | 원본 관측 프레임 역추적 참조(frame_ref) | BE-C-03 |
| `examples/envelope-valid.json` | 봉투를 통과하는 정상 메시지 예제 | 위 스키마 |

## 봉투와 채널의 관계

`message.schema.json`은 **봉투(envelope)만** 정의한다 — 모든 메시지에 공통인 머리
(`schema_version` · `source_id` · `entity_id` · `node_id` · `zone_id` · `timestamp` ·
`sequence_id` · `correlation_id` · `origin_kind`).

채널별 본문(계측값 `water_level_m`, 탐지 `boxes`, 위험 `risk_state` 등)은 이 봉투 위에 얹히며,
각 채널 payload 스키마에서 따로 정의한다. `examples/envelope-valid.json`이 봉투 위에 채널 본문
(`channel: "state"` + 계측 필드)이 얹힌 실제 모양을 보여준다.

- **필수 필드**: `schema_version` · `source_id` · `node_id` · `zone_id` · `timestamp`.
  이 다섯은 모든 메시지에 무조건 있어야 한다.
- **선택 필드**: `entity_id`(노드=개체가 1:1이면 생략) · `sequence_id`(연속 메시지에만) ·
  `correlation_id`(명령 사슬에만) · `origin_kind`(미기재 시 실물로 간주).

## 식별자 원칙 (BE-C-02)

장치·이동체·구역을 **IP·MAC 같은 가변값이 아니라 논리 식별자 계층**으로 참조한다.

- **Entity(개체)** — `entity_id`. 논리 대상. 로봇 한 노드가 여러 개체를 대리할 수 있다.
- **Node(물리 노드)** — `node_id`. 실행 노드. 물리 노드 레지스트리에 연결.
- **Zone(구역)** — `zone_id`. 권한·라우팅·범위(scope)의 기준.

네트워크 주소(IP·MAC)는 도달성 정보이며 개체 정체성이 아니다. 봉투에 IP·MAC·broker topic을
논리 식별자 대신 넣지 않는다. (device_id↔MAC/IP 매핑은 백엔드 레지스트리·라우팅의 내부 관심사
이며 봉투 계약에 포함하지 않는다. `source_id`가 정본이고 device_id 별칭은 계약에서 제외한다 —
생산자는 source_id 단일 필드로 정렬한다.)

## 버전 정책

- 기존 필드의 의미·타입 변경은 `schema_version`의 MAJOR 또는 MINOR를 올린다.
- 선택 필드는 누락 대신 명시적 `null`을 쓸 수 있으나, 봉투 선택 필드는 아예 생략도 허용한다
  (required가 아니므로). 채널 payload 스키마 쪽에서 `null` 강제가 필요하면 그쪽에서 정한다.
- 새로운 채널은 payload 스키마·예제·검증을 함께 추가한다.
- 실제 브로커 topic 문자열, 저장소 제품, 전송 기술은 이 계약에 포함하지 않는다 — 배포 adapter가
  결정한다(BE-C-05: 계약 축 {entity, node, channel}은 프로토콜 문자열이 아니다).

## 검증

각 파트는 수신 시 `message.schema.json`을 먼저 검증하고, `channel`에 따라 payload 스키마를
선택한다. 검증 실패 메시지는 정상 topic으로 재발행하지 말고 격리·기록한다(백엔드 수신 규약).
`examples/envelope-valid.json`이 회귀 검증의 기준 fixture다.
