/**
 * src/detect/status/history.ts (261124 신설 — 객체 탐지 상태판 · 변경 기록)
 *
 * **data_stream 은 모델이 바뀐 기록을 남기지 않는다.** 그래서 가시화가 조회할 때마다 앞 값과 비교해 사건을 만든다
 * (`diffDetectSnapshot` — 순수 함수, `verify:detect-status` 가 그대로 부른다).
 *
 * ## 임무 판이 돌 때만 적는다 (261124 사용자 결정)
 *
 * 기록기가 판 폴더를 잡고 쓰는 동안(`recorderStatus().state === 'recording'`)만 사건을 쌓는다. 판 폴더가 새로 서면 지난
 * 사건을 비우고 첫 줄에 「기록 시작 — 지금 모델 · 대상」을 적는다 — 기록이 그 앞을 모른다는 것을 숨기지 않는다.
 * 쌓인 사건은 그 판의 `progress.json`(`detectModels`)에 실려 임무 이력에서 다시 열린다.
 *
 * 임무가 없을 때는 비교 기준(앞 값)만 갱신하고 적지 않는다.
 *
 * ## 끊긴 동안은 모델을 지우지 않는다
 *
 * `/health` 가 실패하면 그 포트의 모델 · 대상을 앞 값 그대로 들고 간다. 안 그러면 끊김 한 번에 「모델 −」 이 줄줄이 찍히고,
 * 다시 붙으면 「모델 +」 가 또 찍힌다 — 바뀐 것은 연결뿐인데.
 */

import { useSyncExternalStore } from 'react';
import type { DetectSourceRow } from './summary.ts';
import type { TargetInfo } from './targets.ts';

export type DetectEventKind = 'start' | 'modelUp' | 'modelDown' | 'modelRestart' | 'targets' | 'profile' | 'scanStart' | 'scanEnd' | 'down' | 'up';

export type DetectEvent = {
  atMs: number;
  base: string;
  /** 소스 이름(모르면 주소). */
  source: string;
  kind: DetectEventKind;
  model?: string;
  before?: string;
  after?: string;
  /** 끊긴 길이(ms) — `up` 에만. */
  downMs?: number;
  /** 덧붙임 — 대상이 바뀔 때 프로필 판 변화(`v11 → v12`). */
  detail?: string;
};

export type BaseSnapshot = {
  source: string;
  reachable: boolean;
  /** 끊긴 시각 — 끊겨 있는 동안만. */
  downSinceMs: number | null;
  /** 살아 있는 모델 → run · 누계. */
  models: Readonly<Record<string, { run: string | null; results: number | null }>>;
  targets: readonly string[] | null;
  profileVersion: number | null;
  scanId: string | null;
};

export type DetectSnapshot = Readonly<Record<string, BaseSnapshot>>;

const sameList = (a: readonly string[] | null, b: readonly string[] | null) =>
  a !== null && b !== null && [...a].sort().join('\u0000') === [...b].sort().join('\u0000');

/**
 * 판이 그린 줄 → 비교용 한 장. 끊긴 포트는 앞 값의 모델 · 대상을 들고 간다(파일 머리).
 * `targets` 는 포트 → 지정 탐지(없으면 그 포트는 대상 없음).
 */
export function snapshotOf(
  rows: readonly DetectSourceRow[],
  targets: Readonly<Record<string, TargetInfo | null>>,
  prev: DetectSnapshot,
  atMs: number,
): DetectSnapshot {
  const out: Record<string, BaseSnapshot> = {};
  for (const row of rows) {
    if (row.state === 'waiting') {
      if (prev[row.base] !== undefined) out[row.base] = prev[row.base];
      continue;
    }
    const before = prev[row.base];
    const source = row.source ?? before?.source ?? row.base;
    if (row.state === 'down') {
      out[row.base] = before === undefined
        ? { source, reachable: false, downSinceMs: atMs, models: {}, targets: null, profileVersion: null, scanId: null }
        : { ...before, reachable: false, downSinceMs: before.reachable ? atMs : before.downSinceMs };
      continue;
    }
    const info = targets[row.base] ?? null;
    const models: Record<string, { run: string | null; results: number | null }> = {};
    for (const m of row.live) models[m.model] = { run: m.run, results: m.results };
    out[row.base] = {
      source,
      reachable: true,
      downSinceMs: null,
      models,
      // 대상을 못 읽은 순간(창구 오류)은 앞 값을 든다 — 읽기 실패를 「대상 바뀜」으로 적지 않는다.
      targets: info === null ? null : (info.targets ?? before?.targets ?? null),
      profileVersion: info === null ? null : (info.profileVersion ?? before?.profileVersion ?? null),
      scanId: row.busyScanId,
    };
  }
  return out;
}

/** 앞 · 뒤 한 장씩 → 사건. 처음 보는 포트는 사건이 없다(기록 시작 줄이 적는다). */
export function diffDetectSnapshot(prev: DetectSnapshot, next: DetectSnapshot, atMs: number): DetectEvent[] {
  const events: DetectEvent[] = [];
  for (const [base, now] of Object.entries(next)) {
    const was = prev[base];
    if (was === undefined) continue;
    const at = { atMs, base, source: now.source };
    if (was.reachable && !now.reachable) { events.push({ ...at, kind: 'down' }); continue; }
    if (!now.reachable) continue;
    if (!was.reachable) events.push({ ...at, kind: 'up', ...(was.downSinceMs === null ? {} : { downMs: atMs - was.downSinceMs }) });
    for (const [model, info] of Object.entries(now.models)) {
      const old = was.models[model];
      if (old === undefined) events.push({ ...at, kind: 'modelUp', model, ...(info.run === null ? {} : { after: info.run }) });
      else if ((old.run !== null && info.run !== null && old.run !== info.run)
        || (old.results !== null && info.results !== null && info.results < old.results)) {
        events.push({ ...at, kind: 'modelRestart', model, ...(old.run === null ? {} : { before: old.run }), ...(info.run === null ? {} : { after: info.run }) });
      }
    }
    for (const model of Object.keys(was.models)) {
      if (now.models[model] === undefined) events.push({ ...at, kind: 'modelDown', model });
    }
    if (was.targets !== null && now.targets !== null && !sameList(was.targets, now.targets)) {
      events.push({
        ...at, kind: 'targets', before: was.targets.join(' · '), after: now.targets.join(' · '),
        ...(was.profileVersion !== now.profileVersion && now.profileVersion !== null ? { detail: `v${was.profileVersion ?? '?'} → v${now.profileVersion}` } : {}),
      });
    } else if (was.profileVersion !== null && now.profileVersion !== null && was.profileVersion !== now.profileVersion) {
      events.push({ ...at, kind: 'profile', before: `v${was.profileVersion}`, after: `v${now.profileVersion}` });
    }
    if (was.scanId !== now.scanId) {
      if (was.scanId !== null) events.push({ ...at, kind: 'scanEnd', before: was.scanId });
      if (now.scanId !== null) events.push({ ...at, kind: 'scanStart', after: now.scanId });
    }
  }
  return events;
}

/** 기록 시작 줄 — 그 순간 포트마다 모델 · 대상. */
export function startEvents(snap: DetectSnapshot, atMs: number): DetectEvent[] {
  return Object.entries(snap).filter(([, s]) => s.reachable).map(([base, s]) => ({
    atMs, base, source: s.source, kind: 'start' as const,
    after: Object.keys(s.models).sort().join(' · '),
    ...(s.targets === null ? {} : { before: s.targets.join(' · ') }),
  }));
}

// ── 저장소 ────────────────────────────────────────────────────────────────

export const DETECT_HISTORY_MAX = 200;

export type DetectHistoryState = {
  /** 지금 적고 있는가(임무 판이 돌고 있다). */
  recording: boolean;
  /** 기록에서 연 판이면 그 폴더. */
  recorded: { date: string; run: string } | null;
  events: readonly DetectEvent[];
};

let state: DetectHistoryState = { recording: false, recorded: null, events: [] };
let last: DetectSnapshot = {};
/** 지금 적고 있는 판 폴더 — 바뀌면 새로 시작한다. */
let folder: string | null = null;
const listeners = new Set<() => void>();

function commit(next: DetectHistoryState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function detectHistory(): DetectHistoryState {
  return state;
}

export function useDetectHistory(): DetectHistoryState {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    detectHistory, detectHistory,
  );
}

/**
 * 판이 조회할 때마다 부른다. `runFolder` 는 기록기가 쓰고 있는 판 폴더(안 쓰면 null) — 있을 때만 적는다.
 * 다시보기(기록에서 연 판) 동안은 부르지 않는다 — 화면이 지난 판을 보이는 중이다.
 */
export function noteDetectSnapshot(snap: DetectSnapshot, runFolder: string | null, atMs: number): void {
  const prev = last;
  last = snap;
  // 다시보기에서 돌아왔다 — 지난 판의 사건을 걷는다(판은 다시보기 동안 이것을 안 부른다).
  if (state.recorded !== null) { folder = null; commit({ recording: false, recorded: null, events: [] }); }
  if (runFolder === null) {
    if (state.recording) commit({ ...state, recording: false });
    folder = null;
    return;
  }
  if (runFolder !== folder) {
    folder = runFolder;
    commit({ recording: true, recorded: null, events: startEvents(snap, atMs) });
    return;
  }
  const added = diffDetectSnapshot(prev, snap, atMs);
  if (!state.recording) commit({ ...state, recording: true });
  if (added.length === 0) return;
  commit({ ...state, recording: true, events: [...state.events, ...added].slice(-DETECT_HISTORY_MAX) });
}

/** 판이 그린 줄로 한 번에 — 앞 값(`last`)을 기준으로 한 장을 만들고 적는다. */
export function noteDetectRows(
  rows: readonly DetectSourceRow[],
  targets: Readonly<Record<string, TargetInfo | null>>,
  runFolder: string | null,
  atMs: number,
): void {
  noteDetectSnapshot(snapshotOf(rows, targets, last, atMs), runFolder, atMs);
}

/** 판 기록에 싣는 것 — 이 판의 사건이 있을 때만. */
export function recordableDetectHistory(): readonly DetectEvent[] | null {
  return state.recorded === null && state.events.length > 0 ? state.events : null;
}

const isEvent = (value: unknown): value is DetectEvent => value !== null && typeof value === 'object'
  && typeof (value as DetectEvent).atMs === 'number' && typeof (value as DetectEvent).base === 'string'
  && typeof (value as DetectEvent).kind === 'string';

/** 임무 이력에서 판을 열 때. 없거나 모양이 틀리면 비운다 — 지금 판의 사건이 지난 판 자리에 남으면 안 된다. */
export function restoreDetectHistory(saved: unknown, recorded: { date: string; run: string }): void {
  const events = Array.isArray(saved) ? saved.filter(isEvent) : [];
  folder = null;
  commit({ recording: false, recorded, events });
}

/** 다시보기를 닫을 때 · 검사. */
export function resetDetectHistory(): void {
  last = {};
  folder = null;
  commit({ recording: false, recorded: null, events: [] });
}
