/**
 * src/physical/navFeed.ts (260915 신설 — 자율주행 편 · pi1 중계)
 *
 * **pi1 이 가시화에 전해 주는 것을 뜯고 들고 있는 열.** 명령 응답(uplink)도 장비 상태도 아닌
 * 세 번째 귀다.
 *
 * ## 누가 로봇을 모는가
 *
 * 문 찾기 편(pi7)은 **화면이 명령을 낸다.** 자율주행 편(pi1)은 다르다 — 로봇을 모는 것은
 * **유니티**다(UDP 15110 `go1_path` · `PATH_CANCEL`). 화면은 pi1 이 「무엇을 받았고 로봇이
 * 어떤가」를 옮겨 주는 것을 **보기만 한다.** 그래서 이 파일에는 보내는 함수가 없다.
 *
 * ## 계약 (`문서/작업프롬프트_pi1_가시화중계_260915.md` §3 — 이 파일이 받는 쪽의 정본)
 *
 *   <zone>/robot/<entity>/nav_state   JSON · QoS 0 · 0.5초마다 · retain 안 함
 *   <zone>/robot/<entity>/nav_event   JSON · QoS 1 · 일어날 때마다
 *
 * `schema` 가 `viz-nav/1` 이 아니면 버린다 — 모양이 바뀐 것을 옛 규칙으로 읽으면 조용히
 * 틀린 값이 된다. **없는 값은 null 이고 지어 채우지 않는다.** 배터리 `null` 은 0% 가 아니다.
 *
 * 신선도는 **받은 시각(이 노트북 시계)** 으로 잰다. `ts_ms` 는 pi1 시계라 표시에만 쓴다 —
 * 두 시계가 어긋나면 멀쩡한 값이 낡아 보이거나 낡은 값이 살아 보인다.
 */

import { useSyncExternalStore } from 'react';

export const NAV_SCHEMA = 'viz-nav/1';

/** 방위를 어디서 읽었나. 규약이 반대라 섞으면 부호가 뒤집힌다. */
export type YawSource = 'bridge_state' | 'go1_odometry';

/** `nav_state` 한 건. */
export type NavTelemetry = {
  nodeId: string;
  entityId: string;
  /** pi1 시계(ms). 표시용. */
  tsMs: number | null;
  batteryPct: number | null;
  yawDeg: number | null;
  /**
   * `bridge_state` — 브리지가 유니티에 보내는 상태(UDP 15101)의 yaw. 라디안을 도로 바꾼 값이고
   * 유니티 규약(+Z 기준 시계방향 +)이다. `go1_odometry` — robot-node 의 heading_deg(반시계 +).
   */
  yawSource: YawSource | null;
  /**
   * **IMU 방위(선택 키 `yaw_odometry_deg`)** (260915 pi1 답신 반영). 브리지 yaw 는 `-yaw_rel + offset` 이고
   * offset 이 **경로를 받을 때마다 다시 맞춰진다** — 경로 사이에 기준이 바뀐다. 그래서 Go1 내부 MQTT 의
   * IMU 값을 나란히 받는다. 부호가 반대다(반시계 +). 없으면 null — v1 에 더한 선택 키라 옛 중계는 안 싣는다.
   */
  yawOdometryDeg: number | null;
  moving: boolean | null;
  pathActive: boolean | null;
  pathId: number | null;
  /** 받은 시각(이 노트북 시계, ms). 신선도는 이것으로 잰다. */
  receivedAtMs: number;
};

export type NavEventKind = 'path_received' | 'path_cancel' | 'cancel_ack' | 'path_done' | 'estop' | 'feed_started';
const EVENT_KINDS: ReadonlySet<string> = new Set<NavEventKind>(['path_received', 'path_cancel', 'cancel_ack', 'path_done', 'estop', 'feed_started']);

/** `nav_event` 한 건. */
export type NavEvent = {
  nodeId: string;
  entityId: string;
  seq: number;
  tsMs: number | null;
  event: NavEventKind;
  pathId: number | null;
  pointCount: number | null;
  /** pi1 이 어디서 봤나 (`journal` · `udp15110` · `udp15101_mode99` · `udp15100_estop` …). 없으면 null. */
  source: string | null;
  note: string | null;
  receivedAtMs: number;
};

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const int = (value: unknown): number | null => {
  const n = num(value);
  return n !== null && Number.isInteger(n) ? n : null;
};
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
const bool = (value: unknown): boolean | null => (typeof value === 'boolean' ? value : null);

/** 토픽 → 채널. 우리 것이 아니면 null — 남의 토픽을 지어 해석하지 않는다. */
export function navChannel(topic: string): 'nav_state' | 'nav_event' | null {
  const parts = topic.split('/');
  if (parts.length !== 4 || parts.some((part) => part === '')) return null;
  const channel = parts[3];
  return channel === 'nav_state' || channel === 'nav_event' ? channel : null;
}

/** 토픽의 장비 id. 본문에 없을 때만 쓴다. */
function entityOfTopic(topic: string): string {
  return topic.split('/')[2] ?? '';
}

export function parseNavState(topic: string, body: Record<string, unknown>, receivedAtMs = Date.now()): NavTelemetry | null {
  if (body.schema !== NAV_SCHEMA) return null;
  const yawSource = body.yaw_source === 'bridge_state' || body.yaw_source === 'go1_odometry' ? body.yaw_source : null;
  const battery = num(body.battery_pct);
  const yaw = num(body.yaw_deg);
  return {
    nodeId: str(body.node_id) ?? '',
    entityId: str(body.entity_id) ?? entityOfTopic(topic),
    tsMs: num(body.ts_ms),
    // 0~100 밖은 받은 값이 아니라 고장이다 — 모르는 것으로 둔다.
    batteryPct: battery !== null && battery >= 0 && battery <= 100 ? battery : null,
    // 방위가 있는데 출처가 없으면 부호를 모른다 — 값째 버린다.
    yawDeg: yaw !== null && yawSource !== null ? yaw : null,
    yawSource,
    yawOdometryDeg: num(body.yaw_odometry_deg),
    moving: bool(body.moving),
    pathActive: bool(body.path_active),
    pathId: int(body.path_id),
    receivedAtMs,
  };
}

export function parseNavEvent(topic: string, body: Record<string, unknown>, receivedAtMs = Date.now()): NavEvent | null {
  if (body.schema !== NAV_SCHEMA) return null;
  const seq = int(body.seq);
  if (seq === null || typeof body.event !== 'string' || !EVENT_KINDS.has(body.event)) return null;
  return {
    nodeId: str(body.node_id) ?? '',
    entityId: str(body.entity_id) ?? entityOfTopic(topic),
    seq,
    tsMs: num(body.ts_ms),
    event: body.event as NavEventKind,
    pathId: int(body.path_id),
    pointCount: int(body.point_count),
    source: str(body.source),
    note: str(body.note),
    receivedAtMs,
  };
}

// ── 열 ───────────────────────────────────────────────────────────────────────

export type NavFeedState = {
  /** 마지막 `nav_state`. 한 건도 안 왔으면 null. */
  telemetry: NavTelemetry | null;
  /**
   * **pi1 시계 → 이 노트북 시계 차(ms)** — 최근 `nav_state` 의 (받은 시각 − `ts_ms`) 중앙값. 셋 미만이면 null.
   * 260915 실측으로 pi1 이 약 2.3초 앞서 있었다. 늦게 온 사건의 시각을 되돌리는 데 쓴다(`eventTimeMs`).
   */
  clockOffsetMs: number | null;
  /** 받은 사건. 받은 순서 그대로 — 오래된 것부터 버린다. */
  events: readonly NavEvent[];
  /** 버린 건수(모양이 안 맞음). 연결 관리가 「오긴 오는데 못 읽는다」를 말하는 재료다. */
  rejected: number;
};

/** 들고 있는 사건 수. 한 판이 이보다 길면 앞부터 버린다 — 노드 칠하기는 받는 즉시 끝난다. */
export const NAV_EVENT_KEEP = 500;

const EMPTY: NavFeedState = { telemetry: null, clockOffsetMs: null, events: [], rejected: 0 };
let state: NavFeedState = EMPTY;
/** QoS 1 은 같은 사건을 두 번 줄 수 있다. 중계가 다시 뜨면 seq 가 1 로 돌아가므로 시각을 같이 본다. */
const seen = new Set<string>();
/** 시계 차 표본 — `nav_state` 는 큐에 안 쌓이고 제때 오므로(pi1 보고 §6-10) 표본으로 쓸 수 있다. */
const offsetSamples: number[] = [];
const OFFSET_SAMPLES = 15;

function sampleOffset(telemetry: NavTelemetry): number | null {
  if (telemetry.tsMs === null) return state.clockOffsetMs;
  offsetSamples.push(telemetry.receivedAtMs - telemetry.tsMs);
  if (offsetSamples.length > OFFSET_SAMPLES) offsetSamples.shift();
  if (offsetSamples.length < 3) return null;
  const sorted = [...offsetSamples].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/** 이만큼 넘게 늦게 온 사건은 「큐에 있다 온 것」으로 보고 시각을 되돌린다. 네트워크 지연은 이보다 한참 짧다. */
export const NAV_LATE_MS = 2000;

/**
 * **그 사건이 일어난 시각(이 노트북 시계, ms).**
 *
 * pi1 은 브로커가 끊긴 동안 `nav_event` 를 큐에 뒀다가 다시 붙으면 보낸다(보고 §6-10 — `ts_ms` 는 사건 시각).
 * 받은 시각으로 칠하면 그 사건들이 **다시 붙은 순간에 몰려** 칠해지고, 판을 열기 전 사건이 이 판의 것처럼 들어온다.
 * 그래서 시계 차를 알고, 받은 시각보다 `NAV_LATE_MS` 넘게 앞선 사건이면 되돌린 시각을 쓴다.
 * 제때 온 사건은 받은 시각 그대로다 — 시계 차 추정의 흔들림이 평소 시각을 흔들면 안 된다.
 */
export function eventTimeMs(event: NavEvent, current: NavFeedState = state): number {
  if (event.tsMs === null || current.clockOffsetMs === null) return event.receivedAtMs;
  const happened = event.tsMs + current.clockOffsetMs;
  return event.receivedAtMs - happened > NAV_LATE_MS ? happened : event.receivedAtMs;
}

/**
 * **PATH_CANCEL 과 짝인 정지** — 이 `estop` 과 pi1 시각이 이만큼 안에 붙은 `path_cancel` 이 있으면 짝이다.
 *
 * 260915 §4.4 실측: 유니티는 경로를 바꿀 때 PATH_CANCEL 과 **같은 ms** 에 15100 으로 `0 0 0 1` 을 보내고 15~35 ms 뒤
 * `0` 으로 돌린다. 계약(15100 0→1)대로 그것도 `estop` 으로 나온다 — **비상 정지가 아니라 취소용 정지**다.
 * 실측 짝의 차이는 0~2 ms 였고, 한 번의 취소에 오는 PATH_CANCEL 끼리는 약 0.1초 떨어진다. 그래서 창을 0.1초보다
 * 좁게 잡는다 — 넓히면 다음 PATH_CANCEL 과도 짝이 된다(그래도 취소용이라 틀리지는 않지만, 짝의 뜻이 흐려진다).
 */
export const ESTOP_CANCEL_PAIR_MS = 60;

export function isCancelStop(event: NavEvent, events: readonly NavEvent[] = state.events): boolean {
  if (event.event !== 'estop' || event.tsMs === null) return false;
  const at = event.tsMs;
  return events.some((other) => other.event === 'path_cancel' && other.nodeId === event.nodeId
    && other.tsMs !== null && Math.abs(other.tsMs - at) <= ESTOP_CANCEL_PAIR_MS);
}

const listeners = new Set<(event: NavEvent | null) => void>();

function commit(next: NavFeedState, event: NavEvent | null): void {
  state = next;
  for (const listener of listeners) listener(event);
}

export function navFeedState(): NavFeedState {
  return state;
}

/**
 * 한 건 받기. 받아들였으면 true. 사건이면 구독자에게 그 사건을 같이 넘긴다 —
 * 노드 칠하기가 열을 처음부터 다시 훑지 않게.
 */
export function receiveNavMessage(topic: string, body: Record<string, unknown>, nowMs = Date.now()): boolean {
  const channel = navChannel(topic);
  if (channel === null) return false;
  if (channel === 'nav_state') {
    const telemetry = parseNavState(topic, body, nowMs);
    if (telemetry === null) { commit({ ...state, rejected: state.rejected + 1 }, null); return false; }
    commit({ ...state, telemetry, clockOffsetMs: sampleOffset(telemetry) }, null);
    return true;
  }
  const event = parseNavEvent(topic, body, nowMs);
  if (event === null) { commit({ ...state, rejected: state.rejected + 1 }, null); return false; }
  const key = `${event.nodeId}|${event.seq}|${event.tsMs ?? ''}`;
  if (seen.has(key)) return false;
  seen.add(key);
  const events = [...state.events, event];
  commit({ ...state, events: events.length > NAV_EVENT_KEEP ? events.slice(-NAV_EVENT_KEEP) : events }, event);
  return true;
}

export function subscribeNav(listener: (event: NavEvent | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const subscribeForReact = (listener: () => void) => subscribeNav(() => listener());

export function useNavFeed(): NavFeedState {
  return useSyncExternalStore(subscribeForReact, navFeedState, navFeedState);
}

// ── 임무 기록 · 다시보기 (260915 지시 「다시보기에 기록도 남기도록」) ─────────────

export type RecordedNavFeed = {
  /** 이 판을 연 시각(이 노트북 시계). 사건은 이 뒤에 일어난 것만 남긴다. */
  startedAtMs: number | null;
  telemetry: NavTelemetry | null;
  clockOffsetMs: number | null;
  events: NavEvent[];
  rejected: number;
};

/**
 * 기록기가 뜨는 몫. 열은 판을 넘어 쌓이므로(최근 500건) **이 판에 일어난 사건만** 남긴다 — 지난 판의 경로 사건이
 * 이 판 기록에 섞이면 다시보기의 액션 아이템이 거짓말을 한다.
 */
export function recordableNavFeed(startedAtMs: number | null): RecordedNavFeed {
  return {
    startedAtMs,
    telemetry: state.telemetry,
    clockOffsetMs: state.clockOffsetMs,
    events: startedAtMs === null ? [] : state.events.filter((event) => eventTimeMs(event) >= startedAtMs),
    rejected: state.rejected,
  };
}

/** 다시보기 — 그 판의 값을 도로 채운다. 다시 받는 사건이 중복으로 안 들어오게 중복 표도 같이 채운다. */
export function restoreNavFeed(saved: Partial<RecordedNavFeed> | undefined): void {
  seen.clear();
  offsetSamples.length = 0;
  const events = Array.isArray(saved?.events) ? saved.events : [];
  for (const event of events) seen.add(`${event.nodeId}|${event.seq}|${event.tsMs ?? ''}`);
  commit({
    telemetry: saved?.telemetry ?? null,
    clockOffsetMs: saved?.clockOffsetMs ?? null,
    events,
    rejected: saved?.rejected ?? 0,
  }, null);
}

/** 검사가 판을 비울 때 · 다시보기를 닫을 때. */
export function resetNavFeed(): void {
  seen.clear();
  offsetSamples.length = 0;
  commit(EMPTY, null);
}

/** 이 값이 지금 값인가 — 중계는 0.5초마다 내므로 넉넉히 6초. 연결 관리와 노드가 같은 기준을 쓴다. */
export const NAV_FRESH_MS = 6000;

export function telemetryFresh(telemetry: NavTelemetry | null, nowMs = Date.now()): boolean {
  return telemetry !== null && nowMs - telemetry.receivedAtMs <= NAV_FRESH_MS;
}
