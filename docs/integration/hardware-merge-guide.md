# 하드웨어 파트 병합·연결 안내

대상 요구사항은 `HW-R-04`, `HW-R-05`, `HW-R-08`, `HW-R-10`, `HW-S-03`,
`HW-S-06`, `HW-S-08`, `HW-C-01`, `HW-C-02`다.

## 가져갈 범위

하드웨어 브랜치에는 우선 아래 파일만 반영하면 된다.

- `contracts/ai/frame-reference.schema.json`
- `contracts/ai/model-deployment-result.schema.json`
- `contracts/ai/message.schema.json`
- `contracts/ai/examples/model-deployment-result.json`
- 필요 시 `contracts/ai/detection-result.schema.json`과 탐지 예제

Python 기반 온보드 코드를 함께 사용한다면 다음 구현도 반영한다.

- `ai-framework/ai_framework/providers/adapters.py::ModelDeploymentProvider`
- `ai-framework/ai_framework/runtime/model_deployment.py`

AI 내부 detector, tracker, planner 구현을 하드웨어 코드에 복사하지 않는다.

## 카메라·프레임 연결

영상 픽셀은 MQTT/Kafka/OTLP 메시지에 넣지 않는다. RTSP·WebRTC·로컬 카메라 등 별도 미디어
경로를 사용하고 업무 메시지에는 프레임 참조만 전달한다.

필수 프레임 참조는 다음 네 값이다.

| 필드 | 생산 위치 | 의미 |
|---|---|---|
| `source_id` | 카메라 adapter | 카메라 논리 식별자 |
| `capture_timestamp` | 프레임 취득 노드 | NTP 기준 ISO-8601 시각 |
| `sequence_id` | 프레임 취득 노드 | 소스별 단조 증가 순서 |
| `time_sync_state` | 시간 동기 감시 | `SYNCED` 또는 `DEGRADED` |

`frame_ref`를 단일 frame 번호로 축약하지 않는다. 카메라가 둘 이상이면 같은 번호가 생길 수
있고, 재접속 시 번호가 초기화돼 오버레이 정합이 깨진다.

## 모델 수신·적용

장치별 구현은 `ModelDeploymentProvider` 뒤에 둔다.

1. `current_version`: 현재 활성 모델 버전 조회
2. `download`: 내부 저장소의 artifact를 staging 위치로 수신
3. `validate`: checksum과 장치·runtime 호환성 검증
4. `activate`: 검증된 버전을 원자적으로 활성화
5. `rollback`: 활성화 실패 시 직전 정상 버전 복구

파일 경로, systemd 명령, runtime reload API는 provider 내부에만 둔다. 적용 결과는
`model_deployment_result` 채널로 발행하며 최소한 `model_id`, `model_version`, `checksum`,
`target_node_id`, `status`, `previous_version`, `reason`을 포함한다.

## 로컬 안전·제어 경계

- 카메라 입력이 사라지면 하드웨어 제어계가 받을 상태는 `SAFE_STOP`이다.
- 네트워크·엣지가 끊겨도 로컬 안전 판단과 제어기 연결은 유지한다.
- AI의 `recommendation`은 물리 명령이 아니다. 실제 구동 명령 번역과 물리 완료 확인은
  백엔드·하드웨어가 담당한다.
- 명령 전달 ACK와 물리 동작 완료를 같은 상태로 보고하지 않는다.

## 검증 체크리스트

- `contracts/ai/examples/model-deployment-result.json`을 장치 메시지 parser가 읽는다.
- 잘못된 checksum이면 기존 모델이 계속 활성 상태다.
- 활성화 실패 시 직전 버전 복구 결과가 `ROLLED_BACK`으로 보고된다.
- NTP 장애 중에도 `sequence_id`가 계속 증가한다.
- 영상 픽셀이 MQTT/Kafka payload에 포함되지 않는다.
- 실제 Raspberry Pi에서 AI-B-10 자원 사용량과 최소 안전 응답시간을 별도로 측정한다.

## Git 적용 시 주의

현재 공개된 `origin/HW`는 `origin/main`과 동일하다. 하드웨어 로컬 변경이 따로 있다면 먼저
커밋 또는 별도 보존한 뒤 계약 커밋만 선택적으로 반영한다. `.gitignore`에는 Python 캐시와
하드웨어 빌드 산출물 규칙을 모두 유지한다.
