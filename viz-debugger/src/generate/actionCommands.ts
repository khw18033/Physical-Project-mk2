/**
 * src/generate/actionCommands.ts (261123 신설 — AI 생성 임무 실행기)
 *
 * **모델이 낸 임무를 걸음 목록으로 바꾼다.** 계획서: `documents/작업프롬프트/작업프롬프트_AI생성임무실행기_구현계획_261123.md`.
 *
 * 정량 명령 임무(`physical/stepScript.ts`)가 이미 「걸음 목록 → 승인 → 시작 → 한 걸음씩」 길을 돈다. 여기서 하는 일은
 * 모델의 액션 아이템을 **그 길이 받는 모양**으로 바꾸는 것뿐이다. 그래서 이 파일은 React · 저장소 · 소켓을 모른다 —
 * `verify:generated-run` 이 Node 에서 그대로 돌린다.
 *
 * ## 절반만 읽고 나머지를 지어내지 않는다
 *
 * 정량 명령과 같은 원칙이다. 받을 수 없는 액션 아이템이 **하나라도** 있으면 그 임무 전체를 실행 불가로 둔다 —
 * 앞부분만 내면 모델이 낸 계획과 다른 것이 로봇에 나간다. 계획 보기(캔버스에 올리기)는 그래도 된다.
 *
 * ## 값은 사람이 채운다
 *
 * 생성 규칙상 거리 · 각도는 적지 않는다(`gen-lab/goldset/action-items.json` rules — 「실행이 경로에서 정하는 값」).
 * 그래서 `turn` · `move_forward` 는 대개 값 없이 온다. 그 값을 **승인 칸에서 사람이 채운다** — 채우기 전에는
 * 실행 가능이 아니다. 모델이 값을 적어 왔으면 미리 채워 두되 사람이 고칠 수 있다.
 *
 * ## 명령이 없는 과업은 사람이 닫는다
 *
 * sense · decide · verify · report 와 액션 아이템이 빈 act 는 장비에 낼 것이 없다. 실행 순서에서 그 차례가 오면
 * 사람이 「확인」 · 「실패로 닫기」로 닫는다. 자동으로 완료하면 하지 않은 판정을 한 것처럼 기록된다.
 */

import type { Task } from '../model/types.ts';
import type { TaskCommand } from '../physical/missionLink.ts';
import { forwardStepCommands, turnStepCommands, TURN_MAX_DEG, TURN_MIN_DEG, FORWARD_MAX_M, FORWARD_MIN_M } from '../physical/stepScript.ts';
import { STOP_ACTION, STOP_REASON } from '../physical/presets.ts';

/** 1단계가 내는 동작 셋. 로봇이 움직이는 것과 서는 것뿐이다. */
export const RUN_ACTIONS = ['turn', 'move_forward', 'abort'] as const;
export type RunAction = (typeof RUN_ACTIONS)[number];

/**
 * **막는 것과 미루는 것을 가른다.** `scan_mission` 은 생성 임무에서 막는다 — 모델이 만든 계획에 문 찾기 스캔이
 * 따라 나가면 안 된다(`data/scenario.ts` 의 `activateGenerated` 가 AI 편 관문을 닫아 두었던 이유). 수문은 2단계다 —
 * 게이트웨이 명령 길(`gateway/commands.ts`)로 내야 하고, 이 실행기는 로봇 브로커로만 낸다.
 */
const BLOCKED_ACTIONS: readonly string[] = ['scan_mission'];
const LATER_ACTIONS: readonly string[] = ['open_gate', 'close_gate'];

export type RejectReason =
  /** 액션 아이템에 동작 이름이 없다. */
  | 'shape'
  /** act 가 아닌 과업에 액션 아이템이 있다 — 생성 규칙 위반(`verify:action-item-shape` 와 같은 규칙). */
  | 'not_act'
  /** 그 장비의 동작 어휘(`equipment.json` actions)에 없다. */
  | 'vocabulary'
  /** 생성 임무에서 막는 동작. */
  | 'blocked'
  /** 2단계에서 다룰 동작. */
  | 'later'
  /** 어휘에는 있지만 이 실행기가 모르는 동작. */
  | 'unsupported'
  /** 장비가 둘 이상이다 — 1단계는 한 임무에 장비 하나다. */
  | 'targets'
  /** 의존성이 돌고 돈다 — 차례를 정할 수 없다. */
  | 'cycle';

export type Rejection = { taskId: string; itemId: string | null; action: string; reason: RejectReason; target?: string | null };

/** 사람이 채울 값 한 칸. `key` 가 값 표의 열쇠다. */
export type FillSlot = {
  key: string;
  taskId: string;
  itemId: string;
  action: 'turn' | 'move_forward';
  param: 'deg' | 'distance_m';
  /** 모델이 적어 온 값. 없으면 null. */
  preset: number | null;
};

export type PlannedItem = { itemId: string; action: RunAction; fill: FillSlot | null };

/** 실행 순서의 한 칸. 명령 과업이거나 사람 확인 과업이다. */
export type PlannedTask = { taskId: string; kind: 'command'; items: PlannedItem[] } | { taskId: string; kind: 'human' };

export type GeneratedRunPlan = {
  /** 의존성 위상 순서. 같은 깊이면 임무에 적힌 차례다. */
  order: PlannedTask[];
  fills: FillSlot[];
  rejected: Rejection[];
  /** 명령을 받을 장비(레지스트리 이름). 명령 과업이 없으면 null. */
  target: string | null;
  commandTasks: number;
  humanTasks: number;
  /** 거부가 없고 명령 과업이 하나 이상이다. 값을 다 채웠는지는 `fillProblems` 가 따로 본다. */
  runnable: boolean;
};

export function fillKey(taskId: string, itemId: string): string {
  return `${taskId}#${itemId}`;
}

function presetOf(params: Record<string, string | number>, name: 'deg' | 'distance_m'): number | null {
  const value = params[name];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * 위상 순서. 남은 것 중 **앞선 과업이 다 끝난 첫 과업**을 고른다 — 같은 깊이에서 임무에 적힌 차례가 지켜진다.
 * 임무 밖을 가리키는 의존성은 무시한다(그 과업은 기다릴 대상이 없다). 돌고 도는 것이 남으면 그 과업들을 돌려준다.
 */
function topoOrder(tasks: readonly Task[]): { order: Task[]; cyclic: Task[] } {
  const known = new Set(tasks.map((task) => task.id));
  const done = new Set<string>();
  const left = [...tasks];
  const order: Task[] = [];
  while (left.length > 0) {
    const index = left.findIndex((task) => task.deps.every((dep) => !known.has(dep) || done.has(dep)));
    if (index < 0) return { order, cyclic: left };
    const [next] = left.splice(index, 1);
    order.push(next);
    done.add(next.id);
  }
  return { order, cyclic: [] };
}

/**
 * **임무 → 실행 계획.** `vocabulary` 는 `equipment/equipment.json` 의 `actions` 표다(장비 → 동작 이름들).
 */
export function planGeneratedRun(
  tasks: readonly Task[],
  vocabulary: Readonly<Record<string, readonly string[]>>,
): GeneratedRunPlan {
  const rejected: Rejection[] = [];
  const fills: FillSlot[] = [];
  const order: PlannedTask[] = [];
  const targets: string[] = [];
  const firstTaskOf = new Map<string, string>();
  const { order: sorted, cyclic } = topoOrder(tasks);
  for (const task of cyclic) rejected.push({ taskId: task.id, itemId: null, action: '', reason: 'cycle' });

  for (const task of sorted) {
    const items = task.actionItems ?? [];
    if (items.length === 0) {
      order.push({ taskId: task.id, kind: 'human' });
      continue;
    }
    if (task.nodeKind !== undefined && task.nodeKind !== 'act') {
      for (const item of items) rejected.push({ taskId: task.id, itemId: item.id, action: item.label, reason: 'not_act' });
      continue;
    }
    const planned: PlannedItem[] = [];
    for (const item of items) {
      const action = typeof item.params.action === 'string' ? item.params.action : item.label;
      const target = item.target ?? task.target;
      const reject = (reason: RejectReason) => rejected.push({ taskId: task.id, itemId: item.id, action, reason, target });
      if (action === '' || target === null || target === '') { reject('shape'); continue; }
      if (!(vocabulary[target] ?? []).includes(action)) { reject('vocabulary'); continue; }
      if (BLOCKED_ACTIONS.includes(action)) { reject('blocked'); continue; }
      if (LATER_ACTIONS.includes(action)) { reject('later'); continue; }
      if (!(RUN_ACTIONS as readonly string[]).includes(action)) { reject('unsupported'); continue; }
      if (!targets.includes(target)) { targets.push(target); firstTaskOf.set(target, task.id); }
      let fill: FillSlot | null = null;
      if (action === 'turn' || action === 'move_forward') {
        const param = action === 'turn' ? 'deg' : 'distance_m';
        fill = { key: fillKey(task.id, item.id), taskId: task.id, itemId: item.id, action, param, preset: presetOf(item.params, param) };
        fills.push(fill);
      }
      planned.push({ itemId: item.id, action: action as RunAction, fill });
    }
    order.push({ taskId: task.id, kind: 'command', items: planned });
  }

  // **장비는 하나다** (1단계). 둘째 장비부터, 그 장비가 처음 나온 과업을 거부로 적는다 — 어느 과업이 갈랐는지 보이게.
  for (const extra of targets.slice(1)) {
    rejected.push({ taskId: firstTaskOf.get(extra) ?? '', itemId: null, action: '', reason: 'targets', target: extra });
  }

  const commandTasks = order.filter((entry) => entry.kind === 'command' && entry.items.length > 0).length;
  return {
    order,
    fills,
    rejected,
    target: targets[0] ?? null,
    commandTasks,
    humanTasks: order.filter((entry) => entry.kind === 'human').length,
    runnable: rejected.length === 0 && commandTasks > 0,
  };
}

export type FillProblem = { key: string; reason: 'missing' | 'range' };

/** 값 한 칸이 받을 수 있는 범위. 정량 명령의 규약 범위와 같다(`stepScript.ts`). */
export function fillRange(param: FillSlot['param']): { min: number; max: number } {
  return param === 'deg' ? { min: TURN_MIN_DEG, max: TURN_MAX_DEG } : { min: FORWARD_MIN_M, max: FORWARD_MAX_M };
}

/**
 * **채운 값의 문제.** 회전은 부호가 방향이다(오른쪽 +, 규약과 같다) — 크기가 5~360° 여야 한다. 직진은 0.05~10 m 다.
 * 10 m 를 넘는 직진은 받지 않는다 — 사람이 칸 하나에 적는 값이고, 더 가야 하면 계획을 다시 세우는 것이 맞다.
 */
export function fillProblems(plan: GeneratedRunPlan, values: Readonly<Record<string, number | undefined>>): FillProblem[] {
  const problems: FillProblem[] = [];
  for (const slot of plan.fills) {
    const value = values[slot.key];
    if (value === undefined || !Number.isFinite(value)) { problems.push({ key: slot.key, reason: 'missing' }); continue; }
    const { min, max } = fillRange(slot.param);
    const size = slot.param === 'deg' ? Math.abs(value) : value;
    if (size < min || size > max) problems.push({ key: slot.key, reason: 'range' });
  }
  return problems;
}

/** 처음 채워 둘 값 — 모델이 적어 온 것만. 없으면 칸이 빈다. */
export function presetValues(plan: GeneratedRunPlan): Record<string, number> {
  const out: Record<string, number> = {};
  for (const slot of plan.fills) if (slot.preset !== null) out[slot.key] = slot.preset;
  return out;
}

/** 실행기가 도는 목록의 한 칸. 승인 때 굳혀 임무에 싣는다(`view.params.generated_run`). */
export type RunItem = { kind: 'command'; taskId: string; steps: TaskCommand[] } | { kind: 'human'; taskId: string };

/**
 * **실행 계획 + 채운 값 → 실행 목록.** 실행 가능하고 값에 문제가 없을 때만 목록이 나온다 — 아니면 null.
 * 걸음은 정량 명령과 같은 함수로 자른다(`turnStepCommands` · `forwardStepCommands`).
 */
export function runItemsOf(plan: GeneratedRunPlan, values: Readonly<Record<string, number | undefined>>): RunItem[] | null {
  if (!plan.runnable || fillProblems(plan, values).length > 0) return null;
  const items: RunItem[] = [];
  for (const entry of plan.order) {
    if (entry.kind === 'human') { items.push({ kind: 'human', taskId: entry.taskId }); continue; }
    const steps: TaskCommand[] = [];
    for (const item of entry.items) {
      // 정지는 화면이 낸 정지다 — 경로 접근의 도착 정지(`approachPlan.ts`)와 같은 이름 · 같은 사유 값이다.
      if (item.action === 'abort') { steps.push({ taskId: entry.taskId, action: STOP_ACTION, parameters: { reason: STOP_REASON.screen } }); continue; }
      const value = values[item.fill?.key ?? ''] as number;
      steps.push(...(item.action === 'turn' ? turnStepCommands(value, entry.taskId) : forwardStepCommands(value, entry.taskId)).steps);
    }
    items.push({ kind: 'command', taskId: entry.taskId, steps });
  }
  return items;
}

/** 임무에 실린 실행 목록. 없으면 빈 배열 — 그 임무는 생성 임무 실행기가 안 돈다. */
export function generatedRunOf(params: Record<string, unknown> | null | undefined): readonly RunItem[] {
  const raw = params?.generated_run;
  return Array.isArray(raw) ? (raw as RunItem[]) : [];
}

// ── 실행 ────────────────────────────────────────────────────────────────────

export type RunOutcome = { ended: 'done' } | { ended: 'failed'; taskId: string; reason: string } | { ended: 'stopped'; taskId: string | null };

/**
 * 실행기가 바깥에 기대는 것. 소켓 · 기록 · 화면은 부르는 쪽이 준다 — 이 함수는 차례만 지킨다.
 */
export type RunDeps = {
  /**
   * 한 과업의 걸음을 **끝까지** 낸다 — 앞 걸음의 종료 응답을 받은 뒤 다음을 내고, 마지막 걸음의 종료까지 기다린다
   * (`robotCommands.ts` 의 `issueStepsToEnd`). 노드를 칠하는 것도 그쪽이다(명령이 과업 id 를 들고 간다).
   */
  issue(steps: readonly TaskCommand[]): Promise<{ sent: boolean; reason?: string | null }>;
  /** 사람 확인을 기다린다. 정지되면 `stopped` 로 끝나야 한다. */
  waitHuman(taskId: string): Promise<'done' | 'failed' | 'stopped'>;
  /** 정지됐는가. 과업 사이마다 본다. */
  stopped(): boolean;
  /** 과업 하나가 시작된다 — 화면 상태용. */
  onTask?(index: number, item: RunItem): void;
};

/**
 * **차례대로 돈다.** 명령 과업은 끝까지 기다리고, 사람 확인 과업은 사람을 기다린다. 하나라도 실패 · 정지면
 * **뒤의 것은 하나도 안 낸다.**
 */
export async function runGenerated(items: readonly RunItem[], deps: RunDeps): Promise<RunOutcome> {
  for (const [index, item] of items.entries()) {
    if (deps.stopped()) return { ended: 'stopped', taskId: item.taskId };
    deps.onTask?.(index, item);
    if (item.kind === 'human') {
      const verdict = await deps.waitHuman(item.taskId);
      if (verdict === 'stopped') return { ended: 'stopped', taskId: item.taskId };
      if (verdict === 'failed') return { ended: 'failed', taskId: item.taskId, reason: 'human' };
      continue;
    }
    // 값이 범위 안이면 걸음이 반드시 하나 이상이다(`fillProblems`). 그래도 비어 있으면 낼 것이 없으니 다음으로 간다.
    if (item.steps.length === 0) continue;
    const outcome = await deps.issue(item.steps);
    if (deps.stopped()) return { ended: 'stopped', taskId: item.taskId };
    if (outcome.sent !== true) return { ended: 'failed', taskId: item.taskId, reason: outcome.reason ?? '' };
  }
  return { ended: 'done' };
}
