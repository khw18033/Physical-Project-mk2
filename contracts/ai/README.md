# AI Integration Contracts

이 디렉터리는 AI 내부 Python 객체가 아니라 파트 경계를 통과하는 JSON 메시지의 기준이다.
하드웨어·백엔드·가시화 구현은 언어별 타입을 독립적으로 유지하되 이 Schema와 예제로
호환성을 검증한다.

## 메시지 봉투

모든 AI 메시지는 `message.schema.json`을 따른다. 백엔드 공통 규약의
`source_id`, `node_id`, `zone_id`, `timestamp`, `schema_version`, `correlation_id`와
가시화 구독 축의 `entity_id`, `channel`을 함께 유지한다. MQTT/Kafka topic 문자열은
봉투에 포함하지 않으며 배포 adapter가 결정한다.

## 채널

| channel | payload schema | 주 소비자 |
|---|---|---|
| `detections` | `detection-result.schema.json` | 백엔드, 가시화 |
| `risk_state` | `risk-judgment.schema.json` | 백엔드, 가시화 |
| `ai_failure` | `ai-failure.schema.json` | 백엔드, 가시화 |
| `plan_proposal` | `plan-proposal.schema.json` | 백엔드, 가시화 |
| `capability_status` | `capability-status.schema.json` | 백엔드, 가시화 |
| `model_deployment_result` | `model-deployment-result.schema.json` | 하드웨어, 백엔드, 가시화 |

`frame_ref`는 단일 숫자가 아니라 `source_id`, `capture_timestamp`, `sequence_id`를
포함한다. 탐지 `bbox`는 `{x, y, width, height}` 객체이며 `bbox_space`가 절대/정규화
좌표와 기준 해상도를 선언한다.

## 호환성 정책

- 기존 필드의 의미나 타입 변경은 `schema_version`을 올린다.
- 선택 필드는 누락 대신 명시적 `null`을 사용한다.
- 새로운 채널은 payload schema, 예제, Python 계약 테스트를 함께 추가한다.
- 가시화용 필드명 변환과 좌표 변환은 각 파트에 흩어 두지 않고 adapter 한 곳에서 한다.
- 실제 브로커 topic, 저장소, 모델 런타임, 오버레이 제품은 이 계약에 포함하지 않는다.
