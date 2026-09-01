/**
 * src/scenarios/nowPlaying.ts (260901 신설 — 「지금 무엇이 어디서 보이는지」)
 *
 * 사용자의 목적은 **「실행되는 걸 보면서 확인」**이다. 그런데 지금까지 화면은 지금 시각에
 * 무슨 일이 어느 탭에서 일어나는지 말하지 않았다 — 사용자가 탭을 하나씩 눌러 찾아야 했다.
 *
 * 이 파일은 **재생 머리(headSec) 기준 진행 중인 노드 한 줄**과 **그 일이 보이는 탭**을 만든다.
 * 새로 계산하는 것이 없다 — 상태는 `statusesAt()` 이 이미 접어서 돌려주고, 축은
 * `axesOfDrive()`(대본 전체의 축과 같은 규칙), 탭은 `AXIS_TABS` 표에서 나온다.
 *
 * 셸이 그린다(`AppShell`). 탭이 그리면 탭을 옮길 때 사라진다.
 *
 * **대본을 인자로 받는다** — 여기서 `library.ts` 를 열면 JSON import 때문에 Node 에서
 * 안 열려 `verify:scenario-mode` 가 이 규칙을 돌려 볼 수 없다. 부르는 쪽(셸)이 찾아 넘긴다.
 */

import { foldStatuses } from '../data/fold.ts';
import type { MissionView } from '../data/scenario.ts';
import { AXIS_TABS, axesOfDrive, axesOfScript, type ScenarioAxis, type ScenarioTab } from './axes.ts';
import type { ScriptScenario } from './types.ts';

export type NowPlaying = {
  /** 「지금」 한 줄. */
  text: string;
  /** 그 일이 보이는 탭 후보. **둘이면 둘 다 적는다.** 탭①은 늘 살아 있으므로 뺀다. */
  tabs: ScenarioTab[];
};

/** 아직 끝나지 않은 상태들 — 이 중 하나면 「진행 중인 노드」다. */
const ACTIVE = new Set(['running', 'rerunning', 'awaiting_evaluation']);

const TAB_ORDER: ScenarioTab[] = ['debugger', 'overview', 'control', 'metrics', 'video'];

export function nowPlaying(
  view: MissionView,
  /** 이 임무의 대본. 옛 편(구판 세계)은 null — 판정 대상이 아니다(구판 안내 띠가 따로 말한다). */
  script: ScriptScenario | null,
  headSec: number,
  playing: boolean,
): NowPlaying | null {
  if (script === null) return null;

  if (!playing && headSec >= view.durationSec) {
    // 재생 끝 — 마지막 상태 유지. 기존 동작 그대로다.
    return { text: '재생 끝 — 장치는 마지막 상태를 유지합니다', tabs: [] };
  }

  const first = view.milestones[0] ?? null;
  if (!playing && headSec <= 0) {
    // 정지 미리보기 — 사건이 하나도 없다. 시작 상태와 첫 마일스톤을 적는다.
    return {
      text: first === null
        ? 'T+0 · 시작 상태 — 승인하면 재생됩니다 (VZ-U-07)'
        : `T+0 · 시작 상태 — 첫 마일스톤 ${first.id} ${first.title}. 승인하면 재생됩니다 (VZ-U-07)`,
      tabs: [],
    };
  }

  // 그 태스크가 **마지막으로 움직인 시각** — 「지금 창」의 시작이자 진행 중 후보의 정렬 기준.
  const lastMoveAt = new Map<string, number>();
  for (const event of view.events) {
    if (event.atSec > headSec) break;
    lastMoveAt.set(event.nodeId, event.atSec);
  }

  const folded = foldStatuses(headSec, view);
  const active = view.tasks
    .filter((task) => ACTIVE.has(folded.tasks[task.id]?.status ?? 'pending'))
    .sort((a, b) => (lastMoveAt.get(b.id) ?? -1) - (lastMoveAt.get(a.id) ?? -1));
  // 진행 중이 없으면(사건 사이의 틈) 마지막으로 움직인 노드를 적는다 — 비워 두지 않는다.
  const task =
    active[0] ??
    [...view.tasks].sort((a, b) => (lastMoveAt.get(b.id) ?? -1) - (lastMoveAt.get(a.id) ?? -1)).find((t) => lastMoveAt.has(t.id)) ??
    null;

  if (task === null) {
    return { text: `T+${Math.round(headSec)}s · 첫 사건 대기`, tabs: [] };
  }

  const startedAt = lastMoveAt.get(task.id) ?? 0;
  const axes = new Set<ScenarioAxis>();

  // 이 창에서 나간 명령 — 있으면 그 이름을 적고 축은 액추에이터·명령이다(탭③).
  let command: string | null = null;
  for (const cmd of script.commands ?? []) {
    if (cmd.taskId === task.id || (cmd.atSec >= startedAt && cmd.atSec <= headSec)) {
      axes.add('actuator');
      axes.add('command');
      command = cmd.action;
    }
  }
  // 이 창에서 몰린 세계 값 — drive 키가 곧 축이다.
  for (const frame of script.worldTimeline ?? []) {
    if (frame.atSec > headSec) break;
    if (frame.atSec >= startedAt) for (const axis of axesOfDrive(frame.drive)) axes.add(axis);
  }
  // 창 안에 아무것도 없으면(판정만 하는 노드) 대본 전체의 축으로 넓힌다 — 빈 안내는 쓸모가 없다.
  if (axes.size === 0) for (const axis of axesOfScript(script)) axes.add(axis);

  const tabs = new Set<ScenarioTab>();
  for (const axis of axes) for (const tab of AXIS_TABS[axis]) tabs.add(tab);

  const milestone = view.milestones.find((m) => m.id === task.milestone) ?? null;
  const head = milestone === null ? task.title : `${milestone.id} ${task.title}`;

  return {
    // 태스크 제목이 이미 그 명령을 말하고 있으면 덧붙이지 않는다 — 같은 말을 두 번 적지 않는다.
    text: command === null || head.includes(command) ? head : `${head} → ${command} 발행`,
    // 탭①은 늘 살아 있고 사용자가 지금 보고 있을 화면이라 「갈 탭」 후보에서 뺀다.
    tabs: TAB_ORDER.filter((tab) => tab !== 'debugger' && tabs.has(tab)),
  };
}
