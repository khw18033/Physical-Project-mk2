/**
 * src/autodrive/obstacle.ts (260915 신설 — 자율주행 편 · 장애물 탐지)
 *
 * **AI 서버의 장애물 JSON 을 받아 들고 있는 열.** 「장애물 탐지」(T-NB2)의 액션 아이템과 판단 근거가
 * 이것을 읽는다. 값은 **받은 그대로** 두고(`raw`), 화면이 읽기 쉽게 몇 칸만 뜯어 둔다.
 *
 * ## 받은 모양 (260915 실측 · `GET /control/go1_front`)
 *
 * ```json
 * {"timestamp":"1789438645.4756753","camera_id":"go1_front",
 *  "detections":[{"id":1,"name":"umbrella","group":"HARD_OBSTACLE","rel_depth":1.31,
 *                 "distance_cm":43.59,"distance_cm_raw":43.18,"risk_level":"near","bbox_xyxy":[91,221,230,379]}],
 *  "has_near_obstacle":true,"state_change":false}
 * ```
 *
 * 뜯지 못한 칸은 null 이다 — 지어 채우지 않는다. **판정(`has_near_obstacle`)은 AI 서버가 낸 것**이고
 * 화면이 거리로 다시 계산하지 않는다(탐지 편과 같은 규칙).
 *
 * ## 언제 묻는가
 *
 * 0.5초마다 — 서버가 그 주기로 값을 바꾼다. **누가 보고 있을 때만** 묻는다: 자율주행 판이 열려 있거나
 * (`startObstacleWatch`) 액션 아이템이 떠 있을 때(`holdObstaclePolling`). 붙잡은 수를 센다 — 둘 중 먼저
 * 끝난 쪽이 남은 쪽의 폴링을 끄면 「값이 멈췄다」로만 보인다.
 */

import { t } from '../i18n/dict.ts';
import { useSyncExternalStore } from 'react';
import { isReplayingRecord } from '../record/replayMode.ts';
import { fetchObstacleJson, type FetchLike } from './aiClient.ts';

/** 이 값을 붙이는 노드 — 자율주행 편(`MSN-260915-01`)의 「장애물 탐지」. */
export const OBSTACLE_TASK = 'T-NB2';

export type ObstacleDetection = {
  id: number | null;
  name: string;
  group: string | null;
  relDepth: number | null;
  distanceCm: number | null;
  distanceCmRaw: number | null;
  riskLevel: string | null;
  bbox: [number, number, number, number] | null;
};

export type ObstacleSnapshot = {
  cameraId: string | null;
  /** AI 서버 시계(초). 문자열로 오므로 숫자로 바꾼다. 표시·멈춤 판정용. */
  timestampSec: number | null;
  detections: readonly ObstacleDetection[];
  hasNearObstacle: boolean | null;
  stateChange: boolean | null;
  /** **받은 JSON 그대로.** 액션 아이템이 이것을 그대로 보여 준다. */
  raw: Record<string, unknown>;
  /** 받은 시각(이 노트북 시계, ms). */
  receivedAtMs: number;
};

export type ObstacleLogLine = { atMs: number; level: 'info' | 'warn'; text: string };

const num = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) return Number(value);
  return null;
};
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
const bool = (value: unknown): boolean | null => (typeof value === 'boolean' ? value : null);

/** 받은 객체 → 스냅샷. 모양이 아니면 null(`detections` 가 배열이 아니다). */
export function parseObstacle(body: unknown, receivedAtMs = Date.now()): ObstacleSnapshot | null {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return null;
  const raw = body as Record<string, unknown>;
  if (!Array.isArray(raw.detections)) return null;
  const detections: ObstacleDetection[] = [];
  for (const item of raw.detections) {
    if (typeof item !== 'object' || item === null) continue;
    const d = item as Record<string, unknown>;
    const box = Array.isArray(d.bbox_xyxy) && d.bbox_xyxy.length === 4 && d.bbox_xyxy.every((v) => num(v) !== null)
      ? (d.bbox_xyxy.map((v) => num(v) as number) as [number, number, number, number])
      : null;
    detections.push({
      id: num(d.id),
      name: str(d.name) ?? t('ob2.1'),
      group: str(d.group),
      relDepth: num(d.rel_depth),
      distanceCm: num(d.distance_cm),
      distanceCmRaw: num(d.distance_cm_raw),
      riskLevel: str(d.risk_level),
      bbox: box,
    });
  }
  return {
    cameraId: str(raw.camera_id),
    timestampSec: num(raw.timestamp),
    detections,
    hasNearObstacle: bool(raw.has_near_obstacle),
    stateChange: bool(raw.state_change),
    raw,
    receivedAtMs,
  };
}

// ── 열 ───────────────────────────────────────────────────────────────────────

export type ObstacleState = {
  latest: ObstacleSnapshot | null;
  /** 마지막 요청이 실패했으면 그 사유. 성공하면 비운다. */
  error: string | null;
  /** 창구로 받았나 직접 받았나. */
  via: 'relay' | 'direct' | null;
  /** 서버 시계가 이 시각(이 노트북 ms)부터 안 바뀌었다. 바뀌고 있으면 null. */
  frozenSinceMs: number | null;
  /** 바뀐 것만 적는 줄 — 가까운 장애물 생김/사라짐 · state_change · 끊김/복구. */
  log: readonly ObstacleLogLine[];
  polling: boolean;
};

export const OBSTACLE_LOG_KEEP = 300;
export const OBSTACLE_POLL_MS = 500;
/** 서버 시계가 이만큼 안 바뀌면 멈춘 것으로 적는다 — 0.5초 주기의 열 배. */
export const OBSTACLE_FROZEN_MS = 5000;

const EMPTY: ObstacleState = { latest: null, error: null, via: null, frozenSinceMs: null, log: [], polling: false };
let state: ObstacleState = EMPTY;
const listeners = new Set<() => void>();

function commit(next: ObstacleState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function obstacleState(): ObstacleState {
  return state;
}

export function subscribeObstacle(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useObstacle(): ObstacleState {
  return useSyncExternalStore(subscribeObstacle, obstacleState, obstacleState);
}

function withLog(log: readonly ObstacleLogLine[], lines: ObstacleLogLine[]): readonly ObstacleLogLine[] {
  if (lines.length === 0) return log;
  const next = [...log, ...lines];
  return next.length > OBSTACLE_LOG_KEEP ? next.slice(-OBSTACLE_LOG_KEEP) : next;
}

const nearWords = (snap: ObstacleSnapshot) => snap.detections
  .filter((d) => d.riskLevel === 'near')
  .map((d) => `${d.name}${d.distanceCm === null ? '' : ` ${d.distanceCm.toFixed(0)}cm`}`)
  .join(', ');

/** 받은 한 건을 얹는다. 바뀐 것만 줄로 남긴다. 검사가 시각을 넣어 부른다. */
export function receiveObstacle(body: unknown, via: 'relay' | 'direct', nowMs = Date.now()): boolean {
  const snap = parseObstacle(body, nowMs);
  if (snap === null) {
    commit({ ...state, error: t('ob2.2'), log: withLog(state.log, state.error === null ? [{ atMs: nowMs, level: 'warn', text: t('ob2.3') }] : []) });
    return false;
  }
  const prev = state.latest;
  const lines: ObstacleLogLine[] = [];
  if (state.error !== null) lines.push({ atMs: nowMs, level: 'info', text: t('ob2.4') });
  if (snap.hasNearObstacle !== null && snap.hasNearObstacle !== (prev?.hasNearObstacle ?? null)) {
    lines.push(snap.hasNearObstacle
      ? { atMs: nowMs, level: 'warn', text: t('ob2.nearPresent', { what: nearWords(snap) || t('ob2.noneMarked') }) }
      : { atMs: nowMs, level: 'info', text: t('ob2.5') });
  }
  if (snap.stateChange === true && prev?.stateChange !== true) lines.push({ atMs: nowMs, level: 'warn', text: 'state_change: true' });
  const sameClock = prev !== null && snap.timestampSec !== null && prev.timestampSec === snap.timestampSec;
  // 멈춤은 줄로 안 적는다 — 판정은 화면이 시각으로 한다(`obstacleFrozen`).
  const frozenSinceMs = sameClock ? (state.frozenSinceMs ?? prev.receivedAtMs) : null;
  commit({ ...state, latest: snap, error: null, via, frozenSinceMs, log: withLog(state.log, lines) });
  return true;
}

/** 실패 한 건. 같은 사유가 이어지면 줄을 또 적지 않는다. */
export function noteObstacleError(reason: string, nowMs = Date.now()): void {
  const lines: ObstacleLogLine[] = state.error === reason ? [] : [{ atMs: nowMs, level: 'warn', text: t('ob2.notReceived', { reason }) }];
  commit({ ...state, error: reason, log: withLog(state.log, lines) });
}

/** 서버 값이 멈췄나 — 서버 시계가 5초 넘게 그대로다. */
export function obstacleFrozen(current: ObstacleState = state, nowMs = Date.now()): boolean {
  return current.frozenSinceMs !== null && nowMs - current.frozenSinceMs >= OBSTACLE_FROZEN_MS;
}

// ── 폴링 — 붙잡은 수를 센다 ────────────────────────────────────────────────────

let holders = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
let fetcher: FetchLike | undefined;
let inFlight = false;

async function tick(): Promise<void> {
  timer = null;
  if (holders === 0) return;
  if (!inFlight) {
    inFlight = true;
    try {
      const outcome = await fetchObstacleJson(fetcher);
      if (holders > 0 && !isReplayingRecord()) {
        if (outcome.ok) receiveObstacle(outcome.body, outcome.via);
        else noteObstacleError(outcome.reason);
      }
    } finally {
      inFlight = false;
    }
  }
  if (holders > 0 && timer === null) timer = setTimeout(() => void tick(), OBSTACLE_POLL_MS);
}

/**
 * 폴링을 붙잡는다. 되돌려주는 함수를 부르면 놓는다 — 마지막으로 놓을 때만 멈춘다.
 * @param customFetcher 검사가 갈아 끼운다.
 */
export function holdObstaclePolling(customFetcher?: FetchLike): () => void {
  // **다시보기 중에는 묻지 않는다** (260915) — 지금 값이 그 판의 기록을 덮으면 다시보기가 거짓말을 한다.
  if (isReplayingRecord()) return () => undefined;
  if (customFetcher !== undefined) fetcher = customFetcher;
  holders += 1;
  if (holders === 1) {
    commit({ ...state, polling: true });
    void tick();
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holders -= 1;
    if (holders === 0) {
      if (timer !== null) { clearTimeout(timer); timer = null; }
      commit({ ...state, polling: false });
    }
  };
}

export function obstacleHolders(): number {
  return holders;
}

/** 검사가 판을 비울 때. */
export function resetObstacle(): void {
  if (timer !== null) { clearTimeout(timer); timer = null; }
  holders = 0;
  fetcher = undefined;
  commit(EMPTY);
}

/** 판이 새로 서면 지난 판의 줄을 걷는다 — 최신 값은 남긴다(같은 카메라의 지금 값이다). */
export function clearObstacleLog(): void {
  commit({ ...state, log: [] });
}

// ── 임무 기록 · 다시보기 (260915) ─────────────────────────────────────────────

export type RecordedObstacle = {
  latest: ObstacleSnapshot | null;
  log: ObstacleLogLine[];
  error: string | null;
  via: 'relay' | 'direct' | null;
};

/** 기록기가 뜨는 몫 — 마지막 값(받은 JSON 그대로 포함)과 이 판의 바뀐 줄. */
export function recordableObstacle(): RecordedObstacle {
  return { latest: state.latest, log: [...state.log], error: state.error, via: state.via };
}

/** 다시보기 — 그 판의 값으로 채운다. **붙잡은 수와 타이머는 건드리지 않는다** — 셈이 어긋나면 폴링이 안 멈춘다. */
export function restoreObstacle(saved: Partial<RecordedObstacle> | undefined): void {
  commit({
    ...state,
    latest: saved?.latest ?? null,
    log: Array.isArray(saved?.log) ? saved.log : [],
    error: saved?.error ?? null,
    via: saved?.via ?? null,
    frozenSinceMs: null,
  });
}

/** 값만 비운다 — 다시보기를 닫을 때. 붙잡은 수와 타이머는 그대로 둔다. */
export function clearObstacleData(): void {
  commit({ ...state, latest: null, log: [], error: null, via: null, frozenSinceMs: null });
}
