# 백엔드 파트 병합·연결 안내

백엔드는 공통 메시지 식별자·상관키의 소유자이며 AI 메시지를 저장·중계하는 경계다.
대상 요구사항은 `BE-C-01~04`, `BE-A-03~05`, `BE-S-01/02`, `BE-X-01/04/05/06`,
`DT-01~03`이다.

## 가져갈 범위

백엔드 브랜치에는 `contracts/ai/` 전체를 반영한다. Python AI 구현은 백엔드가 직접 import하지
않고 Kafka/HTTP/내부 RPC 등 배포 adapter를 통해 Schema 메시지만 수신한다.

수신 시 `message.schema.json`을 먼저 검증하고 `channel`에 따라 payload Schema를 선택한다.
검증 실패 메시지는 정상 topic으로 재발행하지 말고 격리·기록한다.

## 식별자·봉투 매핑

| 공통 계약 | 백엔드 책임 |
|---|---|
| `message_id` | 중복 수신 방지·감사 진입점 |
| `source_id` | 실제 생산자 식별 |
| `node_id` | 물리 실행 노드 레지스트리 연결 |
| `entity_id` | 장치·로봇·시설 논리 개체 연결 |
| `zone_id` | 권한·구역 라우팅 기준 |
| `timestamp` | 메시지 생성 시각 보존 |
| `sequence_id` | 생산자별 유실·역전 검출 |
| `correlation_id` | 요청·결과·감사 사슬 연결 |

IP·MAC·broker topic을 위 식별자 대신 저장하지 않는다. 네트워크 주소는 도달성 정보이며
개체 정체성이 아니다.

## 채널 처리

| channel | 백엔드 처리 | 재접속 캐시 |
|---|---|---|
| `detections` | 프레임 정합을 보존해 WS 중계 | 금지 |
| `risk_state` | 제어 번역 입력·가시화 중계 | 과거 replay 금지, 현재값 주기 재발행 |
| `ai_failure` | 사건 저장·즉시 알림 | 금지 |
| `plan_proposal` | 승인 대기 상태 생성·가시화 중계 | 승인 대기 최신 상태만 |
| `capability_status` | 배포 상태와 별도 보관·중계 | 최신 상태 허용 |
| `model_deployment_result` | 적용 이력 저장·상태 중계 | 대상별 최신 결과 허용 |

캐시된 메시지의 `timestamp`를 재접속 시각으로 다시 찍지 않는다.

## 가시화 게이트웨이 호환

기존 가시화 `Envelope`를 당장 유지한다면 게이트웨이 한 곳에서만 다음처럼 변환한다.

| 공통 계약 | 기존 VZ Envelope |
|---|---|
| `entity_id` | `entity` |
| `node_id` | `node` |
| `zone_id` | `zone` |
| `timestamp` | `ts` |
| `sequence_id` | `seq` |
| `channel` | `channel` |
| `coordinate_frame` | `coordinate_frame` |

payload 내부 필드는 재명명하지 않는다. 장기적으로는 가시화도 공통 봉투 이름을 직접 쓰는 것이
중간 변환을 줄인다.

## 계획 승인 경계

AI의 `plan_proposal`은 승인 전 실행 가능한 명령이 아니다. 백엔드는 다음을 추가 관리한다.

- `decision`: pending/approved/rejected
- 승인·거부 주체와 시각
- `plan_id`와 백엔드 발급 `command_id` 매핑
- 승인 결과의 엣지·로봇 발행 상태
- 계획 생성기·입력 context 버전과 검증 결과 보존

거부된 계획과 검증 실패 subtask를 실행관리로 전달하지 않는다.

## 검증 체크리스트

- `contracts/ai/examples/*.json` 6종을 모두 수신·검증한다.
- `message_id` 중복이 명령·알림 중복 실행으로 이어지지 않는다.
- `correlation_id`가 계획·위험 판단·제어·감사까지 유지된다.
- `frame_ref`의 `source_id + sequence_id` 조합이 영상 버퍼 조회까지 보존된다.
- capability 미배포와 실제 AI 실패를 서로 다른 상태·사건으로 중계한다.
- 탐지·실패 이벤트가 재접속 snapshot으로 재생되지 않는다.

## Git 적용 시 주의

계약 파일을 먼저 반영한 후 백엔드 adapter를 별도 커밋으로 둔다. Schema 변경과 저장소·API
리팩터링을 한 커밋에 섞지 않아야 AI·가시화가 계약 커밋만 선택적으로 가져갈 수 있다.
