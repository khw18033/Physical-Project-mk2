# AI Integration Contracts

이 디렉터리는 AI 내부 Python 객체가 아니라 파트 경계를 통과하는 JSON 메시지의 기준이다.
하드웨어·백엔드·가시화 구현은 언어별 타입을 독립적으로 유지하되 이 Schema와 예제로
호환성을 검증한다.

## 메시지 봉투

모든 AI 메시지는 `message.schema.json`을 따른다. 백엔드 통합데이터규약 v2(2026-10-15)
이후 봉투는 **평평하다** — 머리와 본문이 같은 층에 있고 `payload` 로 한 겹 더 감싸지
않는다. 공통 머리는 `schema_version`(현재 `"2.0"`), `source_id`, `node_id`, `zone_id`,
`channel`, `timestamp`, `sequence_id`, `session_id` 이고 `entity_id`·`correlation_id`·
`coordinate_frame` 은 해당이 있을 때만 싣는다. MQTT/Kafka topic 문자열은 봉투에
포함하지 않으며 배포 adapter가 결정한다.

시각은 ISO-8601 밀리초 3자리 `+09:00` 고정이다(규약 R5/D1).

## 채널

| channel | payload schema | 주 소비자 |
|---|---|---|
| `detections` | `detection-result.schema.json` | 백엔드, 가시화 |
| `risk_state` | `risk-judgment.schema.json` | 백엔드, 가시화 |
| `ai_failure` | `ai-failure.schema.json` | 백엔드, 가시화 |
| `capability_status` | `capability-status.schema.json` | 백엔드, 가시화 |
| `model_deployment_result` | `model-deployment-result.schema.json` | 하드웨어, 백엔드, 가시화 |
| `status_snapshot` | `status-snapshot.schema.json` | 가시화(운영 화면), 백엔드 |

`frame_ref` 는 규약 D13 의 세 칸 `{camera_id, sequence_id, timestamp}` 다. 프레임을
처음 손에 넣은 기기가 붙인 값을 그대로 옮기며 결과를 내는 쪽이 새로 만들지 않는다.
탐지 `bbox` 는 `[x1, y1, x2, y2]` 픽셀이고 기준 해상도는 결과의 `width`·`height` 다.

`status_snapshot` 은 구역마다 쪼개지 않은 **한 장**이다. 구역별로 채널을 나누면 같은
사실이 두 채널로 와서 도착 순서에 따라 화면 구역끼리 어긋난다. 그리고 세면 나오는 값
(상태별 노드 수·가속기별 부하·경과 시간·조건 집계)은 싣지 않는다 — 함께 실으면 한쪽만
갱신된 스냅샷이 나가는 날 반드시 어긋난다.

## 호환성 정책

- 기존 필드의 의미나 타입 변경은 `schema_version`을 올린다.
- **모르는 값에 `null` 을 싣지 않고 칸을 뺀다**(규약 R8). 2026-10-15 규약이 이전
  규칙(명시적 `null`)을 뒤집었다 — `null` 과 `0` 과 "칸 없음"이 서로 다른 뜻을
  가지는 자리(측정 없음 · 미수신 · 미배치)가 실제로 있었기 때문이다.
- 받는 쪽은 **모르는 칸을 통과시킨다**(규약 R12). 그래서 봉투와 본문은 모르는 최상위
  칸을 거부하지 않는다. `frame_ref` 안쪽만 참조 규격이라 닫혀 있다.
- 새로운 채널은 payload schema, 예제, Python 계약 테스트를 함께 추가한다.
- 가시화용 필드명 변환과 좌표 변환은 각 파트에 흩어 두지 않고 adapter 한 곳에서 한다.
- 실제 브로커 topic, 저장소, 모델 런타임, 오버레이 제품은 이 계약에 포함하지 않는다.
