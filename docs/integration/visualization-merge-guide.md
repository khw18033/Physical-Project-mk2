# 가시화 파트 병합·연결 안내

현재 `khw_VZ` 브랜치는 탐지 오버레이, 위험 표시, AI 실패 알림, 계획 승인 화면을 이미
갖고 있다. 이번 계약 반영은 화면 재작성보다 수신 타입과 정합 키를 교체하는 작업이다.

## 가져갈 범위

가시화 브랜치에는 다음을 반영한다.

- `contracts/ai/` 전체
- `contracts/ai/examples/*.json`을 TypeScript fixture로 사용
- 이 문서와 `docs/integration/README.md`

Python `ai-framework` 코드는 가시화 빌드 의존성으로 추가하지 않는다.

## 필수 타입 변경

### 탐지 결과

기존 `frame_ref: number`를 다음 객체로 변경한다.

```ts
type FrameReference = {
  source_id: string;
  capture_timestamp: string;
  sequence_id: number;
  frame_id: string | null;
  time_sync_state: 'SYNCED' | 'DEGRADED';
};
```

프레임 버퍼 키는 숫자 하나가 아니라 `source_id + sequence_id` 조합을 사용한다. 탐지 박스는
배열이 아니라 `{x, y, width, height}`를 사용한다. `bbox_space.format`이 `normalized`일 때만
표시 크기를 곱하고 `absolute`일 때는 기준 해상도 비율을 적용한다.

### 위험도

`RiskState`는 `payload.state`, `payload.score`, `payload.reasons`, `payload.recommendation`,
`payload.decided_at`을 읽는다. AI 내부 이름인 `risk_level`을 화면에서 직접 기대하지 않는다.

### AI 실패와 기능 상태

- `ai_failure`: 즉시 알림과 오류 이력에 사용
- `capability_status`: ACTIVE/DEGRADED/DISABLED 표시와 미배포·축소 운용 판정에 사용

현재 `EDGE_SILENCE_MS`로 엣지 정밀 인지 부재를 추정하는 코드는 `capability_status`가 도착한
후 서버 선언을 우선하도록 바꾼다. 시간 기반 추정은 구버전 fallback으로만 유지한다.

### 계획·모델 배포

- `plan_proposal`을 기존 화면의 `Plan`으로 변환할 때 승인 상태·route·command_id는 백엔드
  응답에서 보강한다. AI payload에 없는 값을 화면이 추정하지 않는다.
- `model_deployment_result`의 FAILED/ROLLED_BACK은 `ai_failure`와 별도로 모델 상태 패널에
  표시한다. 실패 알림을 함께 받더라도 동일 `correlation_id`로 중복 표시를 접는다.

## 기존 VZ 채널 변경

`Channel` union에 최소 다음 값을 반영한다.

- `plan_proposal`
- `capability_status`
- `model_deployment_result`

기존 `detections`, `risk_state`, `ai_failure`는 이름을 유지하되 payload 타입을 Schema에 맞춘다.

## TypeScript 계약 검증

Ajv 2020 또는 동등한 JSON Schema validator로 `contracts/ai/examples/*.json`을 빌드 테스트에서
검증한다. 화면 타입만 맞고 실제 JSON parser가 다른 경우를 막기 위해 mock gateway도 같은
예제를 발행하는 시나리오를 둔다.

필수 회귀 항목은 다음과 같다.

- 서로 다른 카메라의 같은 `sequence_id`가 같은 프레임으로 합쳐지지 않는다.
- `x1,y1,x2,y2` 배열을 실수로 받으면 조용히 그리지 않고 계약 오류로 기록한다.
- association unavailable이면 소스별 track을 유지한다.
- capability DEGRADED는 AI 실패로 표시하지 않는다.
- AI failure와 model deployment failure를 `correlation_id`로 연결한다.
- 승인 전 `plan_proposal`이 실행 중 상태로 표시되지 않는다.

## Git 적용 시 주의

현재 AI와 VZ 브랜치의 커밋 파일 충돌 예상은 `.gitignore` 하나다. 충돌 시 VZ의 Node/Unity
규칙과 AI의 Python 규칙을 모두 유지한다. 기존 `contracts/` 디렉터리 아래에 `ai/`가 새로
추가되므로 기존 가시화 Schema를 삭제하거나 이동할 필요는 없다.
