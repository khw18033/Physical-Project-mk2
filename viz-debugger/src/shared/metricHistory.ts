/**
 * src/shared/metricHistory.ts (261110 신설 — 실시간 상태 그래프)
 *
 * **장비마다 · 지표마다 최근 3분의 값.** 하드웨어 카드의 미니 그래프와 전체 장치 확인의 흐름 그래프가
 * 여기만 읽는다. 받는 쪽(`deviceTelemetry.ts` · `fcxStatus.ts`)이 밀어 넣고, 그리는 쪽은 받는 길을 모른다 —
 * `deviceTelemetry.ts` 와 같은 방향이고 같은 이유다(그리는 쪽이 `tabs/` · `physical/` 를 못 부른다).
 *
 * ## 받은 것만 적는다 — 지어 채우지 않는다
 *
 * 점은 **받은 시각**에 받은 값 하나다. 안 온 동안은 점이 없다. 「끊김」은 따로 적지 않고 점 사이 간격으로
 * 판정한다(`trendRuns`) — 그 지표가 평소 오는 간격(중앙값)의 세 배를 넘게 비면 선을 끊는다. 장비마다
 * 보내는 주기가 달라(드론 FC 5 Hz · `/state` 1 Hz · Go1 status 수 초) 고정 문턱 하나로는 못 가른다.
 *
 * 예외가 하나다 — **수신 간격**(`AGE_KEY`). 장비가 보낸 값이 아니라 이 브라우저가 0.5초마다 「마지막으로
 * 무엇이든 받은 지 몇 초」를 잰다(`startMetricSampler`). 그래서 끊긴 동안에도 이 선만은 계속 올라간다 —
 * 끊김이 「선이 사라짐」과 「간격이 치솟음」 둘로 함께 보인다.
 *
 * ## 같은 지표가 두 길로 오면
 *
 * 드론은 FC 확장 텔레메트리(5 Hz)와 `/state`(1 Hz)가 같은 값을 싣는다. 둘을 섞으면 간격 중앙값이 흔들리고
 * 값이 미세하게 엇갈려 선이 톱니가 된다. FC 쪽이 최근 3초 안에 왔으면 `/state` 의 숫자는 그 지표에
 * 안 적는다(`FCX_PREFERRED_MS`).
 */

/** 숫자 점 하나. */
export type MetricPoint = { atMs: number; v: number };
/** 범주 점 하나 — 모드 · 동작. `code` 는 장비가 보낸 규약 문자열이거나 우리가 정한 코드(`moving` · `idle`). */
export type StatePoint = { atMs: number; code: string };

export const HISTORY_WINDOW_MS = 180_000;
const MAX_POINTS = 1_200;
const FCX_PREFERRED_MS = 3_000;
/** 선을 끊는 최소 간격. 5 Hz 장비가 한두 점 놓친 것은 끊김이 아니다. */
const MIN_BREAK_MS = 1_500;
export const SAMPLE_MS = 500;

/** 이 브라우저가 잰 「마지막 수신 후 초」. */
export const AGE_KEY = 'rx.age_s';
/** Go1 의 동작 — 속도로 가른다(`MOVING_MPS`). */
export const MOTION_KEY = 'motion';
const MOVING_MPS = 0.05;

let metrics: Record<string, Record<string, MetricPoint[]>> = {};
let states: Record<string, Record<string, StatePoint[]>> = {};
let lastSeen: Record<string, number> = {};
let fcxAt: Record<string, number> = {};

function push<T extends { atMs: number }>(list: T[], point: T): void {
  // 받은 시각이 거꾸로 오면(시계 · 재생) 그 점은 버린다 — 선이 되돌아가면 읽을 수 없다.
  if (list.length > 0 && list[list.length - 1]!.atMs > point.atMs) return;
  list.push(point);
  const floor = point.atMs - HISTORY_WINDOW_MS;
  let drop = 0;
  while (drop < list.length && list[drop]!.atMs < floor) drop++;
  if (list.length - drop > MAX_POINTS) drop = list.length - MAX_POINTS;
  if (drop > 0) list.splice(0, drop);
}

export function noteMetric(deviceId: string, key: string, v: number | null | undefined, atMs = Date.now()): void {
  if (deviceId === '' || typeof v !== 'number' || !Number.isFinite(v)) return;
  push(((metrics[deviceId] ??= {})[key] ??= []), { atMs, v });
}

export function noteState(deviceId: string, key: string, code: string | null | undefined, atMs = Date.now()): void {
  if (deviceId === '' || typeof code !== 'string' || code === '') return;
  push(((states[deviceId] ??= {})[key] ??= []), { atMs, code });
}

/** 무엇이든 받았다 — 수신 간격의 기준점. */
export function noteSeen(deviceId: string, atMs = Date.now()): void {
  if (deviceId === '') return;
  if ((lastSeen[deviceId] ?? -Infinity) < atMs) lastSeen[deviceId] = atMs;
}

export function lastSeenAt(deviceId: string): number | null {
  return lastSeen[deviceId] ?? null;
}

export function metricSeries(deviceId: string, key: string): readonly MetricPoint[] {
  return metrics[deviceId]?.[key] ?? [];
}

export function stateSeries(deviceId: string, key: string): readonly StatePoint[] {
  return states[deviceId]?.[key] ?? [];
}

// ── 받는 쪽이 부르는 것 ─────────────────────────────────────────────────────

/** `/state` · MQTT 본문에서 그래프로 그릴 숫자. 경로가 곧 지표 이름이다(`stateRows.ts` 의 경로와 같다). */
export const TREND_PATHS = [
  'battery.remaining_pct',
  'battery.voltage_v',
  'altitude.relative_m',
  'gps.satellites',
  // Go1 모양(`deviceState.ts` 의 고정 칸과 같은 이름)
  'battery_pct',
  'speed_mps',
  // 위치 — 그래프에는 안 그리지만 조작 기록의 표본이 쓴다(261111). 드론 위도 · 경도, Go1 지도 좌표 · 방위
  'gps.lat',
  'gps.lon',
  'position.x',
  'position.y',
  'position.heading_deg',
] as const;

/**
 * 범주 — 상태 타일 하나하나가 띠 그래프가 된다(261111). 드론 비행 모드 · 무장 · GPS 고정, Go1 생사(`status`) ·
 * 로봇 링크 · 장비 상태 · 로봇 모드 · 임무 중 · 구동 브리지. 참/거짓은 `'true'` · `'false'` 로 적는다.
 */
const STATE_PATHS = ['flight.mode', 'flight.armed', 'gps.fix', 'robot_mode', 'status', 'link', 'device_status', 'in_mission', 'sdk.ready'] as const;
/** FC 확장 텔레메트리가 살아 있으면 `/state` 쪽을 안 적는 범주. */
const FCX_STATES = new Set<string>(['flight.mode', 'flight.armed', 'gps.fix']);

const codeOf = (value: unknown): string | null =>
  typeof value === 'string' ? value : typeof value === 'boolean' ? String(value) : null;

function at(body: Record<string, unknown>, path: string): unknown {
  let cursor: unknown = body;
  for (const part of path.split('.')) {
    if (cursor === null || typeof cursor !== 'object' || Array.isArray(cursor)) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return cursor;
}

/** 상태 보고 한 건(`noteDeviceTelemetry` 가 부른다). 빈 몸(heartbeat)도 「받았다」는 적는다. */
export function noteTelemetryBody(deviceId: string, body: Record<string, unknown>, atMs = Date.now()): void {
  noteSeen(deviceId, atMs);
  const fcxLive = atMs - (fcxAt[deviceId] ?? -Infinity) < FCX_PREFERRED_MS;
  for (const path of TREND_PATHS) {
    if (fcxLive && FCX_KEYS.has(path)) continue;
    const value = at(body, path);
    noteMetric(deviceId, path, typeof value === 'number' ? value : null, atMs);
  }
  for (const path of STATE_PATHS) {
    if (fcxLive && FCX_STATES.has(path)) continue;
    noteState(deviceId, path, codeOf(at(body, path)), atMs);
  }
  const speed = at(body, 'speed_mps');
  if (typeof speed === 'number' && Number.isFinite(speed)) noteState(deviceId, MOTION_KEY, speed > MOVING_MPS ? 'moving' : 'idle', atMs);
}

/** FC 확장 텔레메트리가 싣는 지표. 이것이 살아 있으면 `/state` 의 같은 지표는 안 적는다. */
const FCX_KEYS = new Set<string>(['battery.remaining_pct', 'battery.voltage_v', 'altitude.relative_m', 'gps.satellites', 'gps.lat', 'gps.lon']);

/** FC 확장 텔레메트리 한 건(`noteFcx` 가 부른다). 이 모양만 안다 — `fcxStatus.ts` 를 들여오지 않는다. */
export function noteFcxSample(deviceId: string, sample: {
  altRelM: number | null; groundspeed: number | null; climb: number | null; voltageV: number | null;
  remainingPct: number | null; satellites: number | null; mode: string | null;
  armed?: boolean | null; gpsFix?: string | null; ekfWorst?: number | null; rcRssi?: number | null; clockOffsetS?: number | null;
  lat?: number | null; lon?: number | null;
}, atMs = Date.now()): void {
  noteSeen(deviceId, atMs);
  fcxAt[deviceId] = atMs;
  noteMetric(deviceId, 'altitude.relative_m', sample.altRelM, atMs);
  noteMetric(deviceId, 'hud.groundspeed', sample.groundspeed, atMs);
  noteMetric(deviceId, 'hud.climb', sample.climb, atMs);
  noteMetric(deviceId, 'battery.voltage_v', sample.voltageV, atMs);
  noteMetric(deviceId, 'battery.remaining_pct', sample.remainingPct, atMs);
  noteMetric(deviceId, 'gps.satellites', sample.satellites, atMs);
  noteState(deviceId, 'flight.mode', sample.mode, atMs);
  noteState(deviceId, 'flight.armed', codeOf(sample.armed), atMs);
  noteState(deviceId, 'gps.fix', sample.gpsFix, atMs);
  noteMetric(deviceId, 'ekf.worst', sample.ekfWorst, atMs);
  noteMetric(deviceId, 'rc.rssi', sample.rcRssi, atMs);
  noteMetric(deviceId, 'clock.offset_s', sample.clockOffsetS, atMs);
  noteMetric(deviceId, 'gps.lat', sample.lat, atMs);
  noteMetric(deviceId, 'gps.lon', sample.lon, atMs);
}

/** 보고 줄 하나의 이력 키 — 모양을 모르는 장비도 줄마다 띠 그래프를 그린다. */
export const rowKey = (row: { labelKey: string | null; rawLabel?: string }): string => `row:${row.labelKey ?? row.rawLabel ?? ''}`;

/** 보고 줄을 범주 이력으로(`noteDeviceTelemetry` 가 부른다). 값 낱말 키가 있으면 그 키를, 없으면 보낸 글자 그대로. */
export function noteTelemetryRows(deviceId: string, rows: readonly { labelKey: string | null; rawLabel?: string; value: string; valueKey?: string }[], atMs = Date.now()): void {
  for (const row of rows) noteState(deviceId, rowKey(row), row.valueKey ?? row.value, atMs);
}

/** 0.5초마다 수신 간격을 잰다. 3분 넘게 아무것도 안 온 장비는 더 안 잰다(선이 이미 다 밀려 나갔다). */
export function sampleAges(nowMs = Date.now()): void {
  for (const [deviceId, seen] of Object.entries(lastSeen)) {
    if (nowMs - seen > HISTORY_WINDOW_MS) continue;
    noteMetric(deviceId, AGE_KEY, Math.max(0, (nowMs - seen) / 1000), nowMs);
  }
}

export function startMetricSampler(): () => void {
  const id = setInterval(() => sampleAges(), SAMPLE_MS);
  return () => clearInterval(id);
}

export function resetMetricHistory(): void {
  metrics = {};
  states = {};
  lastSeen = {};
  fcxAt = {};
}

// ── 그리는 쪽이 부르는 것 (순수 함수 — 검사가 그대로 부른다) ───────────────────

/** 이 지표가 평소 오는 간격의 세 배(최소 1.5초). 이보다 길게 비면 끊김이다. */
export function breakGapMs(points: readonly { atMs: number }[]): number {
  if (points.length < 3) return MIN_BREAK_MS * 2;
  const gaps: number[] = [];
  for (let i = Math.max(1, points.length - 60); i < points.length; i++) gaps.push(points[i]!.atMs - points[i - 1]!.atMs);
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)]!;
  return Math.max(MIN_BREAK_MS, median * 3);
}

export type TrendRuns = {
  /** 이어 그릴 덩어리들. 덩어리 사이는 끊김이다. */
  runs: MetricPoint[][];
  /** 끊긴 구간 [시작, 끝] ms — 회색으로 비워 둔다. 마지막 점 뒤로 소식이 없으면 「지금」까지. */
  gaps: Array<[number, number]>;
  /** 마지막 점이 아직 「지금」인가. 아니면 그 값을 현재값으로 말하지 않는다. */
  fresh: boolean;
  last: MetricPoint | null;
};

/** 창 안의 점을 끊김 기준으로 가른다. 창 왼쪽 밖의 점 하나는 선이 왼쪽 끝에서 들어오도록 남긴다. */
export function trendRuns(points: readonly MetricPoint[], nowMs: number, windowMs: number): TrendRuns {
  const breakMs = breakGapMs(points);
  const from = nowMs - windowMs;
  let start = points.length;
  while (start > 0 && points[start - 1]!.atMs >= from) start--;
  if (start > 0 && from - points[start - 1]!.atMs <= breakMs) start--;
  const visible = points.slice(start).filter((p) => p.atMs <= nowMs);
  const runs: MetricPoint[][] = [];
  const gaps: Array<[number, number]> = [];
  for (const point of visible) {
    const run = runs[runs.length - 1];
    const prev = run?.[run.length - 1];
    if (run === undefined || prev === undefined || point.atMs - prev.atMs > breakMs) {
      if (prev !== undefined) gaps.push([prev.atMs, point.atMs]);
      runs.push([point]);
    } else run.push(point);
  }
  const last = visible[visible.length - 1] ?? null;
  const fresh = last !== null && nowMs - last.atMs <= breakMs;
  if (last !== null && !fresh) gaps.push([last.atMs, nowMs]);
  return { runs, gaps, fresh, last };
}

export type StateSpan = { from: number; to: number; code: string | null };

/** 범주 값을 구간으로 묶는다. 점이 끊긴 동안은 `code: null`(수신 없음)이다. */
export function stateSpans(points: readonly StatePoint[], nowMs: number, windowMs: number): StateSpan[] {
  const breakMs = breakGapMs(points);
  const from = nowMs - windowMs;
  const spans: StateSpan[] = [];
  const add = (a: number, b: number, code: string | null) => {
    const lo = Math.max(a, from);
    const hi = Math.min(b, nowMs);
    if (hi <= lo) return;
    const prev = spans[spans.length - 1];
    if (prev !== undefined && prev.code === code && prev.to >= lo) prev.to = hi;
    else spans.push({ from: lo, to: hi, code });
  };
  for (let i = 0; i < points.length; i++) {
    const point = points[i]!;
    const next = points[i + 1];
    const end = next === undefined ? nowMs : next.atMs;
    if (end - point.atMs > breakMs) {
      add(point.atMs, point.atMs + breakMs, point.code);
      add(point.atMs + breakMs, end, null);
    } else add(point.atMs, end, point.code);
  }
  return spans;
}

/**
 * `spanMs` 전과 지금의 차. 둘 다 「그 시각의 값」이라고 말할 수 있을 때만 — 지금 값이 낡았거나
 * 그때 점이 없으면 `null` 이다(모르는 변화를 0으로 그리지 않는다).
 */
export function deltaOver(points: readonly MetricPoint[], nowMs: number, spanMs: number): number | null {
  const { fresh, last } = trendRuns(points, nowMs, spanMs + breakGapMs(points));
  if (!fresh || last === null) return null;
  const target = last.atMs - spanMs;
  const breakMs = breakGapMs(points);
  let best: MetricPoint | null = null;
  for (const point of points) {
    if (Math.abs(point.atMs - target) <= breakMs && (best === null || Math.abs(point.atMs - target) < Math.abs(best.atMs - target))) best = point;
  }
  return best === null ? null : last.v - best.v;
}

/** 모드가 바뀐 순간들 — 그래프에 세로 점선으로. 수신 없음과의 경계는 사건이 아니다. */
export function changeMoments(spans: readonly StateSpan[]): number[] {
  const out: number[] = [];
  let prev: string | null = null;
  for (const span of spans) {
    if (span.code === null) continue;
    if (prev !== null && prev !== span.code) out.push(span.from);
    prev = span.code;
  }
  return out;
}

/**
 * **지금 값** (261111 — 조작 기록 2차의 표본). 마지막 점이 `maxAgeMs` 안에 왔을 때만 — 낡은 값을 「그때 값」으로
 * 적지 않는다. 없으면 `null`.
 */
export function latestMetric(deviceId: string, key: string, nowMs: number, maxAgeMs: number): number | null {
  const last = metricSeries(deviceId, key).at(-1);
  return last !== undefined && nowMs - last.atMs <= maxAgeMs && last.atMs <= nowMs ? last.v : null;
}

export function latestState(deviceId: string, key: string, nowMs: number, maxAgeMs: number): string | null {
  const last = stateSeries(deviceId, key).at(-1);
  return last !== undefined && nowMs - last.atMs <= maxAgeMs && last.atMs <= nowMs ? last.code : null;
}
