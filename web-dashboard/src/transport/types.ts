/**
 * src/transport/types.ts
 *
 * 와이어 계약의 클라이언트 측 정의. **이 폴더 밖으로 나가는 것은 Envelope 뿐이고,
 * 그 위의 코드는 WebSocket도 토픽 문자열도 알지 못한다.**
 *
 * 백엔드가 논리 구독 대신 토픽 문자열 방식을 고르면 이 폴더만 갈아끼운다.
 * 그 교체가 성립하려면 아래 두 규칙을 지켜야 한다.
 *   - 상위 코드는 `Selector`(계약 축)로만 말한다. 토픽·URL·프레임은 여기서 끝난다.
 *   - 상위 코드는 재연결·구독 복원을 신경 쓰지 않는다. 여기가 알아서 한다.
 */

/** 구독 축 (VZ-I-01 / REQ-704). 전송 프로토콜의 토픽 문자열을 노출하지 않는다. */
export type Selector = {
  entity: string;
  node: string;
  channel: string;
};

export type Channel =
  | 'state'
  | 'telemetry'
  | 'heartbeat'
  | 'video_meta'
  | 'actuator_state'
  | 'command_result'
  | 'metrics';

/**
 * VZ-I-11 — 구독 범위(관심 영역). **현 단계 'all' 고정.**
 * 화면 병합은 그리는 부하만 줄이고 받는 양은 그대로다. 대상이 늘면 여기서 좁혀야 한다.
 */
export type ScopeSpec = 'all' | { zones?: string[]; nodes?: string[] };

/** VZ-C-03 — 집약 계층 표기. 와이어에서는 축약 문자열과 객체형 둘 다 올 수 있다. */
export type WireAggregation =
  | 'raw'
  | {
      mode: 'raw' | 'aggregated';
      layer?: 'device' | 'edge' | 'server';
      method?: 'mean' | 'sum' | 'max' | 'min' | 'count' | 'rate';
      window_ms?: number;
    };

export type Quality = 'good' | 'degraded' | 'unknown';

/** 서버 → 클라이언트 메시지 봉투. */
export type Envelope = {
  zone: string | null;
  node: string;
  entity: string;
  channel: Channel;
  /** **서버 시각** ISO-8601. */
  ts: string;
  seq: number;
  payload: unknown;
  quality: Quality;
  aggregation: WireAggregation;
  scope: ScopeSpec;
};

/** 상태 3층 원본 (REQ-205). 단일 값으로 뭉치지 않는다. */
export type StateLayers = {
  device_status: 'ok' | 'fault' | 'unknown' | null;
  /** **서버가 판정한 값.** 클라이언트는 이 값을 다시 계산하지 않는다. */
  availability: 'online' | 'offline' | 'stale' | null;
  deployment: 'deployed' | 'not_deployed';
  last_seen: string | null;
  stale_threshold_ms: number;
  reason: string | null;
};

/** 액추에이터 도메인 어휘 (VZ-U-01). 표준 3층과 별개다. */
export type ActuatorState = {
  phase: 'idle' | 'moving' | 'completed' | 'error' | 'unverified';
  progress_pct: number | null;
  position_pct: number | null;
  control_locked: boolean;
  lock_reason: string | null;
  command_id: string | null;
};

/** REQ-903 — 본 레이어는 명령 결과를 3상태로 표시한다. */
export type CommandResult = {
  command_id: string;
  status: 'accepted' | 'completed' | 'rejected' | 'timeout' | 'failed';
  stage?: string;
  detail?: string;
  expires_at?: string;
};

/** VZ-C-04 — 역할 응답. scope는 현 단계 ['*'] 고정이지만 형태에 자리를 둔다. */
export type RoleInfo = {
  role: string;
  scope: string[];
};

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';

export type ConnectionStatus = {
  state: ConnectionState;
  /** 몇 번째 재시도인가. 0이면 정상 연결. */
  attempt: number;
  /** 다음 재시도까지 남은 시간(ms). 재연결 대기 중이 아니면 null. */
  nextRetryInMs: number | null;
  /** 마지막 hello의 서버 시각. 클라이언트 시계와 비교하지 않는다(표시용). */
  serverTime: string | null;
  staleThresholdMs: number | null;
  lastError: string | null;
};
