import rawScenario from '../../scenarios/MSN-260826-01.json';
import type { Scenario, ScenarioEvent, TaskStatus } from '../model/types.ts';

export const scenario = rawScenario as Scenario;
export const humanTrace: ScenarioEvent[] = [];

export function recordHuman(kind: string, nodeId = scenario.missionId, payload: Record<string, unknown> = {}) {
  const event: ScenarioEvent & { payload: Record<string, unknown> } = {
    seq: 10_000 + humanTrace.length, atSec: scenario.durationSec, nodeId,
    status: 'rerunning', kind, producedBy: 'human', payload,
  };
  humanTrace.push(event);
  console.log('[mock trace-event]', event);
  return event;
}

export function statusesAt(second: number): Record<string, { status: TaskStatus; attempt: number }> {
  const state = Object.fromEntries(scenario.tasks.map((task) => [task.id, { status: 'pending' as TaskStatus, attempt: 1 }]));
  for (const event of scenario.events) {
    if (event.atSec > second) break;
    state[event.nodeId] = { status: event.status, attempt: event.attempt ?? state[event.nodeId]?.attempt ?? 1 };
  }
  return state;
}
