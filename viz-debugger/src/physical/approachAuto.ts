/**
 * src/physical/approachAuto.ts (261103 신설 — 「경로대로 이동」을 승인 없이 자동으로)
 *
 * **문 찾기 · 박스 탐지 편에서 경로가 나오면 곧바로 그 경로로 간다.** 전에는 머리줄의 「▶ 경로대로 이동」
 * (`ApproachButton`)을 사람이 눌러야 했다(§1 「한 박자 쉰다」). 이제 기본은 **승인 없이 자동 이동**이고,
 * 필요하면 그 노드(`T-B2`)를 더블클릭해 연 상세에서 「이동 전 승인 필요」를 켠다 — 켜 두면 예전처럼 버튼이 뜬다.
 *
 * ## 설정
 *
 * 편(missionId)마다 따로다 — 문 찾기는 자동, 박스는 승인처럼 갈라 둘 수 있다. `localStorage` 에 남아 새로고침해도
 * 유지된다. 임무 실행 전에 정해 두는 것이 원칙이지만, 이동이 나가기 전이면 판 도중에 바꿔도 그 순간부터 따른다.
 *
 * ## 자동 이동의 규칙
 *
 * - 버튼이 열리는 조건과 **같은 조건**(`canApproach`)에서만 낸다 — 경로가 있고, 아직 안 냈고, 승인된 판이고,
 *   정지·일시정지가 아니다. 발행은 버튼과 같은 `issueApproach` 하나를 지난다(정지 관문 · 추적기 한 벌).
 * - **로봇이 앞 임무를 끝낸 뒤에 낸다** (261103 실측 — `FAILED_PRECONDITION mission_in_progress`). 탐지는 여덟 장을 다
 *   받으면 경로를 내지만, 로봇은 그때 아직 스캔 임무(`T-A3` · 복귀 회전)를 끝내지 않았다. 사람이 누르던 때는 그 사이
 *   몇 초가 저절로 생겼는데 자동 발행은 곧바로 나가 거절당했다. 그래서 낸 명령 중 끝 응답이 안 온 것이 있으면
 *   기다린다(`waiting`). 끝 보고가 {@link ROBOT_IDLE_WAIT_MS} 동안 안 오면 기다림을 접고 버튼을 띄운다.
 * - **한 판에 한 번만** 시도한다(`startedAtMs` 로 판을 가른다). 못 보냈으면 다시 쏘지 않고 버튼을 띄워
 *   사유를 적는다 — 사람이 보고 다시 누른다. 같은 걸음을 말없이 되풀이하면 로봇이 두 번 갈 수 있다.
 * - 다시보기 중에는 안 낸다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { currentMission, recordHuman } from '../data/scenario.ts';
import { appendDetectLog, DETECT_TASKS } from '../detect/detectLog.ts';
import { subscribeDetect } from '../detect/store.ts';
import { isReplayingRecord } from '../record/replayMode.ts';
import { doorScanFlow } from '../scenarios/library.ts';
import { robotClient } from './robotClient.ts';
import { approachWords, canApproach, issueApproach } from './robotCommands.ts';
import { robotSession, subscribeRobot } from './robotSession.ts';

const STORAGE_KEY = 'viz.approachApproval.v1';
/** 로봇이 앞 임무를 끝냈다고 말하기를 기다리는 한도. 한 바퀴 뒤 복귀 회전은 길어도 십수 초다. */
export const ROBOT_IDLE_WAIT_MS = 60_000;
const WAIT_POLL_MS = 1000;

// ── 설정: 이동 전 승인 필요 (기본 꺼짐) ────────────────────────────────────────

function read(): Record<string, boolean> {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, boolean> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (value === true) out[id] = true;
    }
    return out;
  } catch {
    // 저장소가 막혔거나 깨졌다 — 기본값(자동)으로 진행한다.
    return {};
  }
}

let required: Record<string, boolean> = read();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 그 편이 이동 전에 사람 승인을 요구하나. 기본은 아니다(자동 이동). */
export function approachNeedsApproval(missionId: string): boolean {
  return required[missionId] === true;
}

export function useApproachNeedsApproval(missionId: string): boolean {
  return useSyncExternalStore(subscribe, () => approachNeedsApproval(missionId), () => approachNeedsApproval(missionId));
}

export function setApproachNeedsApproval(missionId: string, on: boolean): void {
  if (approachNeedsApproval(missionId) === on) return;
  const next = { ...required };
  if (on) next[missionId] = true;
  else delete next[missionId];
  required = next;
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(required));
  } catch {
    // 이번 세션에만 남는다.
  }
  // 사람이 판의 규칙을 바꾼 것이다 — 기록에 남긴다.
  recordHuman('approach_approval_changed', DETECT_TASKS.approach, { mission: missionId, require_approval: on });
  notify();
  check();
}

// ── 자동 이동 ─────────────────────────────────────────────────────────────────

/** 자동 이동의 지금 상태 — 머리줄 버튼이 읽는다. */
export type AutoApproach =
  | { phase: 'idle' }
  /** 경로는 나왔는데 로봇이 앞 임무를 아직 안 끝냈다. */
  | { phase: 'waiting'; sinceMs: number }
  | { phase: 'sending' }
  | { phase: 'failed'; reason: string };

let auto: AutoApproach = { phase: 'idle' };
/** 이미 자동 시도를 한 판 — `startedAtMs`. */
let attemptedRun: string | null = null;

function setAuto(next: AutoApproach): void {
  auto = next;
  notify();
}

export function autoApproach(): AutoApproach {
  return auto;
}

export function useAutoApproach(): AutoApproach {
  return useSyncExternalStore(subscribe, autoApproach, autoApproach);
}

/**
 * 로봇이 아직 끝 응답을 안 준 **스캔 임무**(`T-A3`). 거절(`mission_in_progress`)을 낳는 것은 이 임무다. 보조 명령
 * (`scan_continue` 등)은 답 없이 끝나기도 해서 보지 않는다 — 그것을 기다리면 멀쩡한 판이 한도까지 선다.
 */
function robotBusyWith(): string | null {
  for (const record of Object.values(robotSession().commands)) {
    if (record.taskId !== DETECT_TASKS.sweep) continue;
    if (record.state === 'issued' || record.state === 'running') return record.action;
  }
  return null;
}

let waitTimer: ReturnType<typeof setTimeout> | null = null;
function checkLater(): void {
  if (waitTimer !== null) return;
  waitTimer = setTimeout(() => { waitTimer = null; check(); }, WAIT_POLL_MS);
  (waitTimer as { unref?: () => void }).unref?.();
}

function runKey(): string {
  return `${currentMission().missionId}:${robotSession().startedAtMs ?? 'none'}`;
}

/** 지금 이 편이 자동으로 이동하는 편인가 — 문 찾기 흐름이고 승인을 요구하지 않는다. */
export function approachIsAuto(missionId = currentMission().missionId): boolean {
  return doorScanFlow(missionId) && !approachNeedsApproval(missionId);
}

/** 한 번 본다. 낼 때가 됐으면 낸다. */
function check(): void {
  const key = runKey();
  // 판이 바뀌면 지난 판의 실패 표시를 내린다.
  if (attemptedRun !== null && attemptedRun !== key && auto.phase !== 'sending') {
    attemptedRun = null;
    if (auto.phase !== 'idle') setAuto({ phase: 'idle' });
  }
  if (isReplayingRecord() || !approachIsAuto() || attemptedRun === key || !canApproach()) {
    if (auto.phase === 'waiting') setAuto({ phase: 'idle' });
    return;
  }
  const busyWith = robotBusyWith();
  if (busyWith !== null) {
    const sinceMs = auto.phase === 'waiting' ? auto.sinceMs : Date.now();
    if (Date.now() - sinceMs < ROBOT_IDLE_WAIT_MS) {
      if (auto.phase !== 'waiting') {
        setAuto({ phase: 'waiting', sinceMs });
        appendDetectLog({
          lane: 'screen', level: 'info',
          say: { key: 'auto.approachWaiting', vars: { action: busyWith } },
          tasks: [DETECT_TASKS.approach],
        });
      }
      checkLater();
      return;
    }
    // 끝 보고가 안 온다 — 말없이 쏘지 않고 사람에게 넘긴다.
    attemptedRun = key;
    const reason = t('auto.robotNoEnd', { action: busyWith, sec: ROBOT_IDLE_WAIT_MS / 1000 });
    appendDetectLog({ lane: 'screen', level: 'warn', say: { key: 'auto.approachFailed', vars: { reason } }, tasks: [DETECT_TASKS.approach] });
    setAuto({ phase: 'failed', reason });
    return;
  }
  attemptedRun = key;
  setAuto({ phase: 'sending' });
  const missionId = currentMission().missionId;
  appendDetectLog({
    lane: 'screen', level: 'info',
    say: { key: 'auto.approachStarted', vars: { route: approachWords() ?? '' } },
    tasks: [DETECT_TASKS.approach],
  });
  void issueApproach(robotClient(), currentMission().params).then((outcome) => {
    if (outcome?.sent === true) { setAuto({ phase: 'idle' }); return; }
    const reason = outcome?.reason ?? '';
    appendDetectLog({
      lane: 'screen', level: 'warn',
      say: { key: 'auto.approachFailed', vars: { reason } },
      tasks: [DETECT_TASKS.approach],
    });
    // 판이 그새 바뀌었으면 이 실패는 지난 판의 것이다.
    if (currentMission().missionId === missionId) setAuto({ phase: 'failed', reason });
    else setAuto({ phase: 'idle' });
  });
}

let started = false;

/** 앱이 살아 있는 동안 한 번 건다(`startTaskRunner` 와 같은 자리) — 화면을 옮겨도 경로가 나오는 순간을 놓치면 안 된다. */
export function startApproachAuto(): () => void {
  if (started) return () => undefined;
  started = true;
  // 저장소를 알리는 도중에 발행하지 않는다 — 한 박자 뒤에 본다.
  const later = () => { setTimeout(check, 0); };
  const offRobot = subscribeRobot(later);
  const offDetect = subscribeDetect(later);
  later();
  return () => {
    offRobot();
    offDetect();
    started = false;
  };
}
