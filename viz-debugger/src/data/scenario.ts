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
 *  - current  : 확정 임무. 화면이 이걸 그린다.
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
 *
 * ## 260904 — 화면이 접는 것이 대본에서 기록 열로 바뀌었다
 *
 * `view.events` 는 이제 **대본의 정의**다. 화면의 원천은 `data/trace.ts` 의 기록 열이고,
 * 거기에 넣는 길은 하나뿐이다(`appendTrace`). 이 파일에서 그 입구를 부르는 자리는 셋이다.
 *
 * | 부르는 자리 | 언제 | 무엇을 넣나 |
 * |---|---|---|
 * | `receiveTrace()` | 통합 빌드 — 게이트웨이 `trace_event` | 받은 봉투 |
 * | 로컬 재생기 (`activateMission(_, 'local')`) | 단독 빌드 — 게이트웨이 없음 | 대본을 시각까지 읽어 흘려보낸다 |
 * | `recordHuman()` | 화면에서 나가는 모든 명령 | `produced_by=human` (`VZ-D-08`) |
 *
 * 기동 직후(`activatedBy: 'boot'`)의 옛 편은 **이미 끝난 과거 임무의 기록**이라 열을 통째로
 * 채워 둔다 — 재생 머리가 처음부터 `durationSec` 에 서 있고 슬라이더가 되감기 도구인 것이
 * 그 뜻이다. 승인을 우회하는 것이 아니다: 승인 선(`VZ-U-07`)이 걸린 것은 **제안과
 * 정지 미리보기**이고, 그 둘은 열이 비어 있다.
 */

import { useSyncExternalStore } from 'react';
import { foldStatuses, type FoldedStatuses } from './fold.ts';
import { MergeScheduler } from './mergeScheduler.ts';
import { appendHuman, appendTrace, resetTrace, traceEvents, traceMissionId } from './trace.ts';
import rawScenario from '../../scenarios/MSN-260826-01.json';
import { libraryEntry } from '../scenarios/library.ts';
import type { ScriptMap, ScriptScenario } from '../scenarios/types.ts';
import type { Hardware, RefEdge, Scenario, ScenarioEvent, TaskStatus, Task } from '../model/types.ts';

export type { FoldedStatuses };
export { traceEvents, traceStats } from './trace.ts';

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
  /**
   * **대본의 정의**다 — 화면의 원천이 아니다 (260904). 로컬 재생기와 목 게이트웨이가 이걸
   * 읽어 기록 열로 흘려보내고, 화면은 흘러온 것만 접는다.
   */
  events: ScenarioEvent[];
  /** 뷰 노드에서 그려도 되는 장비. 옛 편은 hardware 목록의 id 들이다. */
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
/** 로컬 재생기가 대본을 어디까지 읽어 흘려보냈는지. 매 틱 처음부터 훑지 않기 위한 자리다. */
let localCursor = 0;

/**
 * 알림 병합 창 (VZ-I-01 · 100 ms).
 *
 * 20 Hz 수신에서 사건마다 구독자를 깨우면 초당 20번 접고 20번 그린다 — 렌더 예산을 넘긴다.
 * **데이터는 전량 받는다**(열에는 매 건이 들어간다). 묶는 것은 *알림*뿐이고, 규칙도 창
 * 크기도 이미 있는 것을 그대로 쓴다 (`mergeScheduler.ts` · `RENDER_MERGE_WINDOW_MS`).
 *
 * 재생 머리는 창으로 묶고, **제안·승인·미리보기·재생 끝은 창을 건너뛴다**(`commitNow`) —
 * 승인 버튼이 100 ms 늦게 반응하면 그건 그냥 느린 화면이다 (mergeScheduler 규칙 3).
 */
const renderMerge = new MergeScheduler();
renderMerge.subscribe(() => { for (const listener of listeners) listener(); });

/** 상태를 바꾸고 **병합 창**으로 알린다. 재생 머리처럼 초당 여러 번 바뀌는 값. */
function commit(next: Partial<MissionState>): void {
  state = { ...state, ...next };
  renderMerge.mark();
}

/** 상태를 바꾸고 **즉시** 알린다. 늦으면 안 되는 전이. */
function commitNow(next: Partial<MissionState>): void {
  state = { ...state, ...next };
  renderMerge.flushNow();
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

/** 알림 병합 실측값. 자체 관측(`VZ-O-04`)이 읽는다. */
export function missionMergeStats() {
  return renderMerge.stats();
}

const EMPTY_TRACE: readonly ScenarioEvent[] = Object.freeze([]);

/**
 * 그 임무의 기록 열. 열은 임무당 하나이므로, **아직 아무것도 흘러오지 않은 임무**
 * (제안된 대본 · 다른 편)는 빈 열이다 — 지어내지 않는다.
 */
export function traceFor(view: MissionView): readonly ScenarioEvent[] {
  return traceMissionId() === view.missionId ? traceEvents() : EMPTY_TRACE;
}

/**
 * 화면이 그릴 임무 — 제안이 있으면 제안된 대본을 「제안 상태」로 그린다
 * (진행 사건 0건 = 시각 0의 접기 결과, 전부 pending).
 */
export function displayMission(): {
  view: MissionView;
  phase: 'proposal' | 'playing' | 'idle';
  headSec: number;
  /** 그 임무의 기록 열. 화면은 **이것만** 접는다. */
  trace: readonly ScenarioEvent[];
} {
  if (state.proposal !== null) {
    const view = viewForMission(state.proposal.missionId);
    // 제안된 대본은 아직 승인 전이라 흘러온 것이 없다 — 열이 비어 있는 것이 곧 그 사실이다.
    if (view !== null) return { view, phase: 'proposal', headSec: 0, trace: traceFor(view) };
  }
  return {
    view: state.current,
    phase: state.playing ? 'playing' : 'idle',
    headSec: state.headSec,
    trace: traceFor(state.current),
  };
}

// ── 제안 · 승인 · 재생 ────────────────────────────────────────────────────────

/** 발화 매칭 결과를 제안으로 올린다. 게이트웨이(plan 수신)와 단독 빌드(로컬 매칭)가 부른다. */
export function proposeMission(proposal: MissionProposal): void {
  if (viewForMission(proposal.missionId) === null) return;
  // 같은 제안의 중복(로컬 매칭 직후 게이트웨이 plan 도착)은 planId 만 갱신한다.
  if (state.proposal?.missionId === proposal.missionId && proposal.planId === null) return;
  commitNow({ proposal });
}

export function rejectProposal(): void {
  if (state.proposal === null) return;
  commitNow({ proposal: null });
}

/**
 * 승인 → 현재 임무 교체 + 재생 시작.
 * mode 'remote' 는 게이트웨이의 trace_event 가 머리를 밀고(통합),
 * 'local' 은 로컬 재생기가 같은 배속으로 민다(단독 빌드 — 게이트웨이 없음).
 *
 * **어느 쪽이든 기록은 같은 입구로 들어간다** (`appendTrace`). 입구가 둘이면 단독 빌드와
 * 통합 빌드의 되감기가 달라지고, 그게 곧 논문 측정축 D의 오염이다.
 */
export function activateMission(missionId: string, mode: 'remote' | 'local'): void {
  const view = viewForMission(missionId);
  if (view === null) return;
  stopLocalTimer();
  resetTrace(view.missionId);
  localCursor = 0;
  commitNow({ current: view, proposal: null, headSec: 0, playing: true, activatedBy: 'approval' });

  if (mode === 'local') {
    const stepMs = 200;
    localTimer = setInterval(() => {
      const nextHead = state.headSec + (stepMs / 1000) * LOCAL_SPEED;
      if (nextHead >= state.current.durationSec) {
        stopLocalTimer();
        // 남은 사건을 마저 흘려보낸 **뒤에** 머리를 끝에 세운다 — 순서가 바뀌면
        // 마지막 한 틱 동안 화면이 「끝났는데 아직 안 온」 상태를 그린다.
        feedLocalTrace(state.current.durationSec);
        commitNow({ headSec: state.current.durationSec, playing: false });
        return;
      }
      feedLocalTrace(nextHead);
      commit({ headSec: nextHead });
    }, stepMs);
  }
}

/**
 * 로컬 재생기 — **대본을 읽어 게이트웨이와 같은 입구로 기록을 흘려보낸다.**
 * 목 게이트웨이가 하는 일(`gateway/mission-trace.ts`)을 단독 빌드에서 대신하는 자리다.
 */
function feedLocalTrace(headSec: number): void {
  const events = state.current.events;
  while (localCursor < events.length && events[localCursor].atSec <= headSec) {
    appendTrace(state.current.missionId, events[localCursor]);
    localCursor += 1;
  }
}

/**
 * 정지 미리보기 (260831 — 사이트 개선 요구 4 · 우상단 모드 스위치).
 *
 * 현재 임무를 그 대본으로 올리되 **기록 열이 비어 있다** — headSec 0 · playing false 라
 * 탭①은 전부 pending 으로 그린다(제안 상태와 같은 성질). **재생은 여전히 승인 뒤다** —
 * 이 함수는 「그린다」까지이고 승인 선(VZ-U-07 · REQ-1506)을 우회하지 않는다.
 */
export function previewMission(missionId: string): void {
  const view = viewForMission(missionId);
  if (view === null) return;
  stopLocalTimer();
  resetTrace(view.missionId);
  localCursor = 0;
  commitNow({ current: view, proposal: null, headSec: 0, playing: false, activatedBy: 'preview' });
}

function stopLocalTimer(): void {
  if (localTimer !== null) clearInterval(localTimer);
  localTimer = null;
}

/**
 * 게이트웨이 trace_event 수신 (통합 셸의 브리지가 부른다).
 * 다른 임무의 사건은 버린다 — 승인 전에는 애초에 오지 않는다(게이트웨이 규칙).
 *
 * 중복(재접속 뒤 다시 온 같은 `seq`)은 열이 흡수한다 — 새로 생긴 것이 없고 머리도 안
 * 움직이면 화면을 다시 그리지 않는다.
 */
export function receiveTrace(missionId: string, event: ScenarioEvent): void {
  if (missionId !== state.current.missionId) return;
  const fresh = appendTrace(missionId, event);
  const lastAt = state.current.events.at(-1)?.atSec ?? state.current.durationSec;
  if (event.atSec >= lastAt) {
    // 마지막 사건 — 재생 끝. 머리를 durationSec 에 세우고 슬라이더를 되감기 도구로 돌려준다.
    commitNow({ headSec: state.current.durationSec, playing: false });
    return;
  }
  if (!fresh && event.atSec <= state.headSec) return;
  commit({ headSec: Math.max(state.headSec, event.atSec), playing: true });
}

// ── 사람 조작 기록 (260904 — 같은 열로 합쳤다) ───────────────────────────────

/**
 * 화면에서 나가는 명령을 기록한다 (`VZ-D-08`). 전까지는 별도 배열과 `console.log` 가
 * 끝이라 **되감기에 안 보였다** — 기록이라고 부를 수 없었다.
 *
 * `atSec` 는 조작한 그 시각의 재생 머리다. 사건을 만드는 규칙 자체는 `trace.ts` 에 있다 —
 * `produced_by=human` 이 여기저기서 손으로 적히면 그 규칙이 갈라진다.
 */
export function recordHuman(kind: string, nodeId = state.current.missionId, payload: Record<string, unknown> = {}) {
  const event = appendHuman(
    state.current.missionId,
    kind,
    nodeId,
    Math.min(state.headSec, state.current.durationSec),
    payload,
  );
  // 열이 자랐으면 화면을 다시 그린다 — 되감기 타임라인에 그 조작이 떠야 한다.
  if (event !== null) commitNow({});
  return event;
}

// ── 상태 접기 (REQ-1405 되감기 · 마일스톤은 태스크를 접은 결과) ──────────────────

/**
 * 시각 t 의 계층 상태. 접는 규칙은 `fold.ts` 하나에 있고 여기서는 **접는 대상**만
 * 정한다 — 화면이 그리는 임무(제안 중이면 제안된 대본)의 **기록 열**이다.
 */
export function statusesAt(second: number, view: MissionView = displayMission().view): FoldedStatuses {
  return foldStatuses(second, view, traceFor(view));
}

/**
 * 기동 직후의 옛 편 — **이미 끝난 과거 임무의 기록**이라 열을 채워 둔다.
 * 게이트웨이가 있으면 같은 사건이 `trace_event` 로 다시 오는데, `seq` 가 같으므로
 * 열이 중복으로 흡수한다 (`VZ-I-02` 와 같은 성질).
 */
resetTrace(state.current.missionId);
for (const event of state.current.events) appendTrace(state.current.missionId, event);
