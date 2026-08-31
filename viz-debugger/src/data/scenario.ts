/**
 * src/data/scenario.ts
 *
 * **현재 임무 저장소** (260831 — 대본 재생에서 개조).
 *
 * 통합 전에는 `MSN-260826-01.json` 한 편이 모듈 상수로 박혀 있었고, 되감기 시각(41·95)·
 * 마일스톤 수(7건)·배정 대상(MS-C)까지 그 한 편에 맞춰 손으로 적혀 있었다. 이제 이
 * 저장소가 「어느 대본이든」 현재 임무로 든다 — **기동 시 기본은 여전히 `MSN-260826-01`**
 * (HCI 전달본 그대로)이고, 대본이 승인되면 바뀐다.
 *
 * 세 가지 상태:
 *  - current  : 확정 임무. 화면 다섯이 이걸 그린다.
 *  - proposal : 발화가 대본에 매칭돼 **제안 상태**로 뜬 것 (VZ-U-07 · REQ-1506).
 *               승인 전에는 진행 사건이 하나도 없다 — 화면은 전부 pending 으로 그린다.
 *  - headSec  : 재생 머리. 게이트웨이의 trace_event 수신(통합) 또는 로컬 재생기(단독)가
 *               민다. 재생이 끝나면 durationSec 에 서고 슬라이더는 되감기 도구가 된다.
 *
 * **마일스톤 상태는 정적 필드가 아니라 태스크 상태를 접은 결과다** — `statusesAt()` 이
 * 태스크와 마일스톤을 함께 돌려준다. 옛 파일의 정적 status 는 무시하되 지우지 않고,
 * 태스크가 없는 마일스톤(옛 파일의 MS-A·B·D~G)만 그 값으로 그린다(접을 재료가 없다).
 *
 * 이 파일은 `tabs/` 를 import 하지 않는다 — 탭① 단독 빌드의 경계다(verify:standalone).
 */

import { useSyncExternalStore } from 'react';
import rawScenario from '../../scenarios/MSN-260826-01.json';
import { libraryEntry } from '../scenarios/library.ts';
import type { ScriptMap, ScriptScenario } from '../scenarios/types.ts';
import { TraceStore } from '../shared/stores/traceStore.ts';
import type { Hardware, RefEdge, Scenario, ScenarioEvent, TaskStatus, Task } from '../model/types.ts';

/** 옛 파일 원본. HCI 전달본·논문용 — 한 글자도 고치지 않는다(verify:scenario). */
export const scenario = rawScenario as Scenario;

/**
 * 로컬 재생 배속(단독 빌드). 게이트웨이의 VIZ_SCENARIO_SPEED 기본값과 같은 20이다 —
 * 대본마다·환경마다 다른 배속을 두면 둘을 비교할 때 축이 달라진다.
 */
export const LOCAL_SPEED = 20;

// ── 화면이 그리는 형태 ────────────────────────────────────────────────────────

export type MissionMilestone = {
  id: string;
  title: string;
  assignedTargets: string[];
  /** 옛 파일의 정적 status. 태스크가 없는 마일스톤의 마지막 근거다. 대본에는 없다. */
  staticStatus: TaskStatus | null;
};

export type MissionView = {
  missionId: string;
  /** 상단 바의 임무 이름 아래 한 줄. */
  label: string;
  world: 'registry' | 'legacy';
  utteranceText: string;
  durationSec: number;
  milestones: MissionMilestone[];
  /** milestone 필드가 반드시 채워져 있다 — 옛 파일은 전부 MS-C(태스크 7개가 다 그 소속). */
  tasks: Task[];
  events: ScenarioEvent[];
  /** 탭②~⑤에서 그려도 되는 장비. 옛 편은 hardware 목록의 id 들이다. */
  cast: string[];
  /** 옛 편만 있다. 대본(registry 세계)은 cast 로 그린다 — 실측값을 지어내지 않는다. */
  hardware: Hardware[] | null;
  /** 대본의 편별 상수(위험 수위 선 등). 화면이 읽는다. */
  params: Record<string, unknown>;
  /** 2편의 구역 맵(503호 평면·카메라 시야·사각지대 칸). 다른 편은 null — 맵이 없다고 적는다. */
  map: ScriptMap | null;
  /** 되돌아가는 참조 엣지 (260831 노드 분화). deps 가 아니다 — 그리기 전용. */
  refEdges: RefEdge[];
};

function legacyView(): MissionView {
  return {
    missionId: scenario.missionId,
    label: '415동 → 503동 이동',
    world: 'legacy',
    utteranceText: scenario.utterance.text,
    durationSec: scenario.durationSec,
    milestones: scenario.milestones.map((m) => ({
      id: m.id,
      title: m.title,
      assignedTargets: m.assignedTargets,
      staticStatus: m.status ?? null,
    })),
    // 옛 파일의 태스크는 전부 MS-C 소속이다(파일에 필드가 없어 여기서 채운다).
    tasks: scenario.tasks.map((t) => ({ ...t, milestone: t.milestone ?? 'MS-C' })),
    events: scenario.events,
    cast: (scenario.hardware ?? []).map((h) => h.id),
    hardware: scenario.hardware ?? null,
    params: {},
    map: null,
    refEdges: [],
  };
}

function scriptToView(script: ScriptScenario): MissionView {
  return {
    missionId: script.missionId,
    label: script.title,
    world: 'registry',
    utteranceText: script.utterance.text,
    durationSec: script.durationSec,
    milestones: script.milestones.map((m) => ({
      id: m.id,
      title: m.title,
      assignedTargets: m.assignedTargets,
      staticStatus: null,
    })),
    tasks: script.tasks,
    events: script.events,
    cast: script.cast,
    hardware: null,
    params: script.params ?? {},
    map: script.map ?? null,
    refEdges: script.refEdges ?? [],
  };
}

/** 라이브러리의 임무를 화면 형태로. 모르는 id 면 null — 지어내지 않는다. */
export function viewForMission(missionId: string): MissionView | null {
  if (missionId === scenario.missionId) return legacyView();
  const entry = libraryEntry(missionId);
  if (entry?.script) return scriptToView(entry.script);
  return null;
}

// ── 저장소 ───────────────────────────────────────────────────────────────────

export type MissionProposal = {
  missionId: string;
  title: string;
  /** 어느 키워드가 맞아서 이 대본이 골라졌는지 — 화면이 그 자리에서 보여준다. */
  keywords: string[];
  planId: string | null;
  world: 'registry' | 'legacy';
};

export type MissionState = {
  current: MissionView;
  proposal: MissionProposal | null;
  /** 재생 머리(대본 시각 초). 재생 중이 아니면 durationSec — 슬라이더는 되감기 도구다. */
  headSec: number;
  playing: boolean;
  /**
   * 기동 기본(boot) / 승인 활성화(approval) / 모드 스위치의 정지 미리보기(preview).
   * 구판 세계 안내 띠와 「정지 미리보기」 표기의 근거다.
   */
  activatedBy: 'boot' | 'approval' | 'preview';
};

let state: MissionState = {
  current: legacyView(),
  proposal: null,
  headSec: (rawScenario as Scenario).durationSec,
  playing: false,
  activatedBy: 'boot',
};

const listeners = new Set<() => void>();
let localTimer: ReturnType<typeof setInterval> | null = null;

/** 수신한 trace_event 의 기록 열 (덧붙이기 전용). 임무가 바뀌면 새로 시작한다. */
export let missionTrace = new TraceStore();

function commit(next: Partial<MissionState>): void {
  state = { ...state, ...next };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getMissionState(): MissionState {
  return state;
}

export function useMission(): MissionState {
  return useSyncExternalStore(subscribe, getMissionState, getMissionState);
}

export function currentMission(): MissionView {
  return state.current;
}

/**
 * 화면이 그릴 임무 — 제안이 있으면 제안된 대본을 「제안 상태」로 그린다
 * (진행 사건 0건 = 시각 0의 접기 결과, 전부 pending).
 */
export function displayMission(): { view: MissionView; phase: 'proposal' | 'playing' | 'idle'; headSec: number } {
  if (state.proposal !== null) {
    const view = viewForMission(state.proposal.missionId);
    if (view !== null) return { view, phase: 'proposal', headSec: 0 };
  }
  return { view: state.current, phase: state.playing ? 'playing' : 'idle', headSec: state.headSec };
}

// ── 제안 · 승인 · 재생 ────────────────────────────────────────────────────────

/** 발화 매칭 결과를 제안으로 올린다. 게이트웨이(plan 수신)와 단독 빌드(로컬 매칭)가 부른다. */
export function proposeMission(proposal: MissionProposal): void {
  if (viewForMission(proposal.missionId) === null) return;
  // 같은 제안의 중복(로컬 매칭 직후 게이트웨이 plan 도착)은 planId 만 갱신한다.
  if (state.proposal?.missionId === proposal.missionId && proposal.planId === null) return;
  commit({ proposal });
}

export function rejectProposal(): void {
  if (state.proposal === null) return;
  commit({ proposal: null });
}

/**
 * 승인 → 현재 임무 교체 + 재생 시작.
 * mode 'remote' 는 게이트웨이의 trace_event 가 머리를 밀고(통합),
 * 'local' 은 로컬 재생기가 같은 배속으로 민다(단독 빌드 — 게이트웨이 없음).
 */
export function activateMission(missionId: string, mode: 'remote' | 'local'): void {
  const view = viewForMission(missionId);
  if (view === null) return;
  stopLocalTimer();
  missionTrace = new TraceStore();
  commit({ current: view, proposal: null, headSec: 0, playing: true, activatedBy: 'approval' });

  if (mode === 'local') {
    const stepMs = 200;
    localTimer = setInterval(() => {
      const nextHead = state.headSec + (stepMs / 1000) * LOCAL_SPEED;
      if (nextHead >= state.current.durationSec) {
        stopLocalTimer();
        commit({ headSec: state.current.durationSec, playing: false });
        return;
      }
      commit({ headSec: nextHead });
    }, stepMs);
  }
}

/**
 * 정지 미리보기 (260831 — 사이트 개선 요구 4 · 우상단 모드 스위치).
 *
 * 현재 임무를 그 대본으로 올리되 **사건이 하나도 없다** — headSec 0 · playing false 라
 * 탭①은 전부 pending 으로 그린다(제안 상태와 같은 성질). **재생은 여전히 승인 뒤다** —
 * 이 함수는 「그린다」까지이고 승인 선(VZ-U-07 · REQ-1506)을 우회하지 않는다.
 */
export function previewMission(missionId: string): void {
  const view = viewForMission(missionId);
  if (view === null) return;
  stopLocalTimer();
  missionTrace = new TraceStore();
  commit({ current: view, proposal: null, headSec: 0, playing: false, activatedBy: 'preview' });
}

function stopLocalTimer(): void {
  if (localTimer !== null) clearInterval(localTimer);
  localTimer = null;
}

/**
 * 게이트웨이 trace_event 수신 (통합 셸의 브리지가 부른다).
 * 다른 임무의 사건은 버린다 — 승인 전에는 애초에 오지 않는다(게이트웨이 규칙).
 */
export function receiveTrace(missionId: string, event: ScenarioEvent): void {
  if (missionId !== state.current.missionId) return;
  missionTrace.append(event);
  const lastAt = state.current.events.at(-1)?.atSec ?? state.current.durationSec;
  if (event.atSec >= lastAt) {
    // 마지막 사건 — 재생 끝. 머리를 durationSec 에 세우고 슬라이더를 되감기 도구로 돌려준다.
    commit({ headSec: state.current.durationSec, playing: false });
    return;
  }
  commit({ headSec: Math.max(state.headSec, event.atSec), playing: true });
}

// ── 사람 조작 기록 (기존 그대로 — 임무 id 만 저장소를 본다) ─────────────────────

export const humanTrace: ScenarioEvent[] = [];

export function recordHuman(kind: string, nodeId = state.current.missionId, payload: Record<string, unknown> = {}) {
  const event: ScenarioEvent & { payload: Record<string, unknown> } = {
    seq: 10_000 + humanTrace.length, atSec: state.current.durationSec, nodeId,
    status: 'rerunning', kind, producedBy: 'human', payload,
  };
  humanTrace.push(event);
  console.log('[mock trace-event]', event);
  return event;
}

// ── 상태 접기 (REQ-1405 되감기 · 마일스톤은 태스크를 접은 결과) ──────────────────

export type FoldedStatuses = {
  tasks: Record<string, { status: TaskStatus; attempt: number }>;
  milestones: Record<string, TaskStatus>;
};

/**
 * 시각 t 의 계층 상태. **마일스톤도 함께 돌려준다** — 되감기하면 태스크와 마일스톤이
 * 같이 되돌아가야 한다. 접는 대상은 화면이 그리는 임무(제안 중이면 제안된 대본)다.
 */
export function statusesAt(second: number, view: MissionView = displayMission().view): FoldedStatuses {
  const tasks = Object.fromEntries(
    view.tasks.map((task) => [task.id, { status: 'pending' as TaskStatus, attempt: 1 }]),
  );
  for (const event of view.events) {
    if (event.atSec > second) break;
    tasks[event.nodeId] = { status: event.status, attempt: event.attempt ?? tasks[event.nodeId]?.attempt ?? 1 };
  }

  const milestones: Record<string, TaskStatus> = {};
  for (const milestone of view.milestones) {
    const own = view.tasks.filter((task) => task.milestone === milestone.id);
    if (own.length === 0) {
      // 접을 재료가 없다 — 옛 파일의 정적 status 로만 그린다 (대본에는 이런 마일스톤이 없다).
      milestones[milestone.id] = milestone.staticStatus ?? 'pending';
      continue;
    }
    const statuses = own.map((task) => tasks[task.id]?.status ?? 'pending');
    if (statuses.every((s) => s === 'done')) milestones[milestone.id] = 'done';
    else if (statuses.some((s) => s === 'failed')) milestones[milestone.id] = 'failed';
    else if (statuses.every((s) => s === 'not_executed')) milestones[milestone.id] = 'not_executed';
    else if (statuses.every((s) => s === 'skipped')) milestones[milestone.id] = 'skipped';
    else if (statuses.every((s) => s === 'pending')) milestones[milestone.id] = 'pending';
    else milestones[milestone.id] = 'running';
  }

  return { tasks, milestones };
}
