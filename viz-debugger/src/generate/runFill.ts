/**
 * src/generate/runFill.ts (261123 신설 — AI 생성 임무 실행기)
 *
 * **승인 칸에서 사람이 채운 값.** 임무 id 하나에 값 표 하나다(`fillKey` → 숫자).
 *
 * 승인 문(`data/scenario.ts` 의 `acceptProposal`)이 여기서 값을 읽어 걸음을 굳힌다. 화면과 승인 문이 **같은 표**를 봐야
 * 「칸에 적힌 값」과 「로봇에 나간 값」이 갈리지 않는다. 제안이 바뀌면 그 임무의 표는 그대로 두고 새 임무 id 의 표를 쓴다 —
 * 생성 임무 id 는 판마다 새로 지어진다(`nextGeneratedMissionId`).
 */

import { useSyncExternalStore } from 'react';
import { planGeneratedRun, presetValues, runItemsOf, type GeneratedRunPlan } from './actionCommands.ts';
import type { Task } from '../model/types.ts';
import { registerGeneratedRunResolver } from '../data/scenario.ts';
import equipment from '../../../equipment/equipment.json' with { type: 'json' };

type Values = Readonly<Record<string, number | undefined>>;

let tables: Readonly<Record<string, Values>> = {};
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** 장비 → 동작 어휘. 생성기가 고르는 표와 **같은 파일**이다(`equipment.json` 의 `actions`). */
export function actionVocabulary(): Readonly<Record<string, readonly string[]>> {
  return (equipment as { actions?: Record<string, string[]> }).actions ?? {};
}

/** 그 임무의 실행 계획. 값과 상관없이 과업과 어휘만으로 정해진다. */
export function runPlanOf(tasks: readonly Task[]): GeneratedRunPlan {
  return planGeneratedRun(tasks, actionVocabulary());
}

/**
 * 그 임무의 값 표. 처음 묻는 순간 **모델이 적어 온 값으로** 채워 둔다 — 없으면 칸이 빈다.
 * 지어 채우지 않는다: 빈 칸은 사람이 채워야 승인이 선다.
 */
export function fillValues(missionId: string, tasks: readonly Task[]): Values {
  const found = tables[missionId];
  if (found !== undefined) return found;
  const preset = presetValues(runPlanOf(tasks));
  tables = { ...tables, [missionId]: preset };
  // 화면은 이것을 그리기 밖(`useEffect`)에서 부른다 — 그래서 여기서 알려도 된다.
  emit();
  return preset;
}

export function setFillValue(missionId: string, key: string, value: number | undefined): void {
  const current = tables[missionId] ?? {};
  tables = { ...tables, [missionId]: { ...current, [key]: value } };
  emit();
}

export function subscribeFill(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 화면이 값 표를 본다. 표가 없으면 빈 표다 — 처음 채우기는 `fillValues` 가 한다. */
export function useFillValues(missionId: string): Values {
  return useSyncExternalStore(subscribeFill, () => tables[missionId] ?? EMPTY, () => tables[missionId] ?? EMPTY);
}

const EMPTY: Values = Object.freeze({});

/**
 * **승인 문에 계산을 건다** (`data/scenario.ts` 의 `registerGeneratedRunResolver` 주석 — import 고리를 피하는 자리).
 * 이 파일은 화면(`main.tsx` · `GeneratedRunCard.tsx`)이 읽으므로 앱에서는 늘 걸려 있다.
 *
 * - 실행 불가면 걸음 없음(계획만).
 * - 실행 가능인데 값에 문제가 있으면 `blocked` — 승인하지 않는다.
 * - 아니면 사람이 채운 값으로 굳힌 실행 목록.
 */
registerGeneratedRunResolver((view) => {
  const plan = runPlanOf(view.tasks);
  if (!plan.runnable) return { items: null, blocked: false, fills: [] };
  const values = fillValues(view.missionId, view.tasks);
  const items = runItemsOf(plan, values);
  return { items, blocked: items === null, fills: plan.fills.map((slot) => ({ slot, value: values[slot.key] })) };
});
