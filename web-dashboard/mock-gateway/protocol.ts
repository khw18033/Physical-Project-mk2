/**
 * mock-gateway/protocol.ts
 *
 * 목 게이트웨이가 말하는 **와이어 계약**. 프런트엔드의 src/transport/types.ts 와 짝을 이룬다.
 * 두 파일이 의도적으로 중복되어 있는 이유: 프로세스 경계를 넘는 계약이므로 한쪽의
 * 타입을 import 하면 "서버를 갈아끼우면 프런트가 깨진다"는 결합이 생긴다.
 * 진짜 백엔드 게이트웨이가 나오면 이 파일은 버려지고 src/transport/types.ts 만 남는다.
 */

/** 구독은 전송 프로토콜의 토픽 문자열이 아니라 **계약 축**으로 표현한다 (VZ-I-01 / REQ-704). */
export type Selector = {
  /** Entity 식별자 또는 '*'. */
  entity: string;
  /**
   * Node 식별자 또는 '*'.
   * 편의상 Zone 식별자도 받는다 — 레지스트리로 해석해 그 Zone에 속한 모든 Node에 매칭한다.
   * (`{ node: "zone-503", channel: "state" }` 같은 구독이 성립하게 하기 위함)
   * ※ 미결: 정식 계약이 zone 축을 따로 둘지, node 축의 계층 매칭으로 둘지 결정 필요.
   */
  node: string;
  /** 채널 이름 또는 '*'. */
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
 * VZ-I-11 — 구독 범위(관심 영역) 한정. **현 단계 'all' 고정.**
 * 화면 병합은 그리는 부하만 줄이고 받는 양은 그대로이므로, 대상이 늘면 구독에서 좁혀야 한다.
 * 지금 자리를 남기는 비용은 필드 하나지만, 나중에 구독 프로토콜을 바꾸는 비용은
 * 게이트웨이와 전 화면에 전파된다.
 */
export type ScopeSpec = 'all' | { zones?: string[]; nodes?: string[] };

/**
 * VZ-C-03 — 집약 계층 경계 표기. **현 단계 'raw' 고정.**
 * 원본 측정은 문자열 'raw' 축약형으로, 집약값은 집약 계층을 담은 객체형으로 내려간다.
 * 표기가 없으면 화면이 집약값을 다시 평균 내는 **재집약 오류**가 발생한다.
 * ※ 미결: 정식 계약이 축약형/객체형 중 무엇을 쓸지 결정 필요. 수신 측은 둘 다 받아 정규화한다.
 */
export type AggregationSpec =
  | 'raw'
  | {
      mode: 'raw' | 'aggregated';
      /** 어느 계층에서 집약되었는가. */
      layer?: 'device' | 'edge' | 'server';
      method?: 'mean' | 'sum' | 'max' | 'min' | 'count' | 'rate';
      window_ms?: number;
    };

/**
 * 표본 자체의 품질 — "이 값을 지금 값으로 믿어도 되는가".
 * - `good`     : 현재값으로 신뢰 가능
 * - `degraded` : 값은 있으나 원천이 스스로 이상을 보고함 (device_status = fault 등)
 * - `unknown`  : 서버가 현재값임을 확인할 수 없음 (availability = stale / offline)
 *
 * availability(상태 3층)와 값이 겹쳐 보이지만 층이 다르다 — availability는 **대상**의 상태이고
 * quality는 **이 봉투 한 건**의 신뢰도다. 집약값이 섞이기 시작하면 둘은 갈라진다.
 * ※ 미결: quality의 정식 enum이 계약에 없다. 위 세 값은 이번 구현의 잠정 정의.
 */
export type Quality = 'good' | 'degraded' | 'unknown';

/** 서버 → 클라이언트 메시지 봉투. 필드 구성은 고정이다. */
export type Envelope = {
  /** Zone은 선택 계층이다(REQ-301). 지정되지 않으면 null. */
  zone: string | null;
  node: string;
  entity: string;
  channel: Channel;
  /** **서버 시각** ISO-8601. 클라이언트 시계를 신뢰하지 않는다. */
  ts: string;
  /** 대상별 단조 증가 시퀀스. 유실·역전 감지용. */
  seq: number;
  payload: unknown;
  quality: Quality;
  aggregation: AggregationSpec;
  /** 이 봉투가 어느 구독 범위 요청에 대한 응답인지 되돌려 준다(VZ-I-11 왕복 확인). */
  scope: ScopeSpec;
};

/** 상태 3층 원본 (REQ-205). 단일 값으로 뭉치지 않는다. */
export type StateLayers = {
  /** 기기 자기보고. */
  device_status: 'ok' | 'fault' | 'unknown' | null;
  /** 서버 판정. **stale 판정은 서버가 last_seen과 서버 시각으로 수행한다.** */
  availability: 'online' | 'offline' | 'stale' | null;
  /** 오케스트레이터 파생 (REQ-201). */
  deployment: 'deployed' | 'not_deployed';
  /**
   * 마지막 수신 시각(서버 시각 기준 ISO-8601). 발행한 적이 없으면 null.
   * 화면의 "최근 수신 N초 전"은 `envelope.ts - last_seen` 으로 구한다 —
   * **둘 다 서버 시각이므로 클라이언트 시계가 개입하지 않는다.**
   */
  last_seen: string | null;
  /** 화면이 "임계 60초" 같은 문구를 그릴 수 있도록 판정에 쓴 임계를 함께 내려 준다. */
  stale_threshold_ms: number;
  /** 상태 변화의 사람이 읽는 사유. 없으면 null. */
  reason: string | null;
};

/** 액추에이터 도메인 어휘 (VZ-U-01). 표준 3층과 별개로 다룬다. */
export type ActuatorState = {
  /** 대기 / 동작 중 / 완료 / 오류 / 확인 불가 */
  phase: 'idle' | 'moving' | 'completed' | 'error' | 'unverified';
  /** 0~100. phase가 moving일 때만 의미 있음. */
  progress_pct: number | null;
  /** 개도율 등 현재 물리량. */
  position_pct: number | null;
  /** 제어 잠금 여부와 사유 (VZ-O-05). */
  control_locked: boolean;
  lock_reason: string | null;
  /** 이 상태를 유발한 명령의 상관 키 (REQ-909). */
  command_id: string | null;
};

// ── 클라이언트 → 서버 ────────────────────────────────────────────────────────

export type ClientMessage =
  | { type: 'subscribe'; id: string; selector: Selector; scope?: ScopeSpec }
  | { type: 'unsubscribe'; id: string }
  | { type: 'role' }
  | { type: 'scenario'; name: string }
  | { type: 'ping'; t: number };

// ── 서버 → 클라이언트 ────────────────────────────────────────────────────────

export type ServerMessage =
  | { type: 'hello'; server_time: string; stale_threshold_ms: number; protocol: string }
  | { type: 'subscribed'; id: string; selector: Selector; scope: ScopeSpec; snapshot_count: number }
  | { type: 'unsubscribed'; id: string }
  | {
      type: 'role';
      role: string;
      /** VZ-C-04 — 역할이 적용되는 범위. 현 단계 ['*'] 고정. 응답 형태에 자리만 둔다. */
      scope: string[];
    }
  | { type: 'scenario'; name: string; accepted: boolean; message: string }
  | { type: 'pong'; t: number; server_time: string }
  | { type: 'data'; sub: string; envelope: Envelope }
  | { type: 'error'; message: string };
