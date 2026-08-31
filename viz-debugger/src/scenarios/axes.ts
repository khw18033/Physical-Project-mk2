/**
 * src/scenarios/axes.ts (260831 — 사이트 개선 요구 2)
 *
 * 대본이 실제로 몰아 주는 **축**의 유도 규칙 — 여기 하나뿐이다.
 *
 * 대본 파일에 축 목록을 손으로 적지 않는다. 적으면 대본을 고칠 때 한쪽만 바뀌어
 * 조용히 갈라진다 — 이 저장소가 계속 피해 온 실패다. 그래서 worldTimeline 의 drive 키와
 * commands·map 의 존재에서 **유도**한다. 대본에 값이 실려 있으면 축이 있는 것이고,
 * 없으면 없는 것이다.
 *
 * 화면은 이 축으로 「연결 예정(못 받았다)」과 「이 대본에는 해당 없음(이 이야기에 없다)」을
 * 가른다 — 그 구분이 없으면 시연에서 "왜 여긴 비었냐"에 답할 수 없다.
 */

import { SCRIPT_LIBRARY } from './library.ts';
import type { ScriptScenario } from './types.ts';

export type ScenarioAxis =
  | 'position'
  | 'speed'
  | 'water'
  | 'coverage'
  | 'video'
  | 'actuator'
  | 'command'
  // 아래 둘은 **어느 대본도 몰지 않는다** — 위험도는 AI 파트(VZ-I-08), 관측 지표는
  // 평시 ObservabilityEmitter 몫이라 대본이 몰 것이 아니다. 그 사실을 화면에 적는다.
  | 'risk'
  | 'observability';

export const AXIS_LABEL: Record<ScenarioAxis, string> = {
  position: '위치',
  speed: '속도',
  water: '수위',
  coverage: '커버리지·사각지대',
  video: '영상·탐지',
  actuator: '액추에이터',
  command: '명령',
  risk: '위험도 판정',
  observability: '관측 지표',
};

/** 대본 하나가 몰아 주는 축 — drive 키·commands·map 에서 유도한다. */
export function axesOfScript(script: ScriptScenario): ReadonlySet<ScenarioAxis> {
  const axes = new Set<ScenarioAxis>();
  for (const frame of script.worldTimeline ?? []) {
    const drive = frame.drive;
    if ('position' in drive) axes.add('position');
    if ('speed_mps' in drive) axes.add('speed');
    if ('water_level_m' in drive) axes.add('water');
    if ('coverage' in drive) axes.add('coverage');
    if ('in_view' in drive) axes.add('video');
  }
  if (script.map !== undefined) axes.add('coverage');
  if ((script.commands ?? []).length > 0) {
    axes.add('actuator');
    axes.add('command');
  }
  return axes;
}

/** 임무 id 로 축을 묻는다. 옛 편(legacy — 구판 세계)은 아무 축도 몰지 않는다. */
export function axesOfMission(missionId: string): ReadonlySet<ScenarioAxis> {
  const entry = SCRIPT_LIBRARY.find((candidate) => candidate.missionId === missionId);
  return entry?.script ? axesOfScript(entry.script) : new Set<ScenarioAxis>();
}

/** 이 축이 실제로 보이는 대본들 — 「해당 없음」 자리가 어느 편으로 가면 보이는지 안내할 재료. */
export function scriptsWithAxis(axis: ScenarioAxis): Array<{ missionId: string; title: string }> {
  return SCRIPT_LIBRARY
    .filter((entry) => entry.script !== null && axesOfScript(entry.script).has(axis))
    .map((entry) => ({ missionId: entry.missionId, title: entry.script?.title ?? entry.missionId }));
}
